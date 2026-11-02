"""Offline correctness checks: no keys, mocks of live services, or paid calls."""
from datetime import datetime, timezone
from decimal import Decimal
import socket

import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.schemas import PriceQuote, Selection, Source, TripPreferences
from backend.services.costs import summarize_costs
from backend.services.replanning import DEPENDENCIES, affected_components, enforce_selection_locks


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline domain tests must not access the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def quote(amount, basis="whole_leg", currency="INR", **kwargs):
    return PriceQuote(amount=amount, basis=basis, currency=currency,
                      covers_all_travelers=True, taxes_included=True, **kwargs)


def complete_quotes():
    return {"outbound_transport": quote("1000.10"), "return_transport": quote("1000.20"),
            "hotel_stay": quote("4000", basis="whole_stay")}


def test_clarification_keeps_missing_preferences_unknown():
    p = TripPreferences(origin="Delhi", destination="Jaipur", adults=2)
    assert p.missing_required() == ["departure_date", "return_date"]
    assert p.budget_total is None and p.hotel_class is None and p.currency is None


@pytest.mark.parametrize("changes", [
    {"nightly_min": 4000, "nightly_max": 2000},
    {"departure_date": "2027-02-14", "return_date": "2027-02-10"},
    {"adults": True}, {"hotel_class": 6}, {"guest_rating_min": 8},
    {"origin": " Delhi ", "destination": "delhi"}, {"destination": "  "},
    {"nightly_max": "NaN"}, {"budget_total": -1}, {"cities": ["Jaipur", "Jodhpur"]},
])
def test_rejects_invalid_preferences(changes):
    with pytest.raises(ValidationError):
        TripPreferences(**changes)


def test_exact_decimal_total_and_budget_boundary():
    result = summarize_costs(complete_quotes(), "INR", Decimal("6000.30"))
    assert result.complete_subtotal == Decimal("6000.30")
    assert result.budget_status == "within_budget"
    assert summarize_costs(complete_quotes(), "INR", Decimal("6000.29")).budget_status == "over_budget"


def test_missing_return_price_is_unknown_not_zero():
    quotes = complete_quotes(); quotes.pop("return_transport")
    result = summarize_costs(quotes, "INR", Decimal("25000"))
    assert result.known_subtotal == Decimal("5000.10")
    assert result.complete_subtotal is None and result.budget_status == "unknown"
    assert result.missing_or_unverified == ["return_transport"]
    assert summarize_costs({}, "INR").known_subtotal is None


def test_currency_and_tax_uncertainty_prevent_affordability_claim():
    quotes = complete_quotes()
    quotes["hotel_stay"] = quote("40", basis="whole_stay", currency="USD")
    result = summarize_costs(quotes, "INR", Decimal("9000"))
    assert result.complete_subtotal is None and result.known_subtotal == Decimal("2000.30")
    quotes = complete_quotes()
    quotes["hotel_stay"].taxes_included = None
    assert summarize_costs(quotes, "INR").budget_status == "unknown"


def test_unverified_basis_or_occupancy_is_not_a_complete_price():
    assert not PriceQuote(amount=0, currency="INR").complete
    q = quote("1000"); q.covers_all_travelers = False
    assert not q.complete
    quotes = complete_quotes(); quotes["hotel_stay"] = quote("4000")
    assert summarize_costs(quotes, "INR").complete_subtotal is None


def test_selective_replanning_preserves_unrelated_searches():
    before = TripPreferences(origin="Delhi", destination="Jaipur", nightly_max=4000)
    after = TripPreferences(**(before.model_dump() | {"nightly_max": 3000}))
    assert affected_components(before, after) == {"hotels", "itinerary", "costs"}
    interests = TripPreferences(**(before.model_dump() | {"interests": ["history"]}))
    assert affected_components(before, interests) == {"places", "itinerary"}
    assert affected_components(before, before) == set()
    assert set(DEPENDENCIES) == set(TripPreferences.model_fields)


def test_date_change_invalidates_transport_hotels_and_weather():
    before = TripPreferences(departure_date="2027-02-10", return_date="2027-02-14")
    after = TripPreferences(departure_date="2027-02-11", return_date="2027-02-14")
    assert affected_components(before, after) == {"transport", "hotels", "weather", "itinerary", "costs"}


def test_locked_selection_cannot_be_changed_removed_or_unlocked():
    locked = Selection(component="hotel_stay", offer_id="H1", locked=True)
    current = {"hotel_stay": locked}
    for proposed in [{}, {"hotel_stay": Selection(component="hotel_stay", offer_id="H2", locked=True)},
                     {"hotel_stay": Selection(component="hotel_stay", offer_id="H1", locked=False)}]:
        assert enforce_selection_locks(current, proposed) == ["hotel_stay"]
        assert locked.offer_id == "H1" and locked.locked
    assert enforce_selection_locks(current, current) == []


def test_source_requires_timezone_and_http_link():
    Source(provider="fixture", fetched_at=datetime.now(timezone.utc), synthetic=True)
    with pytest.raises(ValidationError):
        Source(provider="fixture", fetched_at=datetime(2027, 2, 10))
    with pytest.raises(ValidationError):
        Source(provider="fixture", fetched_at=datetime.now(timezone.utc), url="javascript:alert(1)")


def test_settings_hide_keys_and_only_require_them_at_live_boundary(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("GROQ_API_KEY=fixture-secret\nUNRELATED_SETTING=ignored\n")
    settings = Settings(_env_file=path)
    assert "fixture-secret" not in repr(settings)
    assert "fixture-secret" not in settings.model_dump_json()
    assert settings.require_provider_key("groq") == "fixture-secret"
    assert not Settings(_env_file=None).groq_api_key.get_secret_value()
    with pytest.raises(ValueError, match="SERPAPI_API_KEY"):
        Settings(_env_file=None, serpapi_api_key="").require_provider_key("serpapi")
