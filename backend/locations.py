"""Explicit city bindings shared by the browser and API. No network lookup."""
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    station: str
    airport: str | None = None
    aliases: tuple[str, ...] = ()


CITY_CATALOG = (
    City("Delhi", "NDLS", "DEL", ("New Delhi",)),
    City("Jaipur", "JP", "JAI"),
    City("Bengaluru", "SBC", "BLR", ("Bangalore",)),
    City("Mysuru", "MYS", aliases=("Mysore",)),
)
CITY_NAMES = tuple(city.name for city in CITY_CATALOG)
_BY_NAME = {name.casefold(): city for city in CITY_CATALOG for name in (city.name, *city.aliases)}


def find_city(name: str | None) -> City | None:
    return _BY_NAME.get(" ".join(name.split()).casefold()) if name else None


def route_error(origin: str | None, destination: str | None, mode: str | None) -> str | None:
    """Reject unsupported inputs, while letting chat ask about missing cities."""
    a, b = find_city(origin), find_city(destination)
    if (origin is not None and a is None) or (destination is not None and b is None):
        return "Choose a supported city: " + ", ".join(CITY_NAMES) + "."
    if a and a == b:
        return "Choose different cities for departure and destination."
    if mode in ("flight", "compare") and any(city and not city.airport for city in (a, b)):
        return "For trips involving Mysuru, choose train. The demo has no flight binding for Mysuru."
    return None
