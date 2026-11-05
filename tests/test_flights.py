"""Flight/date/price contracts and bounded two-leg probes; no real requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
import socket

import httpx
import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.providers.flights import AirportLocation, FlightAdapter, parse_flights, segment_time
from backend.providers.http import JsonResponse, ProviderError, SerpApiHttp
from backend.schemas import TripPreferences
from backend.services.offer_filters import eligible_transport
from scripts import check_providers

DEL = AirportLocation("DEL", "Delhi", "Asia/Kolkata")
JAI = AirportLocation("JAI", "Jaipur", "Asia/Kolkata")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Flight tests cannot connect to the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for key in list(os.environ):
        if key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)


def preferences(**changes):
    return TripPreferences(**(dict(origin="Delhi", destination="Jaipur", departure_date="2027-02-10", return_date="2027-02-13",
        adults=2, transport_mode="flight", currency="INR", flight_class="Economy", flight_sort_by=2) | changes))


def flight_body(origin="DEL", destination="JAI", day="2027-02-10"):
    return {"search_metadata": {"processed_at": "2026-11-03 17:00:00 UTC", "google_flights_url": "https://www.google.com/travel/flights"},
        "search_parameters": {"departure_id": origin, "arrival_id": destination, "outbound_date": day, "type": "2", "adults": 2, "currency": "INR"},
        "best_flights": [{"flights": [{"departure_airport": {"id": origin, "time": day + " 08:00"},
            "arrival_airport": {"id": destination, "time": day + " 09:10"}, "flight_number": "ZZ 100", "airline": "Synthetic Airlines",
            "travel_class": "Economy", "duration": 70}], "price": 4200, "type": "One way", "booking_token": "not-saved"}], "other_flights": []}


def response(body):
    return JsonResponse(body, datetime.now(timezone.utc))


def test_flight_normalization_keeps_segments_and_does_not_multiply_unknown_party_price():
    result = parse_flights(response(flight_body()), preferences(), DEL, JAI, preferences().departure_date, "INR")
    flight = result.items[0]
    assert flight.mode == "flight" and flight.origin == "Delhi" and flight.destination == "Jaipur"
    assert flight.departure.utcoffset() == timedelta(hours=5, minutes=30)
    assert flight.arrival - flight.departure == timedelta(minutes=70)
    assert flight.segments[0].flight_number == "ZZ 100" and flight.segments[0].airline == "Synthetic Airlines"
    assert flight.price.amount == 4200 and flight.price.basis == "whole_leg"
    assert not flight.price.covers_all_travelers and flight.price.taxes_included is None and not flight.price.complete
    assert not flight.source.synthetic and flight.seat_availability == "unverified"
    assert "not-saved" not in flight.model_dump_json()


def test_request_mapping_swaps_route_and_date_for_return_and_never_uses_round_trip_tokens():
    queries = []
    def handler(request):
        q = dict(request.url.params); queries.append(q)
        return httpx.Response(200, json=flight_body(q["departure_id"], q["arrival_id"], q["outbound_date"]))
    p = preferences(flight_max_price="5000.25", flight_class="Business")
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        adapter = FlightAdapter(SerpApiHttp("offline-key", http_client=client))
        adapter.search_leg(p, DEL, JAI)
        returning = adapter.search_leg(p, JAI, DEL, leg="return")
    assert len(queries) == 2
    assert queries[0]["departure_id"] == "DEL" and queries[1]["departure_id"] == "JAI"
    assert queries[1]["arrival_id"] == "DEL" and queries[1]["outbound_date"] == "2027-02-13"
    assert queries[0]["type"] == queries[1]["type"] == "2"
    assert queries[0]["sort_by"] == "2" and queries[0]["max_price"] == "5001" and queries[0]["travel_class"] == "3"
    assert all(not ({"return_date", "departure_token", "booking_token"} & q.keys()) for q in queries)
    assert returning.items[0].origin == "Jaipur" and returning.items[0].destination == "Delhi"


@pytest.mark.parametrize("field,value", [("type", 1), ("departure_id", "BOM"), ("adults", 1), ("currency", "USD"), ("outbound_date", "2027-02-11")])
def test_mismatched_flight_search_echo_is_rejected(field, value):
    body = flight_body(); body["search_parameters"][field] = value
    with pytest.raises(ProviderError, match="flight_query_response_mismatch"):
        parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")


def test_roundtrip_amount_in_a_oneway_record_is_not_accepted():
    body = flight_body(); body["best_flights"][0]["type"] = "Round trip"
    result = parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")
    assert result.items == [] and result.warnings


def test_missing_echo_and_missing_price_remain_unverified_not_free():
    body = flight_body(); body.pop("search_parameters"); body["best_flights"][0].pop("price")
    flight = parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR").items[0]
    assert flight.price.amount is None and flight.price.basis == "unverified" and not flight.price.complete


def test_duplicates_across_best_and_other_lists_are_removed():
    body = flight_body(); body["other_flights"] = deepcopy(body["best_flights"])
    assert len(parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR").items) == 1


@pytest.mark.parametrize("change", ["wrong_airport", "wrong_date", "arrival_before_departure"])
def test_inconsistent_record_is_skipped_with_warning(change):
    body = flight_body(); segment = body["best_flights"][0]["flights"][0]
    if change == "wrong_airport":
        segment["arrival_airport"]["id"] = "DEL"
    elif change == "wrong_date":
        segment["departure_airport"]["time"] = "2027-02-09 08:00"
    else:
        segment["arrival_airport"]["time"] = "2027-02-10 07:00"
    result = parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")
    assert not result.items and result.warnings


def test_connection_timezone_is_required_and_segment_sequence_is_validated():
    body = flight_body(); segments = body["best_flights"][0]["flights"]
    first = segments[0]
    first["arrival_airport"]["id"] = "BOM"
    second = deepcopy(first)
    second.update(departure_airport={"id": "BOM", "time": "2027-02-10 10:00"},
                  arrival_airport={"id": "JAI", "time": "2027-02-10 11:00"}, flight_number="ZZ 101")
    segments.append(second)
    args = (response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")
    assert not parse_flights(*args).items
    assert len(parse_flights(*args, {"BOM": "Asia/Kolkata"}).items[0].segments) == 2
    second["departure_airport"]["time"] = "2027-02-10 08:30"
    assert not parse_flights(*args, {"BOM": "Asia/Kolkata"}).items


def test_cross_timezone_flight_uses_each_airports_local_zone():
    hnd = AirportLocation("HND", "Tokyo", "Asia/Tokyo")
    lax = AirportLocation("LAX", "Los Angeles", "America/Los_Angeles")
    p = preferences(origin="Tokyo", destination="Los Angeles")
    body = flight_body("HND", "LAX"); segment = body["best_flights"][0]["flights"][0]
    segment["departure_airport"]["time"] = "2027-02-10 17:00"
    segment["arrival_airport"]["time"] = "2027-02-10 10:00"
    flight = parse_flights(response(body), p, hnd, lax, p.departure_date, "INR").items[0]
    assert flight.arrival - flight.departure == timedelta(hours=10)


@pytest.mark.parametrize("clock", ["2026-11-01 01:30", "2027-03-14 02:30"])
def test_ambiguous_or_nonexistent_dst_time_is_not_guessed(clock):
    with pytest.raises(ValueError, match="Ambiguous or nonexistent"):
        segment_time({"id": "JFK", "time": clock}, {"JFK": "America/New_York"})


def test_total_price_cap_cannot_be_claimed_met_by_unverified_quote():
    p = preferences(flight_max_price=5000)
    offers = parse_flights(response(flight_body()), p, DEL, JAI, p.departure_date, "INR").items
    assert eligible_transport(offers, p) == []
    assert eligible_transport(offers, preferences()) == offers


@pytest.mark.parametrize("sort", [0, 7, True])
def test_invalid_provider_sort_code_is_rejected_at_domain_boundary(sort):
    with pytest.raises(ValidationError):
        preferences(flight_sort_by=sort)


def test_invalid_bindings_or_class_do_not_spend_a_request():
    calls = []
    with httpx.Client(transport=httpx.MockTransport(lambda req: calls.append(req)), trust_env=False) as client:
        adapter = FlightAdapter(SerpApiHttp("offline-key", http_client=client))
        for p, a, b in [(preferences(), JAI, DEL), (preferences(flight_class="Unknown cabin"), DEL, JAI),
                         (preferences(currency=None, flight_max_price=5000), DEL, JAI)]:
            with pytest.raises(ValueError):
                adapter.search_leg(p, a, b)
    assert not calls


def test_two_leg_probe_keeps_each_legs_own_parameters_and_no_extra_requests(tmp_path):
    queries = []
    def handler(request):
        q = dict(request.url.params); queries.append(q)
        return httpx.Response(200, json=flight_body(q["departure_id"], q["arrival_id"], q["outbound_date"]))
    settings = Settings(_env_file=None, serpapi_api_key="offline-key", data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        code = check_providers.run_check(settings, preferences(), ["outbound_flights", "return_flights"],
            flight_airports=(DEL, JAI), http_factory=lambda key: SerpApiHttp(key, http_client=client))
    path = next((tmp_path / "reports").glob("*/report.json")); report = json.loads(path.read_text(encoding="utf-8"))
    assert code == 0 and len(queries) == len(report["requests"]) == 2
    assert all(len(case["requests"]) == 1 for case in report["cases"])
    assert report["cases"][0]["requests"][0]["parameters"]["departure_id"] == "DEL"
    assert report["cases"][1]["requests"][0]["parameters"]["departure_id"] == "JAI"
    assert "offline-key" not in path.read_text(encoding="utf-8")
    assert "ZZ 100" in (path.parent / "report.html").read_text(encoding="utf-8")


def test_outbound_error_skips_return_and_preserves_sanitized_report(tmp_path):
    calls = []
    def handler(request):
        calls.append(request); return httpx.Response(429, json={"error": "quota offline-key"})
    settings = Settings(_env_file=None, serpapi_api_key="offline-key", data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        code = check_providers.run_check(settings, preferences(), ["outbound_flights", "return_flights"],
            flight_airports=(DEL, JAI), http_factory=lambda key: SerpApiHttp(key, http_client=client))
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text(encoding="utf-8"))
    assert code == 2 and len(calls) == len(report["cases"]) == 1
    assert report["cases"][0]["outcome"] == "PROVIDER_ERROR"


def test_flight_preview_does_not_load_keys_or_send_requests(capsys):
    assert check_providers.main(["--category", "flights"]) == 0
    assert "zero API calls" in capsys.readouterr().out


def test_overnight_arrival_keeps_next_day_instead_of_wrapping_clock_time():
    body = flight_body(); segment = body["best_flights"][0]["flights"][0]
    segment["departure_airport"]["time"] = "2027-02-10 23:30"
    segment["arrival_airport"]["time"] = "2027-02-11 00:40"
    flight = parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR").items[0]
    assert flight.arrival.date() > flight.departure.date()
    assert flight.arrival - flight.departure == timedelta(minutes=70)


def test_unexpected_children_are_not_silently_priced_as_adult_only_scope():
    body = flight_body(); body["search_parameters"]["children"] = 1
    with pytest.raises(ProviderError, match="unexpected_child_passenger_scope"):
        parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")


def test_single_adult_quote_still_does_not_invent_included_taxes():
    body = flight_body(); body["search_parameters"]["adults"] = 1
    p = preferences(adults=1)
    flight = parse_flights(response(body), p, DEL, JAI, p.departure_date, "INR").items[0]
    assert flight.price.covers_all_travelers and not flight.price.complete


def test_skipped_flight_reports_safe_specific_reason_and_airport_code():
    body = flight_body(); body["best_flights"][0]["flights"][0]["arrival_airport"]["id"] = "XYZ"
    result = parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")
    assert result.skipped_records == [{"index": 0, "reason": "unknown_airport_timezone", "airport": "XYZ"}]
    body["best_flights"][0]["flights"][0]["arrival_airport"]["id"] = "JAI"
    body["best_flights"][0]["flights"][0]["departure_airport"]["time"] = "malformed offline-key"
    result = parse_flights(response(body), preferences(), DEL, JAI, preferences().departure_date, "INR")
    assert result.skipped_records == [{"index": 0, "reason": "invalid_segment_fields"}]
    assert "offline-key" not in str(result)
