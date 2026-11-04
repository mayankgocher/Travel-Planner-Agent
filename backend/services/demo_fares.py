"""Repeatable invented prices for confirmed train/route/class combinations only."""
from decimal import Decimal
import hashlib
import re

from backend.schemas import PriceQuote, TransportOffer

RULE_VERSION = "sha256-class-v1"
# Demo design choices only: these are NOT market prices or fare estimates.
CLASS_RANGES = {
    "2S": (100, 500), "SL": (200, 900), "3E": (600, 1400), "3A": (700, 1500),
    "2A": (1100, 2300), "1A": (1600, 3500), "CC": (250, 1000), "EC": (600, 1800),
    "EA": (600, 1800), "FC": (500, 1800), "VS": (250, 1000), "CH": (250, 1000),
    "SH": (250, 1000), "VC": (500, 1500), "EV": (600, 1800),
}


def apply_demo_fare(offer, timetable, travel_class):
    """Preserve schedule provenance; label only the invented price as demo."""
    cabin = travel_class.strip().upper()
    if (offer.mode != "train" or not offer.train_number or not re.fullmatch(r"[0-9]{5}", offer.train_number)
            or cabin not in CLASS_RANGES or timetable.train_number != offer.train_number
            or timetable.is_prs_bookable is False or cabin not in timetable.operated_classes
            or timetable.source.synthetic != offer.source.synthetic):
        raise ValueError("Demo fare requires matching train and operated class evidence")
    a, b = offer.departure_station, offer.arrival_station
    if (not a or not b or a == b or not re.fullmatch(r"[A-Z0-9]{1,10}", a) or not re.fullmatch(r"[A-Z0-9]{1,10}", b)
            or timetable.stop_codes.count(a) != 1 or timetable.stop_codes.count(b) != 1
            or timetable.stop_codes.index(a) >= timetable.stop_codes.index(b)):
        raise ValueError("Demo fare requires a confirmed ordered station pair")
    key = "|".join((offer.train_number, a, b, cabin))
    number = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
    lower, upper = CLASS_RANGES[cabin]
    unit = Decimal(lower + number % (upper - lower + 1))
    quote = PriceQuote(amount=unit * offer.adults, per_adult_amount=unit, currency="INR", basis="whole_leg",
        covers_all_travelers=True, taxes_included=None, pricing_mode="demo", demo_rule_version=RULE_VERSION,
        notes=["ASSUMED DEMO FARE — not a real railway quote or a market-price estimate.",
               "Invented per-adult amount multiplied by the stated adult count; taxes and payable charges are not verified.",
               "Deterministic key: " + key + "; date and passenger count are excluded from the per-adult hash.",
               "Schedules/classes retain their original source; RailRadar did not supply this price."])
    return TransportOffer.model_validate(offer.model_dump() | {"travel_class": cabin, "price": quote.model_dump()})
