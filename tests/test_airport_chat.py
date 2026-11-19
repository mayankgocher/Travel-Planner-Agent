"""Offline browser API tests for airport resolution and comparisons."""
import httpx
import pytest

from backend import main
from backend.providers.http import SerpApiHttp
from test_connected import offline
from test_route_selection import DATES
from test_station_chat import StationResponses, chat_client, lookup_queries, send


def airport_city(city, *airports):
    return {"name": city, "type": "city", "airports": [{"id": code, "name": name} for code, name in airports]}


MUMBAI = airport_city("Mumbai, Maharashtra", ("BOM", "Mumbai Test Airport"), ("NMI", "Navi Mumbai Test Airport"))
HYDERABAD = airport_city("Hyderabad, Telangana, India", ("HYD", "Hyderabad Test Airport"))
LUCKNOW = airport_city("Lucknow, India", ("LKO", "Lucknow Test Airport"))


class AirportResponses(StationResponses):
    def __call__(self, request):
        if request.url.params.get("engine") != "google_flights_autocomplete":
            return super().__call__(request)
        self.calls.append(request)
        query = request.url.params["q"]
        assert request.url.params["gl"] == "in" and request.url.params["exclude_regions"] == "true"
        if query == "Outage":
            return httpx.Response(429, json={"error": "test-serp-secret"})
        options = {"Mumbai": [MUMBAI], "BOM": [MUMBAI], "NMI": [MUMBAI], "Hyderabad": [HYDERABAD],
                   "Hyderabad Test Airport": [HYDERABAD], "LKO": [LUCKNOW], "Lucknow": [LUCKNOW],
                   "London": [airport_city("London, United Kingdom", ("LHR", "Heathrow"))]}
        return httpx.Response(200, json={"suggestions": options.get(query, [])})


def open_client(monkeypatch, http):
    api = chat_client(monkeypatch, http)
    monkeypatch.setattr(main, "SerpApiHttp", lambda key, *, max_requests, http_client:
                        SerpApiHttp(key, max_requests=max_requests, http_client=http))
    return api


def flight_request(origin, destination):
    return (f"Plan a round trip from {origin} to {destination} by Economy flight for 2 adults. "
            "Depart on 10 February 2027 and return on 13 February 2027.")


def airport_queries(calls):
    return [r.url.params["q"] for r in calls if r.url.params.get("engine") == "google_flights_autocomplete"]


def flight_routes(calls):
    return [(r.url.params["departure_id"], r.url.params["arrival_id"], r.url.params["outbound_date"])
            for r in calls if r.url.params.get("engine") == "google_flights"]


def test_airport_choice_pauses_search_and_airport_change_replans_flights(monkeypatch):
    handler = AirportResponses([("update", {"origin": "BOM"})])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = open_client(monkeypatch, http)
        waiting = send(api, flight_request("Mumbai", "Hyderabad"))
        session = waiting["session_id"]
        assert waiting["plan"] is None and "Confirm the departure airport" in waiting["reply"]
        assert "BOM" in waiting["reply"] and "NMI" in waiting["reply"]
        assert len(handler.calls) == 1 and airport_queries(handler.calls) == ["Mumbai"]
        assert send(api, "LHR", session)["reply"] == waiting["reply"]
        assert len(handler.calls) == 1

        selected = send(api, "Use NMI", session)["plan"]
        assert selected["days"] and [leg["mode"] for leg in selected["transport"]] == ["flight", "flight"]
        assert airport_queries(handler.calls) == ["Mumbai", "Hyderabad"]
        assert "SupervisorDecision" not in handler.roles
        assert flight_routes(handler.calls) == [("NMI", "HYD", DATES["departure_date"]),
                                                ("HYD", "NMI", DATES["return_date"])]
        hotel = next(r for r in handler.calls if r.url.params.get("engine") == "google_hotels")
        assert hotel.url.params["q"] == "Hotels in Hyderabad"

        before = len(handler.calls)
        revised = send(api, "Use BOM for departure instead.", session)["plan"]
        assert revised["days"] and revised["trip"]["origin"] == "Mumbai"
        assert flight_routes(handler.calls[before:]) == [("BOM", "HYD", DATES["departure_date"]),
                                                        ("HYD", "BOM", DATES["return_date"])]
        assert not any(r.url.params.get("engine") == "google_hotels" for r in handler.calls[before:])
        assert not any(r.url.host == "api.railradar.in" for r in handler.calls)


def test_flight_comparison_resolves_airport_and_rail_station_before_retrieval(monkeypatch):
    fields = DATES | {"origin": "Delhi", "destination": "Lucknow", "adults": 2, "transport_mode": "compare",
                     "train_class": "CC", "flight_class": "Economy"}
    handler = AirportResponses([("plan", fields)])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = open_client(monkeypatch, http)
        waiting = send(api, "Compare train and flight from Delhi to Lucknow.")
        assert "Confirm the destination station" in waiting["reply"] and waiting["plan"] is None
        assert airport_queries(handler.calls) == ["Lucknow"] and lookup_queries(handler.calls) == ["Lucknow"]
        assert not flight_routes(handler.calls) and len(handler.calls) == 3
        result = send(api, "LJN", waiting["session_id"])["plan"]
    assert result["days"] and result["trip"]["destination"] == "Lucknow"
    assert airport_queries(handler.calls) == ["Lucknow"] and lookup_queries(handler.calls) == ["Lucknow"]
    assert flight_routes(handler.calls) == [("DEL", "LKO", DATES["departure_date"]),
                                            ("LKO", "DEL", DATES["return_date"])]
    assert [r.url.path for r in handler.calls if "/between/" in r.url.path] == [
        "/v1/trains/between/NDLS/LJN", "/v1/trains/between/LJN/NDLS"]


@pytest.mark.parametrize(("name", "notice"), [
    ("London", "No Indian airport match verified"),
    ("Typo Town", "No Indian airport match verified"),
    ("Outage", "Airport lookup is unavailable"),
])
def test_foreign_missing_or_unavailable_airport_stops_before_flight_search(monkeypatch, name, notice):
    handler = AirportResponses([])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        reply = send(open_client(monkeypatch, http), flight_request("Delhi", name))
    assert reply["plan"] is None and notice in reply["reply"]
    assert "test-serp-secret" not in reply["reply"]
    assert airport_queries(handler.calls) == [name] and len(handler.calls) == 1
