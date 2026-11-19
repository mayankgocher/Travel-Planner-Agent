"""Real retrieval callbacks. Python owns provider order, limits and failure handling."""
from contextlib import ExitStack
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool

from backend.locations import find_city
from backend.providers.flights import AirportLocation, FlightAdapter
from backend.providers.http import ProviderError, SerpApiHttp
from backend.providers.rail_http import RailRadarHttp
from backend.providers.railradar import RailRadarAdapter, StationBinding
from backend.providers.results import SearchResult
from backend.providers.serpapi import SerpApiAdapter
from backend.schemas import TripPreferences
from backend.services.offer_filters import eligible_transport


@dataclass(frozen=True)
class JourneyBindings:
    # Explicit selections, not a silent first autocomplete match.
    origin_airport: AirportLocation | None
    destination_airport: AirportLocation | None
    origin_station: StationBinding | None
    destination_station: StationBinding | None
    destination_timezone: str

    def __post_init__(self):
        ZoneInfo(self.destination_timezone)
        for airport, station in ((self.origin_airport, self.origin_station),
                                 (self.destination_airport, self.destination_station)):
            if airport and station and airport.city.casefold() != station.city.casefold():
                raise ValueError("Airport and station bindings must describe the same selected city")


def trip_bindings(preferences: TripPreferences) -> JourneyBindings:
    p = preferences
    if not p.origin or not p.destination:
        raise ValueError("Both departure and destination cities are required.")
    zone = "Asia/Kolkata"
    origin = find_city(p.origin)
    destination = find_city(p.destination)
    airports = (None, None)
    stations = (None, None)
    if p.transport_mode in ("flight", "compare"):
        a = p.origin_airport or (origin.airport if origin else None)
        b = p.destination_airport or (destination.airport if destination else None)
        if not a or not b or a == b:
            raise ValueError("Two distinct airport bindings are required.")
        airports = AirportLocation(a, p.origin, zone), AirportLocation(b, p.destination, zone)
    if p.transport_mode in ("train", "compare"):
        a = p.origin_station or (origin.station if origin else None)
        b = p.destination_station or (destination.station if destination else None)
        if not a or not b or a == b:
            raise ValueError("Two distinct station bindings are required.")
        stations = StationBinding(a, p.origin), StationBinding(b, p.destination)
    return JourneyBindings(*airports, *stations, zone)


def jaipur_probe_bindings():
    return JourneyBindings(AirportLocation("DEL", "Delhi", "Asia/Kolkata"), AirportLocation("JAI", "Jaipur", "Asia/Kolkata"),
                           StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur"), "Asia/Kolkata")


class TravelProviderSession:
    """One execution's clients/audit, not a search cache or persistent trip state."""
    def __init__(self, settings, bindings, *, serp_http=None, rail_http=None, expand_rail_shortlist=False):
        self.settings, self.bindings = settings, bindings
        self.serp_http, self.rail_http = serp_http, rail_http
        self.expand_rail_shortlist = expand_rail_shortlist
        self._stack, self._blocked = ExitStack(), {}
        self.errors, self.tool_calls = [], []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._stack.close()

    def _serp(self):
        if self.serp_http is None:
            self.serp_http = self._stack.enter_context(SerpApiHttp(self.settings.require_provider_key("serpapi"), max_requests=4))
        return self.serp_http

    def _rail(self):
        if self.rail_http is None:
            # Two schedule searches plus up to six timetables in the browser's demo-fare mode.
            # Live fares keep the former two timetables and one fare per direction.
            limit = 8 if self.expand_rail_shortlist or self.settings.train_fare_mode == "live" else 6
            self.rail_http = self._stack.enter_context(RailRadarHttp(self.settings.require_provider_key("railradar"), max_requests=limit))
        return self.rail_http

    def _search(self, provider, operation, function):
        if provider in self._blocked:
            return SearchResult([], [provider + " is unavailable for this run; skipped " + operation + "."], {})
        try:
            return function()
        except ProviderError as exc:
            error = {"provider": provider, "operation": operation, **exc.public()}
            self.errors.append(error)
            if exc.status is None or exc.status in (401, 403, 429) or exc.status >= 500:
                self._blocked[provider] = True
            return SearchResult([], [provider + " " + operation + " failed: " + exc.code + ". No replacement data invented."], {})
        except ValueError:
            # Configuration exception text might include a value; expose a fixed diagnostic only.
            self.errors.append({"provider": provider, "operation": operation, "code": "configuration_or_binding_error"})
            self._blocked[provider] = True
            return SearchResult([], [provider + " configuration/selection is incomplete; " + operation + " unavailable."], {})

    def transport(self, p):
        if p.transport_mode not in ("train", "flight", "compare"):
            return SearchResult([], ["Choose train, flight or compare before searching transport."], {})
        offers, warnings, skipped = [], [], []
        for mode in (("train", "flight") if p.transport_mode == "compare" else (p.transport_mode,)):
            for leg in ("outbound", "return"):
                if mode == "train":
                    a, b = self.bindings.origin_station, self.bindings.destination_station
                    if a is None or b is None:
                        warnings.append("Train search requires a station binding for both cities.")
                        break
                    if leg == "return": a, b = b, a
                    def search(a=a, b=b, leg=leg):
                        adapter = RailRadarAdapter(self._rail(), fare_mode=self.settings.train_fare_mode)
                        try:
                            return adapter.search_leg(p, a, b, leg=leg, expand_if_unpriced=self.expand_rail_shortlist)
                        except ProviderError as exc:
                            # Keep completed schedule/class evidence even if a live fare request fails.
                            if adapter.last_result:
                                offers.extend(adapter.last_result.items)
                                warnings.extend(adapter.last_result.warnings)
                            raise exc
                    result = self._search("railradar", mode + "_" + leg, search)
                else:
                    a, b = self.bindings.origin_airport, self.bindings.destination_airport
                    if a is None or b is None:
                        warnings.append("Flight search requires an airport binding for both cities.")
                        break
                    if leg == "return": a, b = b, a
                    def search(a=a, b=b, leg=leg):
                        zones = {code: "Asia/Kolkata" for code in ("DEL", "JAI", "BOM", "BLR", "HYD", "MAA", "CCU", "AMD", "LKO", "UDR", "JDH", "GOI", "GOX", "PNQ", "COK")}
                        result = FlightAdapter(self._serp(), airport_timezones=zones).search_leg(p, a, b, leg=leg)
                        eligible = eligible_transport(result.items, p)
                        if result.items and not eligible:
                            result.warnings.append("No normalized flight option verified the requested class/total-price filters; this does not prove no flights operate.")
                        if len(eligible) > 4:
                            result.warnings.append("Only the first four normalized flight options per leg enter the ranking shortlist.")
                        result.items = eligible[:4]
                        return result
                    result = self._search("serpapi", mode + "_" + leg, search)
                offers.extend(result.items); warnings.extend(result.warnings); skipped.extend(result.skipped_records)
        return SearchResult(offers, warnings, {}, skipped)

    def hotels(self, p):
        def search():
            self._check_destination(p)
            return SerpApiAdapter(self._serp()).hotels(p)
        return self._search("serpapi", "hotels", search)

    def places(self, p):
        def search():
            self._check_destination(p)
            return SerpApiAdapter(self._serp()).places(p)
        return self._search("serpapi", "places", search)

    def _check_destination(self, p):
        destination = self.bindings.destination_airport or self.bindings.destination_station
        if not p.destination or not destination or p.destination.casefold() != destination.city.casefold():
            raise ValueError("Destination selection must be resolved before retrieval")

    def tools(self):
        """Validated LangChain tools; the graph calls invoke(), not an LLM tool loop."""
        def transport(**values):
            self.tool_calls.append("transport")
            return self.transport(TripPreferences(**values))
        def hotels(**values):
            self.tool_calls.append("hotels")
            return self.hotels(TripPreferences(**values))
        def places(**values):
            self.tool_calls.append("places")
            return self.places(TripPreferences(**values))
        return tuple(StructuredTool.from_function(fn, name=name, description=description, args_schema=TripPreferences)
            for fn, name, description in ((transport, "search_transport", "Retrieve selected train/flight legs with explicit bindings."),
                (hotels, "search_hotels", "Retrieve hotel quotes for validated stay dates and preferences."),
                (places, "search_places", "Retrieve place candidates and known hours for the destination.")))

    def audit(self):
        return {"serpapi": list(self.serp_http.audit) if self.serp_http else [],
                "railradar": list(self.rail_http.audit) if self.rail_http else []}
