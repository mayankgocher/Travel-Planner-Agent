"""Assumed pricing is deterministic, explicit and separate from verified costs."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import httpx
import pytest

from backend.config import Settings
from backend.providers.http import ProviderError
from backend.providers.rail_http import RailRadarHttp
from backend.providers.railradar import CLASSES, RailRadarAdapter, StationBinding
from backend.schemas import PriceQuote, Source, TrainTimetable, TransportOffer, TripPreferences
from backend.services.costs import summarize_costs
from backend.services.demo_fares import CLASS_RANGES, RULE_VERSION, apply_demo_fare
from scripts import check_rail


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Demo pricing tests cannot use real network sockets")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name)


def fixture_offer(adults=2, number="13240", cabin="3A", *, synthetic=True):
    # Invented schedule/class evidence: not a claim about the real train 13240.
    source = Source(provider="offline_test", fetched_at=datetime(2026, 11, 3, tzinfo=timezone.utc), synthetic=synthetic)
    offer = TransportOffer(id="test:" + number, mode="train", origin="Delhi", destination="Jaipur",
        departure=datetime(2027, 2, 10, 6, tzinfo=timezone.utc), arrival=datetime(2027, 2, 10, 10, tzinfo=timezone.utc),
        adults=adults, train_number=number, train_name="Invented test train", departure_station="NDLS", arrival_station="JP",
        price=PriceQuote(currency="INR"), source=source)
    timetable = TrainTimetable(train_number=number, train_name="Invented test train", operated_classes=[cabin],
        is_prs_bookable=True, stop_codes=["NDLS", "JP"], source=source)
    return offer, timetable


def priced():
    offer, detail = fixture_offer()
    return apply_demo_fare(offer, detail, "3A")


def test_unseen_combination_known_vector_and_party_total():
    offer, detail = fixture_offer()
    value = apply_demo_fare(offer, detail, "3A")
    assert value.price.per_adult_amount == 897 and value.price.amount == 1794
    assert value.price.pricing_mode == "demo" and value.price.demo_rule_version == RULE_VERSION
    assert not value.price.complete and value.seat_availability == "unverified"
    assert offer.price.amount is None and value.source == offer.source  # No mutation / fake provider price source.


def test_repeatability_survives_restarts_and_python_hash_seed_changes():
    script = "import runpy; x=runpy.run_path('tests/test_demo_fares.py'); print(x['priced']().price.per_adult_amount)"
    outputs = [subprocess.check_output([sys.executable, "-c", script], env=os.environ | {"PYTHONHASHSEED": seed}, text=True).strip()
               for seed in ("1", "234")]
    assert outputs == ["897", "897"]


def test_date_and_adult_count_do_not_change_per_adult_hash():
    first = priced()
    offer, detail = fixture_offer(adults=3)
    offer = TransportOffer.model_validate(offer.model_dump() | {
        "departure": offer.departure + timedelta(days=1), "arrival": offer.arrival + timedelta(days=1)})
    second = apply_demo_fare(offer, detail, "3A")
    assert first.price.per_adult_amount == second.price.per_adult_amount
    assert second.price.amount == Decimal("2691")


@pytest.mark.parametrize("cabin", sorted(CLASSES))
def test_supported_classes_use_their_documented_demo_ranges(cabin):
    for number in ("13240", "54321", "99999"):
        offer, detail = fixture_offer(number=number, cabin=cabin)
        value = apply_demo_fare(offer, detail, cabin)
        low, high = CLASS_RANGES[cabin]
        assert low <= value.price.per_adult_amount <= high
    assert set(CLASS_RANGES) == CLASSES


@pytest.mark.parametrize("fault", ["number", "class", "reversed_route", "missing_station", "not_bookable", "mixed_evidence"])
def test_missing_or_incompatible_train_evidence_does_not_receive_mock_price(fault):
    offer, detail = fixture_offer()
    if fault == "number": detail.train_number = "54321"
    elif fault == "class": detail.operated_classes = ["CC"]
    elif fault == "reversed_route": detail.stop_codes = ["JP", "NDLS"]
    elif fault == "missing_station": detail.stop_codes = ["NDLS", "AGC"]
    elif fault == "not_bookable": detail.is_prs_bookable = False
    else: detail.source = detail.source.model_copy(update={"synthetic": False})
    with pytest.raises(ValueError): apply_demo_fare(offer, detail, "3A")


def test_real_schedule_metadata_stays_real_while_only_price_is_assumed():
    offer, detail = fixture_offer(synthetic=False)
    value = apply_demo_fare(offer, detail, "3A")
    assert not value.source.synthetic and value.price.pricing_mode == "demo"
    assert value.source.fetched_at == offer.source.fetched_at


def test_assumed_prices_never_create_verified_affordability_but_allow_illustrative_comparison():
    demo = priced().price
    # Complete synthetic comparator quotes isolate arithmetic from unrelated unknown taxes/occupancy.
    quotes = {"outbound_transport": demo,
        "return_transport": PriceQuote(amount="1000", currency="INR", basis="whole_leg", covers_all_travelers=True, taxes_included=True),
        "hotel_stay": PriceQuote(amount="5000", currency="INR", basis="whole_stay", covers_all_travelers=True, taxes_included=True)}
    result = summarize_costs(quotes, "INR", Decimal("7794"))
    assert result.complete_subtotal is None and result.budget_status == "unknown"
    assert result.known_subtotal == 6000 and result.assumed_components == ["outbound_transport"]
    assert result.illustrative_subtotal == 7794 and result.illustrative_budget_status == "within_assumed_budget"
    assert summarize_costs(quotes, "INR", Decimal("7793.99")).illustrative_budget_status == "over_assumed_budget"
    quotes["hotel_stay"].taxes_included = None
    assert summarize_costs(quotes, "INR").illustrative_budget_status == "unknown"
    quotes.pop("return_transport")
    assert summarize_costs(quotes, "INR").illustrative_subtotal is None


def test_mode_defaults_and_invalid_config(monkeypatch):
    monkeypatch.delenv("TRAIN_FARE_MODE", raising=False)
    assert Settings(_env_file=None).train_fare_mode == "mock"
    with pytest.raises(ValueError): Settings(_env_file=None, train_fare_mode="random")
    # Even accidental tax flags cannot make demo amounts verified.
    quote = priced().price; quote.taxes_included = True
    assert not quote.complete


def rail_handler(calls, *, denied_fare=False):
    def handle(request):
        calls.append(request)
        path = request.url.path
        if path.endswith("/fare"):
            if denied_fare:
                return httpx.Response(403, json={"success": False, "error": {"code": "PLAN_UPGRADE_REQUIRED"}})
            raise AssertionError("Mock mode must never call the paid fare endpoint")
        if "/between/" in path:
            data = {"from": {"code": "NDLS"}, "to": {"code": "JP"}, "trains": [
                {"train": {"number": n, "name": "Synthetic test " + n}, "from": {"code": "NDLS", "day": 1, "departure": "06:00"},
                 "to": {"code": "JP", "day": 1, "arrival": "10:00"}, "duration": 240} for n in ("13240", "54321")]}
        else:
            n = path.rsplit("/", 1)[1]
            data = {"train": {"number": n, "name": "Synthetic test " + n, "availableClasses": ["3A"], "isPrsBookable": True},
                    "route": [{"station": {"code": "NDLS"}}, {"station": {"code": "JP"}}]}
        return httpx.Response(200, json={"success": True, "data": data})
    return handle


def trip():
    return TripPreferences(origin="Delhi", destination="Jaipur", departure_date="2027-02-10", return_date="2027-02-13", adults=2, train_class="3A", currency="INR")


def test_mock_mode_prices_both_confirmed_shortlist_matches_without_fare_requests():
    calls = []
    with httpx.Client(transport=httpx.MockTransport(rail_handler(calls)), trust_env=False) as client:
        adapter = RailRadarAdapter(RailRadarHttp("offline-key", max_requests=3, http_client=client), fare_mode="mock")
        result = adapter.search_leg(trip(), StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur"))
    assert len(calls) == 3 and len(adapter.priced_offer_ids) == 2
    assert all(o.price.pricing_mode == "demo" for o in result.items)
    assert all(not o.source.synthetic for o in result.items)  # MockTransport simulates normalized live schedule metadata.


def test_live_mode_keeps_permission_error_and_confirmed_class_without_mock_fallback():
    calls = []
    with httpx.Client(transport=httpx.MockTransport(rail_handler(calls, denied_fare=True)), trust_env=False) as client:
        adapter = RailRadarAdapter(RailRadarHttp("offline-key", max_requests=3, http_client=client), fare_mode="live")
        with pytest.raises(ProviderError): adapter.search_leg(trip(), StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur"))
    confirmed = adapter.last_result.items[0]
    assert confirmed.travel_class == "3A" and confirmed.price.amount is None and confirmed.price.pricing_mode == "live"
    assert not adapter.priced_offer_ids and len(calls) == 3


def test_replay_preserves_input_and_timestamps_without_loading_keys_or_network(tmp_path, monkeypatch):
    offer, detail = fixture_offer()
    original = {"preferences": trip().model_dump(mode="json"), "trains": [offer.model_dump(mode="json")],
                "timetables": [detail.model_dump(mode="json")], "requests": [{"old": "request"}]}
    source = tmp_path / "original.json"; source.write_text(json.dumps(original))
    before = source.read_bytes()
    def forbidden(*a, **k): raise AssertionError("Replay cannot initialize settings/HTTP")
    monkeypatch.setattr(check_rail, "Settings", forbidden)
    monkeypatch.setattr(check_rail, "RailRadarHttp", forbidden)
    assert check_rail.run_replay(source, output_root=tmp_path / "output") == 0
    report = json.loads(next((tmp_path / "output" / "reports").glob("*/report.json")).read_text(encoding="utf-8"))
    assert source.read_bytes() == before and not report["requests"] and report["maximum_requests"] == 0
    assert report["original_request_count"] == 1 and report["saved_report_replay"]
    assert report["trains"][0]["source"]["fetched_at"] == original["trains"][0]["source"]["fetched_at"]
    assert report["trains"][0]["price"]["pricing_mode"] == "demo"
    html = next((tmp_path / "output" / "reports").glob("*/report.html")).read_text(encoding="utf-8")
    assert "ASSUMED DEMO FARE" in html and "zero API requests" in html
