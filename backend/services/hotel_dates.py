"""Derive hotel nights from the ranked transport recommendations."""
from zoneinfo import ZoneInfo

from backend.schemas import TransportOffer, TripPreferences
from backend.services.offer_filters import transport_leg


def stay_preferences(p, transport, destination_timezone):
    offers = [TransportOffer.model_validate(o) for o in transport]
    outward = next((o for o in offers if transport_leg(o, p) == "outbound_transport"), None)
    returning = next((o for o in offers if transport_leg(o, p) == "return_transport"), None)
    if not outward or not returning:
        return p  # Requested trip dates only; caller must disclose unconfirmed transport coverage.
    zone = ZoneInfo(destination_timezone)
    start, end = outward.arrival.astimezone(zone).date(), returning.departure.astimezone(zone).date()
    if end <= start:
        raise ValueError("Transport leaves no overnight hotel stay; clarify trip dates")
    return TripPreferences.model_validate(p.model_dump() | {"departure_date": start, "return_date": end})
