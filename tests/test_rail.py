"""Rail contract tests use invented payloads over intercepted HTTP, never real keys."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
import socket
from zipfile import ZipFile

import httpx
import pytest

from backend.config import Settings
from backend.providers.http import JsonResponse, ProviderError
from backend.providers.rail_http import RailRadarHttp
from backend.providers.railradar import RailRadarAdapter, StationBinding, apply_fare, parse_between, parse_stations, parse_timetable
from backend.schemas import TripPreferences
from scripts import check_rail

NDLS, JP = StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Rail tests must not connect to a network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for key in list(os.environ):
        if key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)


def preferences(**changes):
    return TripPreferences(**(dict(origin="Delhi", destination="Jaipur", departure_date="2027-02-10", return_date="2027-02-13",
        adults=2, train_class="CC", transport_mode="train", currency="INR") | changes))


def envelope(data):
    return {"success": True, "data": data, "meta": {"timestamp": "2026-11-03T22:00:00+05:30", "source": "offline-test"}}


def response(body):
    return JsonResponse(body, datetime.now(timezone.utc))


def between_body(origin="NDLS", destination="JP"):
    rows = []
    for number, departure, arrival, duration in [("12015", "06:00", "10:00", 240), ("12966", "07:00", "14:00", 420), ("12345", "08:00", "16:00", 480)]:
        rows.append({"train": {"number": number, "name": "Synthetic Train " + number},
            "from": {"code": origin, "departure": departure, "day": 2},
            "to": {"code": destination, "arrival": arrival, "day": 2}, "duration": duration})
    return envelope({"from": {"code": origin}, "to": {"code": destination}, "trains": rows, "count": len(rows)})


def timetable_body(number, *, classes=None, origin="NDLS", destination="JP"):
    return envelope({"train": {"number": number, "name": "Synthetic Train " + number,
        "availableClasses": ["CC", "EC"] if classes is None else classes, "isPrsBookable": True},
        "route": [{"station": {"code": origin}}, {"station": {"code": destination}}]})


def fare_body(number="12015"):
    return envelope({"trainNumber": number, "breakdown": {"baseFare": 500, "reservationCharge": 40,
        "goodsServiceTax": 25, "otherCharge": 0, "totalFare": 565}})


def handler_factory(calls, *, incompatible_first=False, fare_status=200):
    def handler(request):
        calls.append(request)
        path, q = request.url.path, request.url.params
        assert request.url.host == "api.railradar.in" and request.headers["Authorization"] == "Bearer offline-rail-key"
        assert "apiKey" not in q and "api_key" not in q
        if path == "/v1/lookup/search/stations":
            body = envelope([{"code": q["q"], "name": "Synthetic " + q["q"], "city": None, "isActive": True, "lat": 26.9, "lng": 75.8}])
        elif "/between/" in path:
            origin, destination = path.split("/")[-2:]
            body = between_body(origin, destination)
        elif path.endswith("/fare"):
            if fare_status != 200:
                return httpx.Response(fare_status, json={"success": False, "error": {"code": "NOT_FOUND", "message": "unavailable offline-rail-key"}})
            body = fare_body(path.split("/")[-2])
        else:
            number = path.split("/")[-1]
            classes = ["3A"] if incompatible_first and number == "12015" else ["CC", "EC"]
            body = timetable_body(number, classes=classes)
        return httpx.Response(200, json=body, headers={"X-RateLimit-Remaining-Month": str(99 - len(calls)), "X-RateLimit-Remaining-Min": str(10 - len(calls))})
    return handler


def test_station_lookup_keeps_nullable_city_and_skips_inactive_duplicates():
    body = envelope([{"code": "ndls", "name": "Synthetic New Delhi", "city": None, "isActive": True},
                     {"code": "NDLS", "name": "Duplicate"}, {"code": "OLD", "name": "Inactive", "isActive": False}, {"code": "bad/code", "name": "Invalid"}])
    result = parse_stations(response(body))
    assert [s.code for s in result.items] == ["NDLS"] and result.items[0].city is None
    assert result.warnings and not result.items[0].source.synthetic


def test_boarding_date_does_not_shift_by_the_trains_origin_day():
    p = preferences(); offers = parse_between(response(between_body()), p, NDLS, JP, p.departure_date).items
    assert offers[0].departure.date() == p.departure_date  # from.day=2 is not +1 day here.
    assert offers[0].departure.utcoffset() == timedelta(hours=5, minutes=30)
    assert offers[0].arrival - offers[0].departure == timedelta(hours=4)
    assert offers[0].price.amount is None and offers[0].seat_availability == "unverified"


def test_overnight_train_uses_relative_day_difference():
    body = between_body(); body["data"]["trains"] = body["data"]["trains"][:1]
    row = body["data"]["trains"][0]
    row["from"].update(departure="23:30", day=3); row["to"].update(arrival="05:00", day=4); row["duration"] = 330
    p = preferences(); offer = parse_between(response(body), p, NDLS, JP, p.departure_date).items[0]
    assert offer.departure.date() == p.departure_date and offer.arrival.date() == p.departure_date + timedelta(days=1)
    assert offer.arrival - offer.departure == timedelta(minutes=330)


@pytest.mark.parametrize("kind", ["negative_day", "duration_mismatch", "station_mismatch", "bad_number"])
def test_inconsistent_schedule_record_is_skipped_without_losing_other_services(kind):
    body = between_body(); row = body["data"]["trains"][0]
    if kind == "negative_day": row["to"]["day"] = 1
    elif kind == "duration_mismatch": row["duration"] = 12
    elif kind == "station_mismatch": row["from"]["code"] = "DLI"
    else: row["train"]["number"] = "7-SPL 1"
    p = preferences(); result = parse_between(response(body), p, NDLS, JP, p.departure_date)
    assert len(result.items) == 2 and any("Skipped" in w for w in result.warnings)


def test_empty_direct_services_is_not_a_free_journey_or_provider_error():
    body = between_body(); body["data"]["trains"] = []
    p = preferences(); assert parse_between(response(body), p, NDLS, JP, p.departure_date).items == []


@pytest.mark.parametrize("body", [envelope([]), envelope({"trains": []}), envelope({"from": {"code": "DLI"}, "to": {"code": "JP"}, "trains": []})])
def test_bad_or_wrong_route_envelope_is_rejected(body):
    p = preferences()
    with pytest.raises(ProviderError):
        parse_between(response(body), p, NDLS, JP, p.departure_date)


def test_timetable_classes_mean_coach_types_not_available_seats():
    detail = parse_timetable(response(timetable_body("12015")), "12015")
    assert detail.operated_classes == ["CC", "EC"] and detail.stop_codes == ["NDLS", "JP"]
    with pytest.raises(ProviderError, match="timetable_train_mismatch"):
        parse_timetable(response(timetable_body("12966")), "12015")


def test_fare_does_not_multiply_by_adults_or_invent_verified_total():
    p = preferences(); offer = parse_between(response(between_body()), p, NDLS, JP, p.departure_date).items[0]
    priced, components = apply_fare(response(fare_body()), offer, "CC")
    assert priced.price.amount == 565 and priced.price.basis == "unverified" and priced.travel_class == "CC"
    assert not priced.price.complete and not priced.price.covers_all_travelers and priced.price.taxes_included is None
    assert components["goodsServiceTax"] == "25" and priced.seat_availability == "unverified"
    assert offer.price.amount is None  # Normalization does not mutate an earlier offer.


@pytest.mark.parametrize("kind", ["missing_total", "negative_total", "nan_total"])
def test_missing_or_invalid_total_remains_unknown(kind):
    body = fare_body()
    if kind == "missing_total": body["data"]["breakdown"].pop("totalFare")
    else: body["data"]["breakdown"]["totalFare"] = -1 if kind == "negative_total" else "NaN"
    p = preferences(); offer = parse_between(response(between_body()), p, NDLS, JP, p.departure_date).items[0]
    assert apply_fare(response(body), offer, "CC")[0].price.amount is None


def test_mismatched_train_or_explicit_fare_scope_is_rejected():
    p = preferences(); offer = parse_between(response(between_body()), p, NDLS, JP, p.departure_date).items[0]
    for body in (fare_body("12966"), envelope(fare_body()["data"] | {"classCode": "3A"})):
        with pytest.raises(ProviderError):
            apply_fare(response(body), offer, "CC")


def test_ordered_small_shortlist_makes_one_fare_call_and_at_most_two_details():
    calls = []
    with httpx.Client(transport=httpx.MockTransport(handler_factory(calls, incompatible_first=True)), trust_env=False) as client:
        http = RailRadarHttp("offline-rail-key", max_requests=4, http_client=client)
        adapter = RailRadarAdapter(http); result = adapter.search_leg(preferences(), NDLS, JP)
    assert [r.url.path for r in calls] == ["/v1/trains/between/NDLS/JP", "/v1/trains/12015", "/v1/trains/12966", "/v1/trains/12966/fare"]
    assert len(adapter.priced_offer_ids) == 1 and sum(o.price.amount is not None for o in result.items) == 1
    assert calls[-1].url.params["classCode"] == "CC" and calls[-1].url.params["quotaCode"] == "GN"
    assert calls[-1].url.params["journeyDate"] == "2027-02-10" and "adults" not in calls[-1].url.params


def test_return_leg_reverses_station_pair_and_uses_return_boarding_date():
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=between_body("JP", "NDLS") if "/between/" in request.url.path else
                              timetable_body("12015", origin="JP", destination="NDLS") if not request.url.path.endswith("/fare") else fare_body())
    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        adapter = RailRadarAdapter(RailRadarHttp("offline-rail-key", max_requests=3, http_client=client))
        result = adapter.search_leg(preferences(), JP, NDLS, leg="return")
    assert calls[0].url.path.endswith("JP/NDLS") and calls[0].url.params["date"] == "2027-02-13"
    assert calls[-1].url.params["source"] == "JP" and calls[-1].url.params["destination"] == "NDLS"
    assert result.items[0].origin == "Jaipur" and result.items[0].departure.date() == preferences().return_date


def test_unsupported_class_or_missing_ordered_stops_never_requests_fare():
    for fault in ("classes", "stops"):
        calls = []
        def handle(request):
            calls.append(request)
            if "/between/" in request.url.path: body = between_body()
            else:
                number = request.url.path.split("/")[-1]
                body = timetable_body(number, classes=["3A"] if fault == "classes" else ["CC"], origin="JP", destination="NDLS")
            return httpx.Response(200, json=body)
        with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
            adapter = RailRadarAdapter(RailRadarHttp("offline-rail-key", max_requests=3, http_client=client))
            adapter.search_leg(preferences(), NDLS, JP)
        assert len(calls) == 3 and not any(r.url.path.endswith("/fare") for r in calls) and not adapter.priced_offer_ids


@pytest.mark.parametrize("path", ["https://other.example.com", "/v1/trains/12015/seats", "/v1/pnr/123", "/v1/../trains/12015"])
def test_unplanned_or_unsafe_endpoint_is_blocked_before_a_request(path):
    with RailRadarHttp("offline-rail-key", max_requests=1) as http:
        with pytest.raises(ValueError): http.get(path, {})
        assert not http.audit


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_provider_failures_do_not_retry_or_expose_key(status):
    calls = []
    def handle(request):
        calls.append(request); return httpx.Response(status, json={"success": False, "error": {"code": "UNAVAILABLE", "message": "bad offline-rail-key"}})
    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        http = RailRadarHttp("offline-rail-key", max_requests=6, http_client=client)
        with pytest.raises(ProviderError) as caught: http.get("/v1/lookup/search/stations", {"q": "NDLS"})
    assert len(calls) == 1 and "offline-rail-key" not in json.dumps(http.audit) + json.dumps(caught.value.public())


def test_timeout_is_safe_and_recorded_without_url_or_authentication():
    def handle(request): raise httpx.ReadTimeout("URL " + str(request.url) + " offline-rail-key", request=request)
    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        http = RailRadarHttp("offline-rail-key", max_requests=1, http_client=client)
        with pytest.raises(ProviderError, match="ReadTimeout"): http.get("/v1/lookup/search/stations", {"q": "NDLS"})
    assert len(http.audit) == 1 and "offline-rail-key" not in json.dumps(http.audit)


def test_local_budget_and_returned_quota_headers_stop_before_another_request():
    for header, budget in [({}, 1), ({"X-RateLimit-Remaining-Month": "0"}, 6), ({"X-RateLimit-Remaining-Min": "0"}, 6)]:
        calls = []
        def handle(request):
            calls.append(request); return httpx.Response(200, json=envelope([]), headers=header)
        with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
            http = RailRadarHttp("offline-rail-key", max_requests=budget, http_client=client)
            http.get("/v1/lookup/search/stations", {"q": "NDLS"})
            with pytest.raises(ProviderError): http.get("/v1/lookup/search/stations", {"q": "JP"})
        assert len(calls) == len(http.audit) == 1


def test_full_rail_probe_writes_input_pairs_partial_prices_and_share_archive(tmp_path):
    calls = []
    settings = Settings(_env_file=None, railradar_api_key="offline-rail-key", data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler_factory(calls)), trust_env=False) as client:
        code = check_rail.run_check(settings, preferences(),
            http_factory=lambda key, **kwargs: RailRadarHttp(key, http_client=client, **kwargs))
    folder = next((tmp_path / "reports").iterdir()); text = (folder / "report.json").read_text(); report = json.loads(text)
    assert code == 0 and report["outcome"] == "PASS_CHECKS" and len(calls) == len(report["requests"]) == 5
    assert report["requests"][0]["parameters"]["q"] == "NDLS" and report["requests"][-1]["parameters"]["classCode"] == "CC"
    assert len(report["priced_offer_ids"]) == 1 and "offline-rail-key" not in text
    assert report["trains"][1]["price"]["amount"] is None
    with ZipFile(folder / "share_results.zip") as z:
        assert set(z.namelist()) == {"report.html", "report.json"} and z.testzip() is None


def test_fare_404_preserves_schedules_and_does_not_try_another_fare(tmp_path):
    calls = []
    settings = Settings(_env_file=None, railradar_api_key="offline-rail-key", data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler_factory(calls, fare_status=404)), trust_env=False) as client:
        code = check_rail.run_check(settings, preferences(),
            http_factory=lambda key, **kwargs: RailRadarHttp(key, http_client=client, **kwargs))
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text())
    assert code == 2 and report["outcome"] == "PROVIDER_ERROR" and len(calls) == 5
    assert len(report["trains"]) == 3 and all(t["price"]["amount"] is None for t in report["trains"])
    assert len(report["timetables"]) == 1 and report["error"]["http_status"] == 404


def test_missing_local_key_needs_no_requests_and_preview_loads_no_key(tmp_path, capsys):
    assert check_rail.main([]) == 0 and "zero API calls" in capsys.readouterr().out
    settings = Settings(_env_file=None, railradar_api_key="", data_dir=tmp_path)
    assert check_rail.run_check(settings, preferences()) == 2
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text())
    assert not report["requests"] and "RAILRADAR_API_KEY" in report["configuration_hint"]


@pytest.mark.parametrize("status", [200, 302])
def test_html_or_redirect_response_is_not_followed_or_saved_as_a_fare(status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, text="<html>offline-rail-key</html>", headers={"Location": "https://other.example.com"})
    with httpx.Client(transport=httpx.MockTransport(handle), trust_env=False) as client:
        http = RailRadarHttp("offline-rail-key", max_requests=6, http_client=client)
        with pytest.raises(ProviderError, match="non_json_response"):
            http.get("/v1/trains/12015/fare", {"source": "NDLS", "destination": "JP"})
    assert len(calls) == 1 and "offline-rail-key" not in json.dumps(http.audit)
