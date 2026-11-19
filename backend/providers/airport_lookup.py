"""Resolve Indian airport candidates from SerpApi's flight autocomplete."""
from dataclasses import dataclass
import re
import unicodedata

from backend.locations import CITY_CATALOG, find_city
from backend.providers.http import ProviderError
from backend.schemas import TripPreferences

INDIA_REGIONS = frozenset("""
india|andaman and nicobar islands|andhra pradesh|arunachal pradesh|assam|bihar|
chandigarh|chhattisgarh|dadra and nagar haveli and daman and diu|delhi|goa|
gujarat|haryana|himachal pradesh|jammu and kashmir|jharkhand|karnataka|kerala|
ladakh|lakshadweep|madhya pradesh|maharashtra|manipur|meghalaya|mizoram|nagaland|
odisha|puducherry|punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|
uttar pradesh|uttarakhand|west bengal
""".replace("\n", "").split("|")) | {"national capital territory of delhi", "nct of delhi"}


def normalize(value: str) -> str:
    value = "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


@dataclass(frozen=True)
class AirportCandidate:
    code: str
    name: str
    city: str
    qualifier: str = ""


def catalog_airport(query: str) -> AirportCandidate | None:
    city = find_city(query) or next((c for c in CITY_CATALOG if c.airport == query.strip().upper()), None)
    return AirportCandidate(city.airport, city.name, city.name) if city and city.airport else None


def search_airports(http, query: str) -> list[AirportCandidate]:
    result = http.get({"engine": "google_flights_autocomplete", "q": query,
                       "hl": "en", "gl": "in", "exclude_regions": "true"})
    rows = result.data.get("suggestions", [])
    if not isinstance(rows, list):
        raise ProviderError("invalid_airport_suggestions", status=200)
    options = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "city" or not isinstance(row.get("name"), str):
            continue
        parts = [part.strip() for part in row["name"].split(",") if part.strip()]
        if len(parts) < 2 or normalize(parts[-1]) not in INDIA_REGIONS:
            continue  # gl localizes the search; it does not restrict results to India.
        airports = row.get("airports")
        if not isinstance(airports, list):
            continue
        for airport in airports:
            if not isinstance(airport, dict):
                continue
            code, name = airport.get("id"), airport.get("name")
            if isinstance(code, str) and re.fullmatch(r"[A-Z]{3}", code) and isinstance(name, str) and name.strip():
                city = find_city(parts[0])
                options.append(AirportCandidate(code, " ".join(name.split())[:120],
                                                city.name if city else parts[0][:100], ", ".join(parts[1:])[:100]))
    return options


def pick_airports(query: str, options: list[AirportCandidate]) -> tuple[AirportCandidate | None, tuple[AirportCandidate, ...]]:
    """Only exact matches can auto-select; suggestions require a code reply."""
    q = normalize(query)
    codes = [a for a in options if a.code == q.upper()]
    if codes:
        return codes[0], ()
    exact = [a for a in options if q in (
        normalize(a.city), normalize(f"{a.city}, {a.qualifier}"), normalize(a.name),
    )]
    unique = tuple({a.code: a for a in reversed(exact or options)}.values())[::-1]
    if exact and len(unique) == 1:
        return unique[0], ()
    return None, unique[:5]


@dataclass(frozen=True)
class AirportChoice:
    field: str
    query: str
    matches: tuple[AirportCandidate, ...]

    def question(self) -> str:
        options = "\n".join(f"{a.code} — {a.name} ({a.city}{', ' + a.qualifier if a.qualifier else ''})"
                            for a in self.matches)
        side = "departure" if self.field == "origin" else "destination"
        return (f"Confirm the {side} airport for {self.query}. Reply with one of these airport codes:\n"
                f"{options}\nTo change your request, say 'cancel airport selection'.")

    def apply(self, preferences: TripPreferences, airport: AirportCandidate) -> TripPreferences:
        updates = {self.field: airport.city, f"{self.field}_airport": airport.code}
        if normalize(airport.city) != normalize(getattr(preferences, self.field)):
            updates[f"{self.field}_station"] = None
        return preferences.model_copy(update=updates)
