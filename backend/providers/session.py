"""Real retrieval callbacks. Python owns provider order, limits and failure handling."""
from contextlib import ExitStack
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from langchain_core.tools import StructuredTool

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
    origin_airport: AirportLocation
    destination_airport: AirportLocation
    origin_station: StationBinding
    destination_station: StationBinding
    destination_timezone: str

    def __post_init__(self):
        ZoneInfo(self.destination_timezone)
        if (self.origin_airport.city.casefold() != self.origin_station.city.casefold() or
                self.destination_airport.city.casefold() != self.destination_station.city.casefold()):
            raise ValueError("Airport and station bindings must describe the same selected cities")


def jaipur_probe_bindings():
    return JourneyBindings(AirportLocation("DEL", "Delhi", "Asia/Kolkata"), AirportLocation("JAI", "Jaipur", "Asia/Kolkata"),
                           StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur"), "Asia/Kolkata")


class TravelProviderSession:
    """One execution's clients/audit, not a search cache or persistent trip state."""
    def __init__(self, settings, bindings, *, serp_http=None, rail_http=None):
        self.settings, self.bindings = settings, bindings
        self.serp_http, self.rail_http = serp_http, rail_http
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
            # Two between searches, <=4 timetables, and <=2 fares only in live-price mode.
            limit = 6 if self.settings.train_fare_mode == "mock" else 8
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
                    if leg == "return": a, b = b, a
                    def search(a=a, b=b, leg=leg):
                        adapter = RailRadarAdapter(self._rail(), fare_mode=self.settings.train_fare_mode)
                        try:
                            return adapter.search_leg(p, a, b, leg=leg)
                        except ProviderError as exc:
                            # Keep completed schedule/class evidence even if a live fare request fails.
                            if adapter.last_result:
                                offers.extend(adapter.last_result.items)
                                warnings.extend(adapter.last_result.warnings)
                            raise exc
                    result = self._search("railradar", mode + "_" + leg, search)
                else:
                    a, b = self.bindings.origin_airport, self.bindings.destination_airport
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
        if not p.destination or p.destination.casefold() != self.bindings.destination_station.city.casefold():
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
