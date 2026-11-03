"""Provider contracts use intercepted HTTP only; sockets are forbidden."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import json
import socket
from zipfile import ZipFile

import httpx
import pytest

from backend.config import Settings
from backend.providers.http import JsonResponse, ProviderError, SerpApiHttp
from backend.providers.serpapi import SerpApiAdapter, parse_hotels, parse_hours, parse_places, public_link
from backend.schemas import TripPreferences
from backend.services.offer_filters import eligible_hotels
from scripts import check_providers


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Provider tests cannot use real network sockets")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for key in list(__import__("os").environ):
        if key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)


def preferences(**changes):
    values = dict(origin="Delhi", destination="Jaipur", departure_date="2027-02-10", return_date="2027-02-13",
                  adults=2, hotel_class=3, nightly_min="2000", nightly_max="4000", guest_rating_min=4.2, currency="INR")
    return TripPreferences(**(values | changes))


def hotel_body():
    # Representative field names from the earlier probe, with invented test data.
    return {"search_metadata": {"processed_at": "2026-11-03 16:00:00 UTC", "google_hotels_url": "https://www.google.com/travel/hotels"},
            "search_parameters": {"check_in_date": "2027-02-10", "check_out_date": "2027-02-13", "adults": 2, "currency": "INR"},
            "properties": [{"type": "hotel", "property_token": "offline-hotel-1", "name": "Synthetic Test Hotel", "extracted_hotel_class": 3,
                            "overall_rating": 4.3, "rate_per_night": {"extracted_lowest": 3000},
                            "total_rate": {"extracted_lowest": 9000}, "link": "https://example.com/hotel"}]}


def maps_body():
    return {"search_metadata": {"processed_at": "2026-11-03 16:00:00 UTC"},
            "local_results": [{"place_id": "offline-place-1", "title": "Synthetic Test Museum", "rating": 4.5,
                "address": "Jaipur", "gps_coordinates": {"latitude": 26.9, "longitude": 75.8},
                "operating_hours": {"monday": "9\u202fAM–6:30\u202fPM", "tuesday": "Closed"}, "website": "https://example.com/museum"}]}


def response(body):
    return JsonResponse(body, datetime(2026, 11, 3, 17, tzinfo=timezone.utc))


def test_hotel_normalization_preserves_real_evidence_and_unknown_occupancy():
    result = parse_hotels(response(hotel_body()), preferences(), "INR")
    hotel = result.items[0]
    assert hotel.price.amount == Decimal("9000") and hotel.nightly_price == Decimal("3000")
    assert hotel.price.basis == "whole_stay" and hotel.price.taxes_included is None
    assert not hotel.price.covers_all_travelers and not hotel.price.complete and hotel.room_type is None
    assert hotel.hotel_class == 3 and hotel.guest_rating == 4.3
    assert hotel.source.provider_data_at.hour == 16 and hotel.source.fetched_at.hour == 17
    assert hotel.source.synthetic is False and hotel.price.notes
    assert [h.id for h in eligible_hotels(result.items, preferences())] == [hotel.id]


def test_only_explicit_after_tax_field_confirms_taxes_without_confirming_occupancy():
    body = hotel_body()
    body["properties"][0]["total_rate"] = {"extracted_lowest": 9000, "extracted_before_taxes_fees": 9000, "extracted_after_taxes_fees": 10080}
    hotel = parse_hotels(response(body), preferences(), "INR").items[0]
    assert hotel.price.amount == Decimal("10080") and hotel.price.taxes_included is True
    assert not hotel.price.complete


def test_absent_stay_total_is_unknown_and_never_multiplied_from_average():
    body = hotel_body(); body["properties"][0].pop("total_rate")
    hotel = parse_hotels(response(body), preferences(), "INR").items[0]
    assert hotel.price.amount is None and hotel.nightly_price == 3000


@pytest.mark.parametrize("field,value", [("adults", 1), ("currency", "USD"), ("check_out_date", "2027-02-14")])
def test_mismatched_search_scope_is_rejected(field, value):
    body = hotel_body(); body["search_parameters"][field] = value
    with pytest.raises(ProviderError, match="hotel_query_response_mismatch"):
        parse_hotels(response(body), preferences(), "INR")


def test_missing_echo_stays_unverified_and_bad_records_do_not_discard_good_records():
    body = hotel_body(); body.pop("search_parameters")
    good = body["properties"][0]
    body["properties"] += [deepcopy(good), {"name": "", "type": "hotel"}, {"type": "vacation rental", "name": "Excluded rental"}]
    result = parse_hotels(response(body), preferences(), "INR")
    assert len(result.items) == 1 and result.items[0].price.basis == "unverified" and result.warnings


@pytest.mark.parametrize("bad", [-1, "NaN", True, "₹9,000"])
def test_non_numeric_or_invalid_price_never_becomes_zero(bad):
    body = hotel_body(); body["properties"][0]["total_rate"] = {"extracted_lowest": bad}
    assert parse_hotels(response(body), preferences(), "INR").items[0].price.amount is None


def test_provider_bucket_is_not_stricter_than_exact_local_rating_and_price_filters():
    captured = []
    def handler(request):
        captured.append(dict(request.url.params))
        return httpx.Response(200, json=hotel_body())
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        adapter = SerpApiAdapter(SerpApiHttp("offline-key", http_client=client))
        result = adapter.hotels(preferences(nightly_min="2000.50", nightly_max="3999.50", guest_rating_min=4.4, hotel_class_rule="at_least"))
    query = captured[0]
    assert query["rating"] == "8" and query["hotel_class"] == "3,4,5"
    assert query["min_price"] == "2000" and query["max_price"] == "4000"
    assert query["adults"] == "2" and query["children"] == "0" and query["currency"] == "INR"
    assert eligible_hotels(result.items, preferences(guest_rating_min=4.4)) == []


def test_exact_stars_and_one_star_do_not_silently_become_at_least_two():
    queries = []
    def handler(request):
        queries.append(dict(request.url.params)); return httpx.Response(200, json=hotel_body())
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        adapter = SerpApiAdapter(SerpApiHttp("offline-key", http_client=client))
        adapter.hotels(preferences()); adapter.hotels(preferences(hotel_class=1))
    assert queries[0]["hotel_class"] == "3" and "hotel_class" not in queries[1]


def test_maps_search_and_detail_hours_normalize_and_exact_ids_deduplicate():
    body = maps_body(); body["local_results"] *= 2
    result = parse_places(response(body))
    assert len(result.items) == 1
    place = result.items[0]
    assert place.weekly_hours == {0: [("09:00", "18:30")], 1: []}
    assert place.latitude == 26.9 and place.rating == 4.5 and not place.source.synthetic
    detail = {"place_results": {"title": "Detail place", "hours": [{"friday": "Open 24 hours"}]}}
    assert parse_places(response(detail)).items[0].weekly_hours == {4: [("00:00", "23:59")]}


def test_unknown_or_ambiguous_hours_are_not_guessed_and_bad_gps_is_skipped():
    assert parse_hours({"monday": "Open now", "tuesday": "9–6 PM", 1: "Closed"}) == {}
    assert parse_hours({"wednesday": "09:00–12:00, 14:00–17:00"}) == {2: [("09:00", "12:00"), ("14:00", "17:00")]}
    body = maps_body(); body["local_results"].append({"title": "Bad GPS", "gps_coordinates": []})
    # A nonempty malformed coordinate value is not interpreted as a mapping.
    body["local_results"][-1]["gps_coordinates"] = [1]
    result = parse_places(response(body)); assert len(result.items) == 1 and result.warnings


@pytest.mark.parametrize("body,parser", [({"properties": {}}, "hotels"), ({"search_parameters": []}, "hotels"), ({"local_results": {}}, "places")])
def test_malformed_top_level_collections_are_not_accepted_as_offers(body, parser):
    with pytest.raises(ProviderError):
        parse_hotels(response(body), preferences(), "INR") if parser == "hotels" else parse_places(response(body))


@pytest.mark.parametrize("status,body", [(401, {"error": "bad offline-key"}), (429, {"error": "quota offline-key"}), (200, {"error": "provider unavailable"})])
def test_auth_quota_and_body_errors_make_one_request_and_redact_key(status, body):
    requests = []
    def handler(request):
        requests.append(request); return httpx.Response(status, json=body)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        http = SerpApiHttp("offline-key", http_client=client)
        with pytest.raises(ProviderError) as caught:
            http.get({"engine": "google_hotels", "q": "Jaipur"})
    assert len(requests) == 1 and requests[0].url.host == "serpapi.com"
    assert "offline-key" not in json.dumps(http.audit) + json.dumps(caught.value.public())
    assert http.audit[0]["http_status"] == status and "error" in http.audit[0]


def test_timeout_never_exposes_url_or_retries():
    calls = []
    def handler(request):
        calls.append(request); raise httpx.ReadTimeout("URL " + str(request.url), request=request)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        http = SerpApiHttp("offline-key", http_client=client)
        with pytest.raises(ProviderError) as caught:
            http.get({"engine": "google_maps", "q": "Jaipur"})
    assert len(calls) == 1 and caught.value.code == "ReadTimeout"
    assert "offline-key" not in str(caught.value) + json.dumps(http.audit)
    assert http.audit[0]["error"]["code"] == "ReadTimeout"


@pytest.mark.parametrize("status,content,code", [(302, b"redirect", "non_json_response"), (200, b"[]", "invalid_response_shape"),
                                               (200, b"x" * 2_000_001, "response_too_large")])
def test_redirect_non_object_and_large_responses_do_not_normalize(status, content, code):
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, content=content)), trust_env=False) as client:
        with pytest.raises(ProviderError) as caught:
            SerpApiHttp("offline-key", http_client=client).get({"engine": "google_hotels"})
    assert caught.value.code == code


def test_public_links_reject_script_userinfo_and_strip_credentials():
    assert public_link("javascript:alert(1)") is None
    assert public_link("https://user:password@example.com") is None
    assert public_link("https://example.com?a=1&api_key=private") == "https://example.com?a=1"


def test_preview_requires_no_key_and_has_zero_requests(capsys):
    assert check_providers.main([]) == 0
    assert "zero API calls" in capsys.readouterr().out


def test_report_has_corresponding_inputs_escaped_html_and_only_two_calls(tmp_path):
    requests = []
    def handler(request):
        requests.append(request)
        body = hotel_body() if request.url.params["engine"] == "google_hotels" else maps_body()
        if "local_results" in body:
            body["local_results"][0]["title"] = "<script>alert('offline-key')</script>"
        return httpx.Response(200, json=body)
    settings = Settings(_env_file=None, serpapi_api_key="offline-key", data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        assert check_providers.run_check(settings, preferences(), ["hotels", "places"],
            http_factory=lambda key: SerpApiHttp(key, http_client=client)) == 0
    folder = next((tmp_path / "reports").iterdir())
    text = (folder / "report.json").read_text(encoding="utf-8"); report = json.loads(text)
    assert len(requests) == len(report["requests"]) == 2
    assert report["cases"][0]["requests"][0]["parameters"]["check_in_date"] == "2027-02-10"
    assert "offline-key" not in text and "<script>" not in (folder / "report.html").read_text(encoding="utf-8")
    assert "&lt;script&gt;" in (folder / "report.html").read_text(encoding="utf-8")
    with ZipFile(folder / "share_results.zip") as archive:
        assert set(archive.namelist()) == {"report.json", "report.html"} and archive.testzip() is None


def test_failed_first_request_stops_second_and_saves_audit(tmp_path):
    calls = []
    def handler(request):
        calls.append(request); return httpx.Response(429, json={"error": "quota offline-key"})
    settings = Settings(_env_file=None, serpapi_api_key="offline-key", data_dir=tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        result = check_providers.run_check(settings, preferences(), ["hotels", "places"],
            http_factory=lambda key: SerpApiHttp(key, http_client=client))
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text())
    assert result == 2 and len(calls) == len(report["requests"]) == len(report["cases"]) == 1
    assert report["cases"][0]["outcome"] == "PROVIDER_ERROR"
