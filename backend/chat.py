"""Single-process conversation state for the local portfolio demo."""
from dataclasses import dataclass, field
from datetime import datetime
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.llm import ModelCallError
from backend.locations import find_city
from backend.plan_view import plan_view
from backend.providers.airport_lookup import AirportChoice, catalog_airport, pick_airports
from backend.providers.http import ProviderError
from backend.schemas import TripPreferences
from backend.services.station_selection import StationChoice, exact_station, label, station_matches_city

TRAIN_CLASSES = {"CC", "EC", "3A", "2A", "1A", "SL"}
_CLASS_CODE = "(?:" + "|".join(sorted(TRAIN_CLASSES)) + ")"
_CLASS_ONLY_QUESTIONS = {
    "which train class would you prefer?",
    "what train class would you prefer?",
    "please provide: train class (e.g. cc).",
}
_GENERIC_INTAKE_REPLY = "Please tell me what you'd like to plan or change."
_ROUND_TRIP_EXAMPLE = (
    "I couldn't read the trip details. For a round trip with one destination, try: "
    "Plan a round trip from [station] to [station] by CC train for 2 adults. "
    "Depart on [day month year] and return on [day month year]."
)
FLIGHT_CLASSES = {"economy", "premium economy", "business", "first"}
RETAINED = ("preferences", "transport", "hotels", "places", "itinerary", "costs")
REQUIRED_LABELS = {
    "origin": "departure city", "destination": "destination city",
    "departure_date": "departure date", "return_date": "return date", "adults": "number of adults",
    "transport_mode": "train, flight, or comparison", "train_class": "train class (e.g. CC)",
    "flight_class": "flight cabin (e.g. Economy)",
}


def _explicit_train_class(message: str) -> str | None:
    """Recognize a single positive literal, leaving other choices to the Supervisor."""
    if re.search(r"\b(?:no|not|cannot|without|avoid|except|never|unless|whether|if|either|or|instead of|\w+n['’]t)\b",
                 message, re.IGNORECASE):
        return None
    codes = set(re.findall(rf"\b{_CLASS_CODE}\b", message.upper()))
    if len(codes) != 1:
        return None
    code = codes.pop()
    if re.search(rf"\b(?:by\s+{code}\s+train\b|train\s+class\s*[:=]\s*{code}\b)", message, re.IGNORECASE):
        return code
    return None


def _explicit_round_trip(message: str) -> dict:
    """Read only the complete train or flight template; never guess a missing field."""
    place = r"[\w .’'-]{1,100}"
    date_text = r"\d{1,2} [A-Za-z]+ \d{4}"
    cabin = r"economy|premium economy|business|first"
    match = re.fullmatch(
        rf"Plan a round trip from (?P<origin>{place}?) to (?P<destination>{place}?) "
        rf"by (?:(?P<train_class>{_CLASS_CODE}) train|(?P<flight_class>{cabin}) flight) "
        rf"for (?P<adults>[1-6]) adults?\. "
        rf"Depart on (?P<departure_date>{date_text}) and return on (?P<return_date>{date_text})\.?",
        " ".join(message.split()), re.IGNORECASE,
    )
    if not match:
        return {}
    fields = match.groupdict()
    if any(re.search(r"\b(?:and|or|via|to|then|through)\b", fields[name], re.IGNORECASE)
           for name in ("origin", "destination")):
        return {}
    try:
        dates = {name: datetime.strptime(fields[name], "%d %B %Y").date()
                 for name in ("departure_date", "return_date")}
    except ValueError:
        return {}
    mode = "train" if fields["train_class"] else "flight"
    return {k: v for k, v in fields.items() if v is not None} | dates | {
        "transport_mode": mode, "adults": int(fields["adults"]),
    }


def chat_constraints(p: TripPreferences) -> tuple[list[str], str | None]:
    if p.currency != "INR":
        return [], "Please use INR for this demo."
    if p.adults is not None and p.adults > 6:
        return [], "Please choose one to six adults for this demo."
    if p.departure_date and p.departure_date <= datetime.now(ZoneInfo("Asia/Kolkata")).date():
        return [], "Please give a future departure date."
    if p.departure_date and p.return_date and (p.return_date - p.departure_date).days > 7:
        return [], "Please choose a trip of one to seven nights."
    missing = p.missing_required()
    if p.transport_mode is None:
        missing.append("transport_mode")
    if p.transport_mode in ("train", "compare"):
        if not p.train_class:
            missing.append("train_class")
        elif p.train_class.upper() not in TRAIN_CLASSES:
            return [], "Choose one of these train classes: CC, EC, 3A, 2A, 1A, SL."
    if p.transport_mode in ("flight", "compare"):
        if not p.flight_class:
            missing.append("flight_class")
        elif p.flight_class.casefold() not in FLIGHT_CLASSES:
            return [], "Choose Economy, Premium Economy, Business, or First for the flight cabin."
    return missing, None


@dataclass
class TripChat:
    # Pending input is separate so clarification cannot invalidate the plan on screen.
    current: TripPreferences = field(default_factory=lambda: TripPreferences(currency="INR"))
    pending: TripPreferences | None = None
    question: str | None = None
    state: dict = field(default_factory=dict)
    view: dict | None = None
    station_choice: StationChoice | None = None
    airport_choice: AirportChoice | None = None

    def respond(self, message, supervisor, run, lookup_stations, lookup_airports):
        if choice := self.airport_choice or self.station_choice:
            kind = "airport" if self.airport_choice else "station"
            if message.strip().casefold().rstrip(".") == f"cancel {kind} selection":
                self.airport_choice = self.station_choice = self.pending = self.question = None
                return self.reply(f"{kind.title()} selection cancelled. Tell me where you'd like to travel.")
            code = re.sub(r"^use\s+", "", message.strip(), flags=re.IGNORECASE).rstrip(".").upper()
            selected = next((s for s in choice.matches if code == s.code), None)
            if selected is None:
                return self.reply(choice.question())
            self.airport_choice = self.station_choice = None
            return self._resolve_and_plan(choice.apply(self.pending, selected), run, lookup_stations, lookup_airports)

        before = self.pending or self.current
        patch, question = _explicit_round_trip(message), None
        if not patch:
            try:
                turn = supervisor(message, before, chat_question=self.question, browser_chat=True)
            except ModelCallError as error:
                if error.http_status == 429:
                    return self.reply("Groq rate-limited this message. Wait for capacity before trying again.")
                return self.reply(_ROUND_TRIP_EXAMPLE)
            question = turn.decision.clarification_question
            patch = turn.patch
            if turn.decision.intent in ("question", "unsupported"):
                answer = (turn.decision.answer or "").strip()
                if answer and answer != _GENERIC_INTAKE_REPLY:
                    return self.reply(answer)
                return self.reply(question or _ROUND_TRIP_EXAMPLE)
        try:
            candidate = TripPreferences.model_validate(before.model_dump() | patch)
        except ValidationError:
            return self.reply("Check that the stations are different and the return date follows departure.")

        if candidate.transport_mode in ("train", "compare"):
            explicit_class = _explicit_train_class(message)
            if explicit_class and candidate.train_class is None and "train_class" not in patch:
                candidate.train_class = explicit_class
            if (explicit_class and candidate.train_class
                    and candidate.train_class.upper() == explicit_class
                    and (question or "").strip().casefold() in _CLASS_ONLY_QUESTIONS):
                question = None

        missing, error = chat_constraints(candidate)
        if error:
            return self.reply(error)
        normalized = {}
        for field_name in ("origin", "destination"):
            value = getattr(candidate, field_name)
            city = find_city(value)
            normalized[field_name] = city.name if city else value
            changed = label(normalized[field_name]).casefold() != label(getattr(before, field_name)).casefold()
            if changed or candidate.transport_mode not in ("train", "compare"):
                normalized[f"{field_name}_station"] = None
            if changed or candidate.transport_mode not in ("flight", "compare"):
                normalized[f"{field_name}_airport"] = None
        if candidate.origin and candidate.destination and (
                normalized["origin"].casefold() == normalized["destination"].casefold()):
            return self.reply("Choose different cities and stations for departure and destination.")
        candidate = candidate.model_copy(update=normalized | {
            "train_class": candidate.train_class.upper() if candidate.train_class else None,
        })
        if missing or question:
            self.pending = candidate
            self.question = question or (
                "Please provide: " + ", ".join(REQUIRED_LABELS[name] for name in missing) + "."
            )
            return self.reply(self.question)
        return self._resolve_and_plan(candidate, run, lookup_stations, lookup_airports)

    def _resolve_and_plan(self, candidate, run, lookup_stations, lookup_airports):
        if candidate.transport_mode in ("flight", "compare"):
            for field_name in ("origin", "destination"):
                if getattr(candidate, f"{field_name}_airport"):
                    continue
                query = " ".join(getattr(candidate, field_name).split())
                if len(query) > 100:
                    return self._pause(candidate, "Please give a shorter city or airport name, or an IATA code.")
                selected = catalog_airport(query)
                options = ()
                if not selected:
                    try:
                        selected, options = pick_airports(query, lookup_airports(query))
                    except ProviderError:
                        return self._pause(candidate, "Airport lookup is unavailable right now. No flight search was started.")
                choice = AirportChoice(field_name, query, options)
                if selected:
                    candidate = choice.apply(candidate, selected)
                    continue
                if not options:
                    return self._pause(candidate, f"No Indian airport match verified for {query}. Try a city and state or an IATA code.")
                self.airport_choice = choice
                return self._pause(candidate, choice.question())
            if (candidate.origin_airport == candidate.destination_airport
                    or candidate.origin.casefold() == candidate.destination.casefold()):
                return self._pause(candidate, "Choose different cities and airports for departure and destination.")

        if candidate.transport_mode in ("train", "compare"):
            for field_name in ("origin", "destination"):
                if getattr(candidate, f"{field_name}_station"):
                    continue
                query = " ".join(getattr(candidate, field_name).split())
                if city := find_city(query):
                    setattr(candidate, f"{field_name}_station", city.station)
                    continue
                if len(query) > 100:
                    return self._pause(candidate, "Please give a shorter railway station name or code.")
                try:
                    matches = lookup_stations(query)
                except ProviderError:
                    return self._pause(candidate, "Station lookup is unavailable right now. No train search was started.")
                if candidate.transport_mode == "compare":
                    matches = [station for station in matches if station_matches_city(station, query)]
                    if not matches:
                        return self._pause(candidate, f"No railway station verified for {query} in this comparison. "
                                           "Try flights only, or choose a different city.")
                if not matches:
                    return self._pause(candidate, f"No railway station matched {query}. Please try a station name or code.")
                choice = StationChoice(field_name, query, tuple(matches))
                selected = exact_station(query, matches)
                if selected is None:
                    self.station_choice = choice
                    return self._pause(candidate, choice.question())
                candidate = choice.apply(candidate, selected)
            if (candidate.origin_station == candidate.destination_station
                    or candidate.origin.casefold() == candidate.destination.casefold()):
                return self._pause(candidate, "Choose different cities and stations for departure and destination.")
        if candidate == self.current and self.view and self.view["days"]:
            self.pending = self.question = None
            return self.reply("The plan is unchanged. Tell me which dates, transport, or hotel filters to change.")

        # Pass only normalized planning state to LangGraph; each turn gets fresh clients.
        seed = {key: self.state[key] for key in RETAINED if key in self.state}
        result = run(candidate, seed)
        view = plan_view(result, candidate)
        self.pending = self.question = None
        if not view["days"] and self.view and self.view["days"]:
            reply = self.reply("I couldn't complete that revision. The previous plan is still shown.")
            reply["turn_warnings"] = view["warnings"]
            return reply
        self.current, self.state, self.view = candidate, {k: result[k] for k in RETAINED if k in result}, view
        if not view["days"]:
            return self.reply("I have partial results, but no validated itinerary. See the warnings below.")
        return self.reply("I've updated your plan." if seed.get("itinerary") else "Here's your trip plan. You can ask me to change it.")

    def _pause(self, candidate, question):
        self.pending, self.question = candidate, question
        return self.reply(question)

    def reply(self, message: str) -> dict:
        return {"reply": message, "plan": self.view}
