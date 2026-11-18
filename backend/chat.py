"""Single-process conversation state for the local portfolio demo."""
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.llm import ModelCallError
from backend.plan_view import plan_view
from backend.schemas import TripPreferences

ROUTE = {"origin": "Delhi", "destination": "Jaipur", "currency": "INR"}
TRAIN_CLASSES = {"CC", "EC", "3A", "2A", "1A", "SL"}
FLIGHT_CLASSES = {"economy", "premium economy", "business", "first"}
RETAINED = ("preferences", "transport", "hotels", "places", "itinerary", "costs")
REQUIRED_LABELS = {
    "departure_date": "departure date", "return_date": "return date", "adults": "number of adults",
    "transport_mode": "train, flight, or comparison", "train_class": "train class (e.g. CC)",
    "flight_class": "flight cabin (e.g. Economy)",
}


def chat_constraints(p: TripPreferences) -> tuple[list[str], str | None]:
    if (p.origin or "").casefold() != "delhi" or (p.destination or "").casefold() != "jaipur":
        return [], "This checkpoint supports Delhi → Jaipur round trips only. Please keep that route."
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
    current: TripPreferences = field(default_factory=lambda: TripPreferences(**ROUTE))
    pending: TripPreferences | None = None
    question: str | None = None
    state: dict = field(default_factory=dict)
    view: dict | None = None

    def respond(self, message, supervisor, run):
        before = self.pending or self.current
        try:
            turn = supervisor(message, before, chat_question=self.question, browser_chat=True)
            candidate = TripPreferences.model_validate(before.model_dump() | turn.patch)
        except ModelCallError as error:
            if error.http_status == 429:
                return self.reply("Groq rate-limited this message. Wait for capacity before trying again.")
            return self.reply("I couldn't apply that request. Please restate the details you want to change.")
        if turn.decision.intent in ("question", "unsupported"):
            return self.reply(turn.decision.answer or "Please tell me what you'd like to plan or change.")

        candidate = candidate.model_copy(update={
            "origin": "Delhi" if (candidate.origin or "").casefold() == "delhi" else candidate.origin,
            "destination": "Jaipur" if (candidate.destination or "").casefold() == "jaipur" else candidate.destination,
            "train_class": candidate.train_class.upper() if candidate.train_class else None,
        })
        missing, error = chat_constraints(candidate)
        if error:
            return self.reply(error)
        if missing or turn.decision.clarification_question:
            self.pending = candidate
            self.question = turn.decision.clarification_question or (
                "Please provide: " + ", ".join(REQUIRED_LABELS[name] for name in missing) + "."
            )
            return self.reply(self.question)

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

    def reply(self, message: str) -> dict:
        return {"reply": message, "plan": self.view}
