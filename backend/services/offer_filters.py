"""Hard constraints are checked before offers reach an LLM."""
from backend.schemas import HotelOffer, TransportOffer, TripPreferences


def transport_leg(offer: TransportOffer, p: TripPreferences) -> str | None:
    route = (offer.origin.casefold(), offer.destination.casefold())
    outward = ((p.origin or "").casefold(), (p.destination or "").casefold())
    if route == outward and offer.departure.date() == p.departure_date:
        return "outbound_transport"
    if route == outward[::-1] and offer.departure.date() == p.return_date:
        return "return_transport"
    return None


def eligible_transport(offers: list[TransportOffer], p: TripPreferences) -> list[TransportOffer]:
    result = []
    for offer in offers:
        if not transport_leg(offer, p) or offer.adults != p.adults:
            continue
        if p.transport_mode in ("train", "flight") and offer.mode != p.transport_mode:
            continue
        requested_class = p.train_class if offer.mode == "train" else p.flight_class
        if requested_class and (offer.travel_class or "").casefold() != requested_class.casefold():
            continue
        if offer.mode == "flight" and p.flight_max_price is not None:
            if (not offer.price.complete or offer.price.currency != p.currency
                    or offer.price.amount > p.flight_max_price):
                continue
        result.append(offer)
    return result


def eligible_hotels(offers: list[HotelOffer], p: TripPreferences) -> list[HotelOffer]:
    result = []
    for offer in offers:
        if ((offer.city.casefold() != (p.destination or "").casefold())
                or offer.check_in != p.departure_date or offer.check_out != p.return_date
                or offer.adults != p.adults):
            continue
        if (offer.room_type or "").casefold() in ("dormitory", "shared_room"):
            continue
        if p.hotel_class is not None:
            if offer.hotel_class is None:
                continue
            if p.hotel_class_rule == "exact" and offer.hotel_class != p.hotel_class:
                continue
            if p.hotel_class_rule == "at_least" and offer.hotel_class < p.hotel_class:
                continue
        if p.guest_rating_min is not None and (offer.guest_rating is None or offer.guest_rating < p.guest_rating_min):
            continue
        if p.nightly_min is not None or p.nightly_max is not None:
            if offer.nightly_price is None or offer.price.currency != p.currency:
                continue
            if p.nightly_min is not None and offer.nightly_price < p.nightly_min:
                continue
            if p.nightly_max is not None and offer.nightly_price > p.nightly_max:
                continue
        result.append(offer)
    return result
