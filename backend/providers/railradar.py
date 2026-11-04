"""Station lookup, dated schedules, a small class-checked shortlist, then fares."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.providers.http import ProviderError
from backend.providers.serpapi import SearchResult, money
from backend.schemas import PriceQuote, Source, StationCandidate, TrainTimetable, TransportOffer
from backend.services.demo_fares import apply_demo_fare

INDIA = ZoneInfo("Asia/Kolkata")
CLASSES = {"1A", "2A", "3A", "3E", "CC", "EC", "EA", "FC", "SL", "2S", "VS", "CH", "SH", "VC", "EV"}


@dataclass(frozen=True)
class StationBinding:
    code: str
    city: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Z0-9]{1,10}", self.code) or not self.city.strip():
            raise ValueError("A selected station needs a valid code and display city")


def source(response, id):
    metadata = response.data.get("meta")
    raw = metadata.get("timestamp") if isinstance(metadata, dict) else None
    try:
        timestamp = datetime.fromisoformat(raw) if isinstance(raw, str) else None
        if timestamp is not None and timestamp.tzinfo is None:
            timestamp = None
    except ValueError:
        timestamp = None
    return Source(provider="railradar", fetched_at=response.fetched_at, provider_data_at=timestamp,
                  source_id=id, url="https://railradar.in/")


def parse_stations(response):
    rows = response.data.get("data")
    if not isinstance(rows, list):
        raise ProviderError("invalid_station_results_shape", status=200)
    items, warnings, seen = [], [], set()
    for index, item in enumerate(rows):
        try:
            if not isinstance(item, dict):
                raise ValueError("Invalid station")
            if item.get("isActive") is False:
                continue
            station = StationCandidate(code=item["code"].upper(), name=item["name"], city=item.get("city"),
                latitude=item.get("lat"), longitude=item.get("lng"), source=source(response, "station:" + item["code"].upper()))
            if station.code not in seen:
                items.append(station); seen.add(station.code)
        except (ValidationError, ValueError, KeyError, TypeError, AttributeError):
            warnings.append(f"Skipped invalid station record at index {index}.")
    return SearchResult(items, warnings, {"top_level_keys": list(response.data)})


def parse_between(response, p, origin, destination, day):
    data = response.data.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("trains"), list):
        raise ProviderError("invalid_trains_between_shape", status=200)
    for key, expected in (("from", origin.code), ("to", destination.code)):
        value = data.get(key)
        if not isinstance(value, dict) or not isinstance(value.get("code"), str) or value["code"].upper() != expected:
            raise ProviderError("rail_route_response_mismatch", status=200)
    offers, warnings, seen = [], [], set()
    for index, item in enumerate(data["trains"]):
        try:
            train, start, end = item["train"], item["from"], item["to"]
            number = train["number"]
            if not isinstance(number, str) or not re.fullmatch(r"[0-9]{5}", number):
                raise ValueError("Unsupported train identifier")
            if start["code"].upper() != origin.code or end["code"].upper() != destination.code:
                raise ValueError("Wrong station route")
            from_day, to_day = start["day"], end["day"]
            if type(from_day) is not int or type(to_day) is not int or from_day < 1 or not 0 <= to_day - from_day <= 10:
                raise ValueError("Invalid relative day")
            # The query date is the boarding-station date, not train-origin date.
            departure = datetime.combine(day, time.fromisoformat(start["departure"]), INDIA)
            arrival = datetime.combine(day + timedelta(days=to_day - from_day), time.fromisoformat(end["arrival"]), INDIA)
            duration = money(item.get("duration"))
            if duration is not None and duration != (arrival - departure).total_seconds() / 60:
                raise ValueError("Conflicting duration")
            id = f"train:{number}:{origin.code}:{destination.code}:{day.isoformat()}"
            if id in seen:
                continue
            offers.append(TransportOffer(id=id, mode="train", origin=origin.city, destination=destination.city,
                departure=departure, arrival=arrival, adults=p.adults, train_number=number, train_name=train["name"],
                departure_station=origin.code, arrival_station=destination.code,
                price=PriceQuote(currency="INR", notes=["Scheduled service only; fare, class and seats are not yet verified."]), source=source(response, id)))
            seen.add(id)
        except (ValidationError, ValueError, KeyError, TypeError, AttributeError):
            warnings.append(f"Skipped train record at index {index}: unsupported identifier or inconsistent route/day/time.")
    warnings.append("Schedules and operated classes do not confirm seat availability. Only standard five-digit services are normalized.")
    return SearchResult(offers, warnings, {"top_level_keys": list(response.data), "raw_train_count": len(data["trains"])})


def parse_timetable(response, number):
    data = response.data.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("train"), dict):
        raise ProviderError("invalid_timetable_shape", status=200)
    train = data["train"]
    if str(train.get("number")) != number:
        raise ProviderError("timetable_train_mismatch", status=200)
    classes = train.get("availableClasses", train.get("classes", []))
    if not isinstance(classes, list) or any(not isinstance(c, str) for c in classes):
        raise ProviderError("invalid_operated_classes_shape", status=200)
    route = data.get("route", [])
    if not isinstance(route, list):
        raise ProviderError("invalid_timetable_route_shape", status=200)
    stops = [r["station"]["code"].upper() for r in route if isinstance(r, dict) and isinstance(r.get("station"), dict)
             and isinstance(r["station"].get("code"), str) and re.fullmatch(r"[A-Za-z0-9]{1,10}", r["station"]["code"])]
    bookable = train.get("isPrsBookable")
    return TrainTimetable(train_number=number, train_name=train["name"], operated_classes=[c.upper() for c in classes],
        is_prs_bookable=bookable if type(bookable) is bool else None, stop_codes=stops, source=source(response, "timetable:" + number))


def apply_fare(response, offer, travel_class):
    data = response.data.get("data")
    if not isinstance(data, dict) or str(data.get("trainNumber")) != offer.train_number or not isinstance(data.get("breakdown"), dict):
        raise ProviderError("invalid_fare_or_train_mismatch", status=200)
    expected = {"source": offer.departure_station, "destination": offer.arrival_station,
                "journeyDate": offer.departure.date().isoformat(), "classCode": travel_class, "quotaCode": "GN"}
    if any(k in data and str(data[k]) != v for k, v in expected.items()):
        raise ProviderError("fare_scope_response_mismatch", status=200)
    breakdown = data["breakdown"]
    amount = money(breakdown.get("totalFare"))
    quote = PriceQuote(amount=amount, currency="INR", basis="unverified", covers_all_travelers=False, taxes_included=None,
        notes=["Fare requested for this train, station pair, boarding date, class and General quota (GN).",
               "The response does not fully establish passenger scope or all payable charges; amount is not multiplied by adults.",
               "An itemized GST field is retained as evidence, not assumed to prove a complete payable total."])
    values = offer.model_dump() | {"travel_class": travel_class, "price": quote.model_dump(), "source": source(response, offer.id).model_dump()}
    updated = TransportOffer.model_validate(values)
    # Only numeric fare components are saved; no raw response/private content.
    components = {k: str(value) for k, raw in breakdown.items() if (value := money(raw)) is not None}
    return updated, components


class RailRadarAdapter:
    def __init__(self, http, *, fare_mode="mock"):
        if fare_mode not in ("mock", "live"):
            raise ValueError("Train fare mode must be mock or live")
        self.http = http
        self.fare_mode = fare_mode
        self.last_result = None
        self.timetables, self.fare_components, self.priced_offer_ids = [], {}, []

    def stations(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 100:
            raise ValueError("Station query must contain 1–100 characters")
        return parse_stations(self.http.get("/v1/lookup/search/stations", {"q": query.strip(), "limit": 5}))

    def timetable(self, number):
        if not isinstance(number, str) or not re.fullmatch(r"[0-9]{5}", number):
            raise ValueError("This adapter supports standard five-digit train numbers")
        return parse_timetable(self.http.get(f"/v1/trains/{number}", {"haltsOnly": "true"}), number)

    def search_leg(self, p, origin, destination, *, leg="outbound", shortlist_limit=2):
        if leg not in ("outbound", "return") or p.missing_required() or type(shortlist_limit) is not int or not 1 <= shortlist_limit <= 2:
            raise ValueError("A complete trip and a one/two-train shortlist are required")
        cities = (p.origin, p.destination) if leg == "outbound" else (p.destination, p.origin)
        if (origin.city.casefold(), destination.city.casefold()) != tuple(c.casefold() for c in cities) or origin.code == destination.code:
            raise ValueError("Selected station bindings do not match the trip route")
        if p.currency not in (None, "INR") or not p.train_class or p.train_class.upper() not in CLASSES:
            raise ValueError("Rail fare search needs an explicit supported class and INR pricing")
        self.timetables, self.fare_components, self.priced_offer_ids = [], {}, []
        self.last_result = None
        day = p.departure_date if leg == "outbound" else p.return_date
        self.last_result = parse_between(self.http.get(f"/v1/trains/between/{origin.code}/{destination.code}",
            {"date": day.isoformat(), "byCity": "false", "live": "false"}), p, origin, destination, day)
        shortlist = sorted(self.last_result.items, key=lambda o: (o.arrival - o.departure, o.departure))[:shortlist_limit]
        for offer in shortlist:
            # Details are needed here to check coach class before spending a fare request.
            timetable = self.timetable(offer.train_number)
            self.timetables.append(timetable)
            if timetable.is_prs_bookable is False or p.train_class.upper() not in timetable.operated_classes:
                self.last_result.warnings.append(f"Train {offer.train_number} is not confirmed as a reserved service operating the requested class.")
                continue
            if timetable.stop_codes.count(origin.code) != 1 or timetable.stop_codes.count(destination.code) != 1 or timetable.stop_codes.index(origin.code) >= timetable.stop_codes.index(destination.code):
                self.last_result.warnings.append(f"Train {offer.train_number} timetable did not confirm the ordered station pair; no fare requested.")
                continue
            # Keep verified class knowledge even when a paid fare call fails.
            confirmed = TransportOffer.model_validate(offer.model_dump() | {"travel_class": p.train_class.upper(),
                "price": offer.price.model_dump() | {"notes": ["Scheduled service and requested coach class confirmed; fare and seats remain unverified."]}})
            self.last_result.items = [confirmed if o.id == offer.id else o for o in self.last_result.items]
            if self.fare_mode == "mock":
                priced, components = apply_demo_fare(confirmed, timetable, p.train_class), {}
            else:
                response = self.http.get(f"/v1/trains/{offer.train_number}/fare", {"source": origin.code, "destination": destination.code,
                    "journeyDate": day.isoformat(), "classCode": p.train_class.upper(), "quotaCode": "GN"})
                priced, components = apply_fare(response, confirmed, p.train_class.upper())
            self.last_result.items = [priced if o.id == offer.id else o for o in self.last_result.items]
            self.fare_components[offer.id] = components
            if priced.price.amount is not None:
                self.priced_offer_ids.append(offer.id)
            if self.fare_mode == "live":
                break  # One paid fare maximum; no automatic fallback to mock.
        if self.fare_mode == "mock" and self.priced_offer_ids:
            self.last_result.warnings.append("ASSUMED DEMO FARES: prices and any resulting budget comparison are illustrative, not verified railway costs.")
        if not self.priced_offer_ids:
            self.last_result.warnings.append("No usable fare was obtained within the bounded shortlist; remaining services were not queried.")
        return self.last_result
