"""One-way flight retrieval with explicit airport/timezone bindings."""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from backend.providers.http import ProviderError
from backend.providers.serpapi import SearchResult, money, provider_time, public_link
from backend.schemas import FlightSegment, PriceQuote, Source, TransportOffer


CLASSES = {"economy": 1, "premium economy": 2, "business": 3, "first": 4}


@dataclass(frozen=True)
class AirportLocation:
    code: str
    city: str
    timezone: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Z]{3}", self.code) or not self.city.strip():
            raise ValueError("Airport binding requires an IATA code and city")
        ZoneInfo(self.timezone)  # Reject unknown zones before spending a request.


def segment_time(airport, zones):
    code = airport["id"]
    if code not in zones:
        raise ValueError("Unresolved airport timezone")
    local = datetime.strptime(airport["time"], "%Y-%m-%d %H:%M")
    zone = ZoneInfo(zones[code])
    first, second = local.replace(tzinfo=zone, fold=0), local.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset() or first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local:
        raise ValueError("Ambiguous or nonexistent local flight time")
    return first


def parse_flights(response, p, origin, destination, journey_date, currency, airport_timezones=None):
    body = response.data
    echoed = body.get("search_parameters", {})
    if not isinstance(echoed, dict):
        raise ProviderError("invalid_flight_search_parameters_shape", status=200)
    expected = {"departure_id": origin.code, "arrival_id": destination.code, "outbound_date": journey_date.isoformat(),
                "type": "2", "adults": str(p.adults), "currency": currency}
    if any(k in echoed and str(echoed[k]) != v for k, v in expected.items()):
        raise ProviderError("flight_query_response_mismatch", status=200)
    if any(str(echoed.get(k, 0)) != "0" for k in ("children", "infants_in_seat", "infants_on_lap")):
        raise ProviderError("unexpected_child_passenger_scope", status=200)
    scope_matches = all(str(echoed.get(k)) == v for k, v in expected.items())
    zones = dict(airport_timezones or {}) | {origin.code: origin.timezone, destination.code: destination.timezone}
    collections = [body.get("best_flights", []), body.get("other_flights", [])]
    if any(not isinstance(rows, list) for rows in collections):
        raise ProviderError("invalid_flight_results_shape", status=200)
    offers, warnings, seen = [], [], set()
    for index, item in enumerate(collections[0] + collections[1]):
        if not isinstance(item, dict):
            warnings.append(f"Skipped malformed flight record at index {index}.")
            continue
        try:
            # A round-trip amount can never be reused as a one-way fare.
            if item.get("type") is not None and item["type"].casefold().replace("-", " ") != "one way":
                raise ValueError("Not a one-way quote")
            raw_segments = item["flights"]
            if not isinstance(raw_segments, list) or not raw_segments:
                raise ValueError("Missing segments")
            segments = []
            for segment in raw_segments:
                dep, arr = segment["departure_airport"], segment["arrival_airport"]
                segments.append(FlightSegment(departure_airport=dep["id"], arrival_airport=arr["id"],
                    departure=segment_time(dep, zones), arrival=segment_time(arr, zones),
                    flight_number=segment.get("flight_number"), airline=segment.get("airline"), travel_class=segment.get("travel_class")))
            if segments[0].departure_airport != origin.code or segments[-1].arrival_airport != destination.code:
                raise ValueError("Wrong airport route")
            if segments[0].departure.date() != journey_date:
                raise ValueError("Wrong departure date")
            for previous, following in zip(segments, segments[1:]):
                if previous.arrival_airport != following.departure_airport or following.departure < previous.arrival:
                    raise ValueError("Unsupported airport transfer or inconsistent segment order")
            classes = {s.travel_class for s in segments}
            travel_class = segments[0].travel_class if len(classes) == 1 else "Mixed cabin"
            amount = money(item.get("price"))
            signature = {"segments": [s.model_dump(mode="json") for s in segments], "amount": str(amount),
                         "currency": currency, "adults": p.adults}
            id = "flight:" + hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:24]
            if id in seen:
                continue
            metadata = body.get("search_metadata")
            url = public_link(metadata.get("google_flights_url")) if isinstance(metadata, dict) else None
            notes = ["One-way search quote; not a round-trip bundle or reserved fare.",
                     "Taxes, baggage and booking fees require source confirmation."]
            if p.adults > 1:
                notes.append("Multi-passenger price coverage is unverified; do not multiply or claim an all-traveler total.")
            offer = TransportOffer(id=id, mode="flight", origin=origin.city, destination=destination.city,
                departure=segments[0].departure, arrival=segments[-1].arrival, adults=p.adults, travel_class=travel_class,
                segments=segments, price=PriceQuote(amount=amount, currency=currency,
                    basis="whole_leg" if scope_matches else "unverified", covers_all_travelers=scope_matches and p.adults == 1,
                    taxes_included=None, notes=notes),
                source=Source(provider="serpapi_google_flights", fetched_at=response.fetched_at,
                    provider_data_at=provider_time(body), source_id=id, url=url))
            offers.append(offer); seen.add(id)
        except (ValidationError, ValueError, KeyError, TypeError, AttributeError):
            warnings.append(f"Skipped flight record at index {index}: invalid route/date/segments or unresolved airport timezone.")
    if not scope_matches:
        warnings.append("Flight search scope was not fully echoed; fare basis remains unverified.")
    if offers:
        warnings.append("Quoted flight prices are not confirmed payable totals; seat availability is unverified.")
    return SearchResult(offers, warnings, {"top_level_keys": list(body),
        "best_flight_count": len(collections[0]), "other_flight_count": len(collections[1])})


class FlightAdapter:
    def __init__(self, http, *, airport_timezones=None):
        self.http = http
        self.airport_timezones = dict(airport_timezones or {})
        for zone in self.airport_timezones.values():
            ZoneInfo(zone)

    def search_leg(self, p, origin_airport, destination_airport, *, leg="outbound"):
        if leg not in ("outbound", "return") or p.missing_required():
            raise ValueError("Flight search requires a complete route, dates, adults and valid leg")
        expected_cities = (p.origin, p.destination) if leg == "outbound" else (p.destination, p.origin)
        if (origin_airport.city.casefold(), destination_airport.city.casefold()) != tuple(c.casefold() for c in expected_cities):
            raise ValueError("Airport bindings do not match requested city route")
        if origin_airport.code == destination_airport.code:
            raise ValueError("Departure and arrival airports must differ")
        if p.flight_max_price is not None and not p.currency:
            raise ValueError("Flight price limits require an explicit currency")
        if p.flight_class and p.flight_class.casefold() not in CLASSES:
            raise ValueError("Supported flight classes: Economy, Premium Economy, Business, First")
        currency = p.currency or "INR"
        day = p.departure_date if leg == "outbound" else p.return_date
        params = {"engine": "google_flights", "type": 2, "departure_id": origin_airport.code,
                  "arrival_id": destination_airport.code, "outbound_date": day.isoformat(),
                  "adults": p.adults, "children": 0, "infants_in_seat": 0, "infants_on_lap": 0,
                  "currency": currency, "hl": "en", "gl": "in"}
        if p.flight_class:
            params["travel_class"] = CLASSES[p.flight_class.casefold()]
        if p.flight_sort_by is not None:
            params["sort_by"] = p.flight_sort_by
        if p.flight_max_price is not None:
            params["max_price"] = str(p.flight_max_price.to_integral_value(rounding=ROUND_CEILING))
        return parse_flights(self.http.get(params), p, origin_airport, destination_airport, day, currency, self.airport_timezones)
