"""Synthetic workflow fixtures, NOT live search tools or LLM agents.

Supports Delhi -> Jaipur only, for routing tests. Never use these functions as
fallbacks after a real provider fails. No HTTP client or API key is used.
"""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from backend.graph.state import TripState
from backend.schemas import HotelOffer, PriceQuote, Source, TransportOffer, TripPreferences

LABEL = "SYNTHETIC DEMO — not real offers, schedules, prices or recommendations"
INDIA = ZoneInfo("Asia/Kolkata")


def ensure_demo_route(p: TripPreferences) -> None:
    if p.origin != "Delhi" or p.destination != "Jaipur" or p.missing_required():
        raise ValueError("Demo fixtures support a complete Delhi-Jaipur request only")


def source() -> Source:
    return Source(provider="synthetic_fixture", source_id="checkpoint03", synthetic=True,
                  fetched_at=datetime.now(timezone.utc))


def transport(p: TripPreferences) -> list[TransportOffer]:
    ensure_demo_route(p)
    # Deliberately unverified price scope: never claim a complete live fare.
    return [TransportOffer(id="DEMO-OUT", mode="train", origin="Delhi", destination="Jaipur",
            departure=datetime.combine(p.departure_date, time(8), INDIA),
            arrival=datetime.combine(p.departure_date, time(13), INDIA), adults=p.adults,
            price=PriceQuote(amount="1000", currency="INR"), source=source()),
            TransportOffer(id="DEMO-RETURN", mode="train", origin="Jaipur", destination="Delhi",
            departure=datetime.combine(p.return_date, time(16), INDIA),
            arrival=datetime.combine(p.return_date, time(21), INDIA), adults=p.adults,
            price=PriceQuote(amount="1100", currency="INR"), source=source())]


def hotels(p: TripPreferences) -> list[HotelOffer]:
    ensure_demo_route(p)
    return [HotelOffer(id="DEMO-HOTEL", name="Synthetic Example Stay", city="Jaipur",
            check_in=p.departure_date, check_out=p.return_date, adults=p.adults,
            hotel_class=3, guest_rating=4.2, nightly_price="3000",
            price=PriceQuote(currency="INR"), source=source())]


def itinerary(state: TripState) -> dict:
    # No attraction scheduling is pretended here. Later agents will receive Maps
    # candidates and validated transport timings rather than invented fixtures.
    return {"synthetic": True, "notice": LABEL, "activities": [],
            "message": "Workflow reached itinerary with current transport/hotel data.",
            "received_transport_ids": [o["id"] for o in state.get("transport", [])],
            "received_hotel_ids": [o["id"] for o in state.get("hotels", [])],
            "refresh_places": "places" in state.get("invalidated", []),
            "refresh_weather": "weather" in state.get("invalidated", [])}
