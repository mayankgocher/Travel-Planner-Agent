"""Labeled, complete-scope synthetic evidence for agent integration tests only."""
from datetime import datetime, time
from backend import demo_workers
from backend.schemas import HotelOffer, PlaceCandidate, PriceQuote, TransportOffer


def transport(p):
    demo_workers.ensure_demo_route(p)
    result = []
    for mode, out_price, back_price, duration in [("train", "2400", "2500", 5), ("flight", "6400", "6500", 1)]:
        for suffix, origin, dest, day, hour, price in [
            ("OUT", "Delhi", "Jaipur", p.departure_date, 8, out_price),
            ("RETURN", "Jaipur", "Delhi", p.return_date, 16, back_price)]:
            result.append(TransportOffer(id=f"FIXTURE-{mode}-{suffix}", mode=mode, origin=origin, destination=dest,
                departure=datetime.combine(day, time(hour), demo_workers.INDIA),
                arrival=datetime.combine(day, time(hour + duration), demo_workers.INDIA), adults=p.adults,
                travel_class="3A" if mode == "train" else "economy",
                price=PriceQuote(amount=price, currency="INR", basis="whole_leg", covers_all_travelers=True, taxes_included=True),
                source=demo_workers.source()))
    return result


def hotels(p):
    demo_workers.ensure_demo_route(p)
    return [HotelOffer(id=id, name="Synthetic " + id, city="Jaipur", check_in=p.departure_date,
        check_out=p.return_date, adults=p.adults, hotel_class=stars, guest_rating=rating,
        room_type="private_room", nightly_price=nightly,
        price=PriceQuote(amount=nightly * (p.return_date - p.departure_date).days, currency="INR", basis="whole_stay",
                         covers_all_travelers=True, taxes_included=True), source=demo_workers.source())
        for id, nightly, stars, rating in [("FIXTURE-H1", 3000, 3, 4.2), ("FIXTURE-H2", 3800, 3, 4.6),
                                           ("FIXTURE-LUXURY", 6000, 5, 4.8), ("FIXTURE-LOW-RATING", 2500, 3, 3.5)]]


def places(p):
    demo_workers.ensure_demo_route(p)
    return [PlaceCandidate(id=id, name=name, weekly_hours={d: [("09:00", "17:00")] for d in range(7)},
                           source=demo_workers.source())
            for id, name in [("FIXTURE-P1", "Synthetic History Museum"), ("FIXTURE-P2", "Synthetic Garden"),
                             ("FIXTURE-P3", "Synthetic Fort")]]
