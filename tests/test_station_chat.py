"""Exercise open-ended station selection with simulated provider responses."""
from datetime import datetime
from copy import deepcopy

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.llm import ModelCallError
from backend.providers.rail_http import RailRadarHttp
from test_connected import offline
from test_route_selection import DATES, RouteResponses, bind_mock_http


class StationResponses(RouteResponses):
    def __init__(self, decisions):
        super().__init__(decisions)
        self.routes = {}

    def __call__(self, request):
        if request.url.host != "api.railradar.in":
            return super().__call__(request)
        self.calls.append(request)
        path = request.url.path
        if path == "/v1/lookup/search/stations":
            q = request.url.params["q"]
            if q == "Quota Town":
                return httpx.Response(429, json={"success": False, "error": {"message": "test-rail-secret"}})
            rows = {
                "CNB": [("CNB", "Kanpur Central", None), ("CNBX", "Unrelated prefix match", None)],
                "Kanpur Central": [("CNB", "Kanpur Central", None)],
                "Lucknow": [("LKO", "Lucknow", "Lucknow"), ("LJN", "Lucknow Junction", "Lucknow")],
                "LKO": [("LKO", "Lucknow", "Lucknow")],
            }.get(q, [])
            data = [dict(code=code, name=name, city=city, isActive=True) for code, name, city in rows]
        elif "/between/" in path:
            a, b = path.rsplit("/", 2)[-2:]
            outward = request.url.params["date"] == DATES["departure_date"]
            number = "99921" if outward else "99922"
            self.routes[number] = (a, b)
            data = {"from": {"code": a}, "to": {"code": b}, "trains": [{
                "train": {"number": number, "name": "Invented station test service"},
                "from": {"code": a, "day": 1, "departure": "09:00" if outward else "16:00"},
                "to": {"code": b, "day": 1, "arrival": "11:30" if outward else "18:30"},
                "duration": 150,
            }]}
        else:
            number = path.rsplit("/", 1)[-1]
            a, b = self.routes[number]
            data = {"train": {"number": number, "name": "Invented station test service",
                              "availableClasses": ["CC"], "isPrsBookable": True},
                    "route": [{"station": {"code": code}} for code in (a, b)]}
        return httpx.Response(200, json={"success": True, "data": data})


def chat_client(monkeypatch, http):
    bind_mock_http(monkeypatch, http)
    monkeypatch.setattr(main, "RailRadarHttp", lambda key, *, max_requests, http_client:
                        RailRadarHttp(key, max_requests=max_requests, http_client=http))
    return TestClient(main.app)


def send(api, message, session_id=None):
    result = api.post("/chat", json={"message": message, "session_id": session_id})
    assert result.status_code == 200, result.text
    return result.json()


def station_codes(reply):
    return [(leg["departure_station"], leg["arrival_station"]) for leg in reply["plan"]["transport"]]


def lookup_queries(calls):
    return [r.url.params["q"] for r in calls if r.url.path == "/v1/lookup/search/stations"]


def trip_fields(origin, destination):
    return DATES | {"origin": origin, "destination": destination, "adults": 2,
                    "transport_mode": "train", "train_class": "CC"}


def test_ambiguous_city_pauses_and_confirmed_station_drives_both_legs(monkeypatch):
    handler = StationResponses([
        ("plan", trip_fields("CNB", "Lucknow")),
        ("update", {"destination": "LKO"}),
        ("update", {"nightly_max": "3500"}),
    ])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = chat_client(monkeypatch, http)
        waiting = send(api, "Plan a CC train round trip for 2 from CNB to Lucknow, Feb 10 to 13, 2027.")
        session = waiting["session_id"]
        assert waiting["plan"] is None and all(s in waiting["reply"] for s in ("LKO", "LJN"))
        assert lookup_queries(handler.calls) == ["CNB", "Lucknow"]
        assert len(handler.calls) == 3  # one Supervisor call and two lookups, no train or hotel search
        assert send(api, "WRONG", session)["reply"] == waiting["reply"]
        assert len(handler.calls) == 3
        chosen = send(api, "Use LJN", session)
        assert station_codes(chosen) == [("CNB", "LJN"), ("LJN", "CNB")]
        assert chosen["plan"]["trip"]["origin"] == "Kanpur Central"
        assert chosen["plan"]["days"]
        assert handler.roles.count("SupervisorDecision") == 1
        assert lookup_queries(handler.calls) == ["CNB", "Lucknow"]
        queries = [r.url.params["q"] for r in handler.calls if r.url.host == "serpapi.com"]
        assert len(queries) == 2 and all(q.endswith("in Lucknow") for q in queries)
        before = len(handler.calls)
        revised = send(api, "Use LKO as my destination station instead.", session)
        assert station_codes(revised) == [("CNB", "LKO"), ("LKO", "CNB")]
        assert lookup_queries(handler.calls[before:]) == ["LKO"]
        assert not any(r.url.host == "serpapi.com" for r in handler.calls[before:])
        before = len(handler.calls)
        updated = send(api, "Find a hotel under 3500 rupees per night.", session)
        assert station_codes(updated) == station_codes(revised)
        assert not any(r.url.host == "api.railradar.in" for r in handler.calls[before:])


def test_exact_station_name_and_code_need_no_second_turn(monkeypatch):
    handler = StationResponses([("plan", trip_fields("Kanpur Central", "LKO"))])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        reply = send(chat_client(monkeypatch, http),
                     "Plan a CC train round trip from Kanpur Central to LKO, Feb 10 to 13, 2027, two adults.")
    assert station_codes(reply) == [("CNB", "LKO"), ("LKO", "CNB")]
    assert lookup_queries(handler.calls) == ["Kanpur Central", "LKO"]


def test_complete_round_trip_reaches_station_choice_without_the_supervisor(monkeypatch):
    handler = StationResponses([])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = chat_client(monkeypatch, http)
        waiting = send(api, "Plan a round trip from Kanpur Central to Lucknow by CC train for 2 adults. "
                            "Depart on 10 February 2027 and return on 13 February 2027.")
        assert waiting["plan"] is None and "Confirm the destination station" in waiting["reply"]
        assert lookup_queries(handler.calls) == ["Kanpur Central", "Lucknow"]
        complete = send(api, "LJN", waiting["session_id"])
    assert station_codes(complete) == [("CNB", "LJN"), ("LJN", "CNB")]
    assert complete["plan"]["days"]
    assert "SupervisorDecision" not in handler.roles


def test_original_december_request_can_list_stations_even_if_model_fails(monkeypatch):
    class NovemberClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 19, 12, tzinfo=tz)

    def unavailable(*args, **kwargs):
        raise ModelCallError("Model unavailable.")

    handler = StationResponses([])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = chat_client(monkeypatch, http)
        monkeypatch.setattr("backend.chat.datetime", NovemberClock)
        monkeypatch.setattr(main, "create_model", unavailable)
        waiting = send(api, "Plan a round trip from Kanpur Central to Lucknow by CC train for 2 adults. "
                            "Depart on 4 December 2026 and return on 7 December 2026.")
    assert waiting["plan"] is None and "Confirm the destination station" in waiting["reply"]
    assert lookup_queries(handler.calls) == ["Kanpur Central", "Lucknow"]
    assert len(handler.calls) == 2


@pytest.mark.parametrize("message", [
    "Plan a round trip from Kanpur Central to Lucknow and Agra by CC train for 2 adults. "
    "Depart on 10 February 2027 and return on 13 February 2027.",
    "Book and pay for a round trip from Kanpur Central to Lucknow by CC train for 2 adults.",
])
def test_empty_non_planning_decision_does_not_start_an_unsupported_search(monkeypatch, message):
    handler = StationResponses([("unsupported", {})])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        reply = send(chat_client(monkeypatch, http), message)
    assert reply["plan"] is None and "one destination" in reply["reply"]
    assert [r.url.host for r in handler.calls] == ["api.groq.com"]


@pytest.mark.parametrize(("preferred_type", "matching_class", "checked"), [
    ("Vande Bharat Express", True, ["99921", "01415"]),
    (None, True, ["01415", "05094", "99921"]),
    (None, False, ["01415", "05094", "99921"]),
])
def test_browser_checks_an_extra_outbound_candidate_only_when_needed(
    monkeypatch, preferred_type, matching_class, checked,
):
    class ShortlistResponses(StationResponses):
        def __call__(self, request):
            response = super().__call__(request)
            if request.url.host != "api.railradar.in":
                return response
            path = request.url.path
            body = response.json()
            if path.endswith("/between/CNB/LKO"):
                rows = body["data"]["trains"]
                rows[0]["train"]["type"] = preferred_type
                for number, arrive, duration in [("01415", "10:05", 65), ("05094", "10:35", 95), ("99923", "12:00", 180)]:
                    train = deepcopy(rows[0])
                    train["train"] = {"number": number, "name": "Invented shortlist service", "type": "Mail/Express"}
                    train["to"]["arrival"], train["duration"] = arrive, duration
                    rows.append(train)
                    self.routes[number] = self.routes["99921"]
            elif path.rsplit("/", 1)[-1] in ("01415", "05094", "99923") or (
                path.endswith("/99921") and not matching_class
            ):
                body["data"]["train"]["availableClasses"] = ["SL"]
            return httpx.Response(200, json=body)

    handler = ShortlistResponses([])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = chat_client(monkeypatch, http)
        reply = send(api, "Plan a round trip from CNB to LKO by CC train for 2 adults. "
                          "Depart on 10 February 2027 and return on 13 February 2027.")
    paths = [r.url.path for r in handler.calls if r.url.host == "api.railradar.in"]
    assert paths == ["/v1/lookup/search/stations", "/v1/lookup/search/stations", "/v1/trains/between/CNB/LKO",
                     *("/v1/trains/" + code for code in checked), "/v1/trains/between/LKO/CNB", "/v1/trains/99922"]
    trip = reply["plan"]
    if matching_class:
        assert trip["days"] and [leg["train_number"] for leg in trip["transport"]] == ["99921", "99922"]
        assert all(leg["travel_class"] == "CC" and leg["price"]["pricing_mode"] == "demo" for leg in trip["transport"])
    else:
        assert not trip["days"] and [leg["train_number"] for leg in trip["transport"]] == ["99922"]
        assert any("No usable outbound CC option" in w and "3 of 4" in w for w in trip["warnings"])


@pytest.mark.parametrize(("origin", "text"), [
    ("No Match", "No railway station matched"),
    ("Quota Town", "Station lookup is unavailable"),
])
def test_lookup_failure_stops_before_train_hotel_and_maps(monkeypatch, origin, text):
    handler = StationResponses([("plan", trip_fields(origin, "LKO"))])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        reply = send(chat_client(monkeypatch, http), "Plan a train trip to LKO.")
    assert reply["plan"] is None and text in reply["reply"]
    assert "test-rail-secret" not in reply["reply"]
    assert len(handler.calls) == 2 and lookup_queries(handler.calls) == [origin]
