"""Normalize hotel/place responses; unknown evidence remains unknown."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from backend.providers.http import ProviderError
from backend.schemas import HotelOffer, PlaceCandidate, PriceQuote, Source
from backend.services.place_aliases import possible_alias_pairs
from backend.providers.results import SearchResult


def money(value):
    if type(value) not in (int, float, str):
        return None
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount >= 0 else None
    except InvalidOperation:
        return None


def public_link(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if url.scheme not in ("https", "http") or not url.hostname or url.username or url.password:
            return None
        query = [(k, v) for k, v in parse_qsl(url.query, keep_blank_values=True)
                 if k.casefold() not in ("api_key", "apikey", "authorization", "password")]
        return urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), url.fragment))
    except ValueError:
        return None


def provider_time(body):
    metadata = body.get("search_metadata")
    value = metadata.get("processed_at") if isinstance(metadata, dict) else None
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def stable_id(prefix, item, *fields):
    known = item.get("property_token") if prefix == "hotel" else item.get("place_id") or item.get("data_id") or item.get("data_cid")
    return prefix + ":" + str(known or hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:20])


def rate(data):
    if not isinstance(data, dict):
        return None, None
    after_tax = money(data.get("extracted_after_taxes_fees"))
    if after_tax is not None:
        return after_tax, True
    for key in ("extracted_display_price", "extracted_lowest", "extracted_before_taxes_fees"):
        amount = money(data.get(key))
        if amount is not None:
            return amount, False if key == "extracted_before_taxes_fees" else None
    return None, None


def hotel_source_link(item, metadata, p):
    """Reject explicitly conflicting stay links; never claim a source URL is checkout."""
    link = public_link(item.get("link"))
    if link:
        expected = {"checkin": p.departure_date, "checkindate": p.departure_date,
                    "checkout": p.return_date, "checkoutdate": p.return_date,
                    "numnights": (p.return_date - p.departure_date).days, "numguests": p.adults}
        for key, value in parse_qsl(urlsplit(link).query):
            normalized = re.sub(r"[^a-z]", "", key.casefold())
            if normalized not in expected:
                continue
            target = expected[normalized]
            acceptable = {str(target)} if isinstance(target, int) else {
                target.isoformat(), target.strftime("%d-%m-%Y"), target.strftime("%m/%d/%Y"), target.strftime("%d/%m/%Y")}
            if value not in acceptable:
                fallback = public_link(metadata.get("google_hotels_url")) if isinstance(metadata, dict) else None
                note = "Hotel website URL contained conflicting stay parameters; "
                return fallback, note + ("using a general source search link instead." if fallback else "no compatible source link is available.")
    fallback = public_link(metadata.get("google_hotels_url")) if isinstance(metadata, dict) else None
    return link or fallback, None


def parse_hotels(response, p, currency):
    body = response.data
    properties = body.get("properties", [])
    if not isinstance(properties, list):
        raise ProviderError("invalid_properties_shape", status=200)
    echoed = body.get("search_parameters", {})
    if not isinstance(echoed, dict):
        raise ProviderError("invalid_search_parameters_shape", status=200)
    expected = {"check_in_date": p.departure_date.isoformat(), "check_out_date": p.return_date.isoformat(),
                "adults": str(p.adults), "currency": currency}
    if any(k in echoed and str(echoed[k]) != v for k, v in expected.items()):
        raise ProviderError("hotel_query_response_mismatch", status=200)
    scope_matches = all(str(echoed.get(k)) == v for k, v in expected.items())
    offers, warnings, seen = [], [], set()
    for index, item in enumerate(properties):
        if not isinstance(item, dict) or item.get("type") not in (None, "hotel"):
            continue
        try:
            name = item.get("name", "")
            id = stable_id("hotel", item, name, item.get("gps_coordinates"), item.get("link"))
            if id in seen:
                continue
            nightly, _ = rate(item.get("rate_per_night"))
            total, taxes = rate(item.get("total_rate"))
            stars = money(item.get("extracted_hotel_class"))
            if stars is None:
                match = re.fullmatch(r"([1-5])-star hotel", str(item.get("hotel_class", "")))
                stars = Decimal(match[1]) if match else money(item.get("hotel_class"))
            stars = int(stars) if stars is not None and stars == stars.to_integral_value() else None
            notes = ["Search passenger count does not verify the returned room's occupancy or room type.",
                     "Displayed nightly rate may be an average; final nightly charges require source confirmation."]
            if taxes is not True:
                notes.append("Taxes and fees are not verified as included in this quoted total.")
            metadata = body.get("search_metadata")
            link, link_warning = hotel_source_link(item, metadata, p)
            if link_warning:
                notes.append(link_warning)
                warnings.append(name + ": " + link_warning)
            source = Source(provider="serpapi_google_hotels", fetched_at=response.fetched_at,
                provider_data_at=provider_time(body), source_id=id,
                url=link)
            offer = HotelOffer(id=id, name=name, city=p.destination, check_in=p.departure_date, check_out=p.return_date,
                adults=p.adults, hotel_class=stars, guest_rating=item.get("overall_rating"),
                nightly_price=nightly, room_type=None, price=PriceQuote(amount=total, currency=currency,
                    basis="whole_stay" if scope_matches else "unverified", covers_all_travelers=False,
                    taxes_included=taxes, notes=notes), source=source)
            offers.append(offer); seen.add(id)
        except (ValidationError, ValueError, TypeError):
            warnings.append(f"Skipped malformed hotel record at index {index}.")
    if offers:
        warnings.append("Room type/occupancy are unverified; hotel totals are quoted offers, not confirmed payable trip costs.")
    if not scope_matches:
        warnings.append("Search scope was not fully echoed; total-stay price basis remains unverified.")
    return SearchResult(offers, warnings, {"top_level_keys": list(body),
        "first_property_keys": list(properties[0]) if properties and isinstance(properties[0], dict) else []})


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def parse_hours(raw):
    if isinstance(raw, list):
        raw = {k: v for row in raw if isinstance(row, dict) for k, v in row.items()}
    result = {}
    if not isinstance(raw, dict):
        return result
    for weekday, value in raw.items():
        if not isinstance(weekday, str) or weekday.casefold() not in WEEKDAYS or not isinstance(value, str):
            continue
        day = WEEKDAYS.index(weekday.casefold())
        text = value.replace("\u202f", " ").replace("\xa0", " ").strip()
        if text.casefold() == "closed":
            result[day] = []
            continue
        if text.casefold() == "open 24 hours":
            result[day] = [("00:00", "23:59")]
            continue
        windows = []
        for part in text.split(","):
            bounds = re.split(r"[–—-]", part)
            if len(bounds) != 2:
                windows = []
                break
            times = []
            for bound in bounds:
                bound = re.sub(r"\s+", " ", bound.strip()).upper()
                parsed = None
                for fmt in ("%I:%M %p", "%I %p", "%H:%M"):
                    try:
                        parsed = datetime.strptime(bound, fmt).strftime("%H:%M")
                        break
                    except ValueError:
                        pass
                times.append(parsed)
            if None in times:
                windows = []
                break
            windows.append(tuple(times))
        if windows:
            result[day] = windows
    return result


def parse_places(response):
    body = response.data
    rows = body.get("local_results", [])
    if not rows and isinstance(body.get("place_results"), dict):
        rows = [body["place_results"]]
    if not isinstance(rows, list):
        raise ProviderError("invalid_places_shape", status=200)
    places, warnings, seen = [], [], set()
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        try:
            name = item.get("title", "")
            gps = item.get("gps_coordinates") or {}
            if not isinstance(gps, dict):
                raise ValueError("Invalid coordinates")
            id = stable_id("place", item, name, gps, item.get("address"))
            if id in seen:
                continue
            place = PlaceCandidate(id=id, name=name, address=item.get("address"), rating=item.get("rating"),
                latitude=gps.get("latitude"), longitude=gps.get("longitude"),
                weekly_hours=parse_hours(item.get("operating_hours", item.get("hours"))),
                source=Source(provider="serpapi_google_maps", fetched_at=response.fetched_at,
                    provider_data_at=provider_time(body), source_id=id, url=public_link(item.get("website"))))
            places.append(place); seen.add(id)
        except (ValidationError, ValueError, TypeError):
            warnings.append(f"Skipped malformed place record at index {index}.")
    for a, b in possible_alias_pairs(places):
        a.possible_duplicate_ids.append(b.id)
        b.possible_duplicate_ids.append(a.id)
        warnings.append(f"Possible aliases: {a.name} / {b.name}. Do not schedule both; their hours need review.")
    if any(len(p.weekly_hours) < 7 for p in places):
        warnings.append("Some weekday hours are unverified; a current open/closed label is not a weekly schedule.")
    warnings.append("Admission fees were not fetched or verified. Geographic relevance and nearby aliases need review.")
    return SearchResult(places, warnings, {"top_level_keys": list(body),
        "first_place_keys": list(rows[0]) if rows and isinstance(rows[0], dict) else []})


class SerpApiAdapter:
    def __init__(self, http):
        self.http = http

    def hotels(self, p):
        if not p.departure_date or not p.return_date or not p.destination or not p.adults:
            raise ValueError("Hotel search requires destination, stay dates and adults")
        currency = p.currency or "INR"
        params = {"engine": "google_hotels", "q": "Hotels in " + p.destination,
                  "check_in_date": p.departure_date.isoformat(), "check_out_date": p.return_date.isoformat(),
                  "adults": p.adults, "children": 0, "currency": currency, "hl": "en", "gl": "in"}
        if p.nightly_min is not None:
            params["min_price"] = str(p.nightly_min.to_integral_value(rounding=ROUND_FLOOR))
        if p.nightly_max is not None:
            params["max_price"] = str(p.nightly_max.to_integral_value(rounding=ROUND_CEILING))
        if p.hotel_class is not None and p.hotel_class >= 2:
            params["hotel_class"] = str(p.hotel_class) if p.hotel_class_rule == "exact" else ",".join(str(s) for s in range(p.hotel_class, 6))
        if p.guest_rating_min is not None and p.guest_rating_min >= 3.5:
            params["rating"] = 9 if p.guest_rating_min >= 4.5 else 8 if p.guest_rating_min >= 4 else 7
        return parse_hotels(self.http.get(params), p, currency)

    def places(self, p):
        if not p.destination:
            raise ValueError("Place search requires destination")
        interests = ", ".join(p.interests)
        params = {"engine": "google_maps", "type": "search", "q": f"{interests} tourist attractions in {p.destination}".strip(), "hl": "en"}
        return parse_places(self.http.get(params))
