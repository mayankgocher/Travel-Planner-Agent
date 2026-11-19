"""Check selected routes through FastAPI with intercepted provider HTTP."""
from collections import OrderedDict
from datetime import date
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend import main
from backend.llm import create_model
from backend.providers.http import SerpApiHttp
from backend.providers.rail_http import RailRadarHttp
from backend.providers.session import TravelProviderSession
from test_connected import P, Responses, config, offline

ROOT = Path(__file__).resolve().parents[1]
DATES = {key: P[key] for key in ("departure_date", "return_date")}


class RouteResponses(Responses):
    def __init__(self, decisions=()):
        super().__init__()
        self.decisions = iter(decisions)

    def __call__(self, request):
        url = request.url
        last = url.path.rsplit("/", 1)[-1]
        if url.host == "api.railradar.in" and ("SBC" in url.path or last in ("99901", "99902")):
            self.calls.append(request)
            outward = url.path.endswith("/SBC/MYS") or last == "99901"
            a, b = ("SBC", "MYS") if outward else ("MYS", "SBC")
            number = "99901" if outward else "99902"
            train = {"number": number, "name": "Invented Karnataka test service",
                     "availableClasses": ["CC"], "isPrsBookable": True}
            if "/between/" in url.path:
                data = {"from": {"code": a}, "to": {"code": b}, "trains": [
                    {"train": train, "from": {"code": a, "day": 1, "departure": "09:00" if outward else "16:00"},
                     "to": {"code": b, "day": 1, "arrival": "11:30" if outward else "18:30"},
                     "duration": 150},
                ]}
            else:
                data = {"train": train, "route": [{"station": {"code": code}} for code in (a, b)]}
            return httpx.Response(200, json={"success": True, "data": data})

        response = super().__call__(request)
        body = response.json()
        if url.host == "serpapi.com" and url.params.get("engine") == "google_maps" and "Mysuru" in url.params["q"]:
            row = body["local_results"][0]
            row.update(place_id="mysuru-test", title="Invented Mysuru museum",
                       gps_coordinates={"latitude": 12.30, "longitude": 76.65})
        elif url.host == "serpapi.com" and url.params.get("engine") == "google_flights":
            day = url.params["outbound_date"]
            leg = body["other_flights"][0]["flights"][0]
            outward = day == DATES["departure_date"]
            leg["departure_airport"]["time"] = day + (" 08:00" if outward else " 16:00")
            leg["arrival_airport"]["time"] = day + (" 10:00" if outward else " 18:00")
        elif url.host == "api.groq.com" and self.roles[-1] == "SupervisorDecision":
            intent, fields, *question = next(self.decisions)
            body["choices"][0]["message"]["content"] = json.dumps({
                "intent": intent, "updates": [{"field": key, "value": value} for key, value in fields.items()],
                "clarification_question": question[0] if question else None, "answer": None,
            })
        elif url.host == "api.groq.com" and self.roles[-1] == "Schedule":
            wire = json.loads(request.content)
            context = json.loads(wire["messages"][1]["content"])
            answer = json.loads(body["choices"][0]["message"]["content"])
            answer["activities"][0]["place_id"] = context["places"][0]["id"]
            body["choices"][0]["message"]["content"] = json.dumps(answer)
        return httpx.Response(200, json=body)


def bind_mock_http(monkeypatch, http):
    settings = config()
    monkeypatch.setattr(main, "chats", OrderedDict())
    monkeypatch.setattr(main, "Settings", lambda **kwargs: settings)
    monkeypatch.setattr(main, "create_model", lambda *args, **kwargs: create_model(settings, http_client=http))
    monkeypatch.setattr(main, "TravelProviderSession", lambda s, bindings, **kwargs: TravelProviderSession(
        s, bindings, serp_http=SerpApiHttp("test-serp", http_client=http, max_requests=4),
        rail_http=RailRadarHttp("test-rail", http_client=http, max_requests=8), **kwargs))


def assert_mysuru_trip(result, requests):
    assert (result["trip"]["origin"], result["trip"]["destination"]) == ("Bengaluru", "Mysuru")
    assert [(leg["departure_station"], leg["arrival_station"]) for leg in result["transport"]] == [
        ("SBC", "MYS"), ("MYS", "SBC")]
    assert all(leg["price"]["pricing_mode"] == "demo" for leg in result["transport"])
    assert result["hotel"] and any(day["activities"] for day in result["days"])
    between = [request for request in requests if "/between/" in request.url.path]
    assert [(r.url.path.rsplit("/between/", 1)[1], r.url.params["date"]) for r in between] == [
        ("SBC/MYS", DATES["departure_date"]), ("MYS/SBC", DATES["return_date"])]
    serp = [r.url.params for r in requests if r.url.host == "serpapi.com"]
    assert [q["engine"] for q in serp] == ["google_hotels", "google_maps"]
    assert all(q["q"].endswith("in Mysuru") for q in serp)


def test_form_selects_cities_and_sends_provider_requests_for_that_route(monkeypatch):
    handler = RouteResponses()
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        bind_mock_http(monkeypatch, http)
        api = TestClient(main.app)
        result = []

        def browser_post(self, url, **kwargs):
            assert url == "http://127.0.0.1:8000/plan"
            response = api.request("POST", "/plan", **kwargs)
            assert response.status_code == 200, response.text
            result.append(response.json())
            return response

        monkeypatch.setattr(httpx.Client, "post", browser_post)
        screen = AppTest.from_file(str(ROOT / "frontend/app.py")).run()
        next(w for w in screen.selectbox if w.label == "Departure city").select("Bengaluru").run()
        next(w for w in screen.selectbox if w.label == "Destination city").select("Mysuru").run()
        assert next(w for w in screen.selectbox if w.label == "Transport").options == ["Train"]
        assert not handler.calls
        for field, day in zip(screen.date_input, DATES.values()):
            field.set_value(date.fromisoformat(day))
        next(w for w in screen.button if w.label == "Generate plan").click().run(timeout=20)
        assert not screen.exception and not screen.error
    assert len(result) == 1
    assert_mysuru_trip(result[0], handler.calls)


def test_chat_asks_for_cities_and_replaces_old_searches_on_route_change(monkeypatch):
    details = DATES | {"adults": 2, "transport_mode": "train", "train_class": "CC"}
    handler = RouteResponses([
        ("plan", details),
        ("update", {"origin": "New Delhi", "destination": "Jaipur"}),
        ("update", {"origin": "Bangalore", "destination": "Mysore"}),
    ])
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        bind_mock_http(monkeypatch, http)
        api = TestClient(main.app)

        def send(message, session_id=None):
            response = api.post("/chat", json={"message": message, "session_id": session_id})
            assert response.status_code == 200, response.text
            return response.json()

        first = send("A CC train round trip for 2 adults, February 10 to 13, 2027.")
        assert first["plan"] is None and "departure city, destination city" in first["reply"]
        assert [r.url.host for r in handler.calls] == ["api.groq.com"]
        second = send("New Delhi to Jaipur.", first["session_id"])
        assert second["plan"]["days"] and second["plan"]["trip"]["origin"] == "Delhi"
        before_change = len(handler.calls)
        third = send("Use Bangalore to Mysore instead.", first["session_id"])
    assert_mysuru_trip(third["plan"], handler.calls[before_change:])
    names = [a["name"] for day in third["plan"]["days"] for a in day["activities"]]
    assert names == ["Invented Mysuru museum"]


@pytest.mark.parametrize(("rail_preference", "model_question", "ready"), [
    ("by CC train", None, True),
    ("by cc train", "Which train class would you prefer?", True),
    ("by CC train", "What is your maximum nightly hotel price?", False),
    ("by train", None, False),
    ("by CC train or by 3A train", None, False),
    ("not by CC train", None, False),
    ("but don't travel by CC train", None, False),
])
def test_chat_uses_an_explicit_class_without_guessing(rail_preference, model_question, ready, monkeypatch):
    fields = DATES | {"origin": "Bengaluru", "destination": "Mysuru", "adults": 2, "transport_mode": "train"}
    handler = RouteResponses([("plan", fields, model_question)])  # Model omitted train_class.
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        bind_mock_http(monkeypatch, http)
        response = TestClient(main.app).post("/chat", json={"message": (
            f"Plan a Bengaluru to Mysuru round trip {rail_preference} for 2 adults. "
            "Depart on 10 February 2027 and return on 13 February 2027."
        )})
    assert response.status_code == 200, response.text
    reply = response.json()
    if ready:
        assert reply["plan"], reply["reply"]
        assert_mysuru_trip(reply["plan"], handler.calls)
        assert all(leg["travel_class"] == "CC" for leg in reply["plan"]["transport"])
        assert handler.roles.count("SupervisorDecision") == 1
    else:
        assert reply["plan"] is None
        assert reply["reply"] == (model_question or "Please provide: train class (e.g. CC).")
        assert [r.url.host for r in handler.calls] == ["api.groq.com"]


def test_flight_route_uses_bengaluru_airport_without_a_rail_search(monkeypatch):
    handler = RouteResponses()
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        bind_mock_http(monkeypatch, http)
        response = TestClient(main.app).post("/plan", json=DATES | {
            "origin": "Bangalore", "destination": "Delhi", "transport_mode": "flight",
        })
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["days"] and plan["trip"]["origin"] == "Bengaluru"
    assert [leg["mode"] for leg in plan["transport"]] == ["flight", "flight"]
    assert not any(call.url.host == "api.railradar.in" for call in handler.calls)
    queries = [call.url.params for call in handler.calls if call.url.params.get("engine") == "google_flights"]
    assert [(q["departure_id"], q["arrival_id"]) for q in queries] == [("BLR", "DEL"), ("DEL", "BLR")]


@pytest.mark.parametrize(("route", "message"), [
    ({"origin": "Mumbai", "destination": "Jaipur"}, "Choose a supported city"),
    ({"origin": "Mysore", "destination": "Mysuru"}, "Choose different cities"),
    ({"origin": "Bengaluru", "destination": "Mysuru", "transport_mode": "flight"}, "choose train"),
    ({"origin": "Mysuru", "destination": "Bengaluru", "transport_mode": "compare"}, "choose train"),
])
def test_invalid_form_route_loads_no_keys(monkeypatch, route, message):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid route must not load keys")
    monkeypatch.setattr(main, "Settings", forbidden)
    response = TestClient(main.app).post("/plan", json=DATES | route)
    assert response.status_code == 422 and message in response.text
