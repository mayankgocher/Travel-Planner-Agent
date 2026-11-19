"""Decide when a RailRadar match is exact and when chat must ask."""
from dataclasses import dataclass
from typing import Literal

from backend.locations import find_city
from backend.schemas import StationCandidate, TripPreferences

Endpoint = Literal["origin", "destination"]


def label(text: str | None) -> str:
    return " ".join((text or "").split())[:100]


def exact_station(query: str, matches: list[StationCandidate]) -> StationCandidate | None:
    code_match = next((station for station in matches if station.code == query.upper()), None)
    if code_match:
        return code_match
    # A station named like the city can still be one of several useful matches.
    if len(matches) == 1 and query.casefold() in (label(matches[0].name).casefold(),
                                                label(matches[0].city).casefold()):
        return matches[0]
    return None


@dataclass(frozen=True)
class StationChoice:
    field: Endpoint
    query: str
    matches: tuple[StationCandidate, ...]

    def question(self) -> str:
        options = "\n".join(f"{s.code} — {label(s.name)}" + (f" ({label(s.city)})" if label(s.city) else "")
                            for s in self.matches)
        side = "departure" if self.field == "origin" else "destination"
        return (f"Confirm the {side} station for {self.query}. Reply with one of these station codes:\n"
                f"{options}\nTo change your request, say 'cancel station selection'.")

    def apply(self, preferences: TripPreferences, station: StationCandidate) -> TripPreferences:
        if preferences.transport_mode == "compare":
            # The airport resolution selected the shared city; don't relabel it.
            return preferences.model_copy(update={f"{self.field}_station": station.code})
        station_name = label(station.name)
        # Avoid using an opaque station code as the destination for hotels/places.
        # When the station has no city, retain a matching city query or its station name.
        location = label(station.city)
        if not location:
            location = (self.query if self.query.casefold() != station.code.casefold()
                        and self.query.casefold() in station_name.casefold() else station_name)
        city = find_city(location)
        return preferences.model_copy(update={
            self.field: city.name if city else location,
            f"{self.field}_station": station.code,
        })


def station_matches_city(station: StationCandidate, city: str) -> bool:
    """For comparisons, don't pair an airport with an unrelated station."""
    target = label(city).casefold()
    if station.city:
        known = find_city(station.city)
        return label(known.name if known else station.city).casefold() == target
    name = label(station.name).casefold()
    return name == target or name.startswith(target + " ")
