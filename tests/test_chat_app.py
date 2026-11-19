"""Exercise clarification, selective changes, and offline export without live calls."""
import json
from collections import OrderedDict
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend import main
from frontend.plan_export import plan_markdown
from test_connected import P, Responses, offline
from test_plan_app import patch_providers

ROOT = Path(__file__).resolve().parents[1]


def test_browser_chat_clarifies_and_reuses_trains_on_hotel_change(monkeypatch):
    # Use the real API/provider adapters and replace only external HTTP responses.
    monkeypatch.setattr(main, "chats", OrderedDict())
    base = Responses()
    decisions = iter([
        ("plan", {"origin": "Delhi", "destination": "Jaipur", "adults": 2,
                  "transport_mode": "train", "train_class": "CC"}, "What dates?", None),
        ("update", {k: P[k] for k in ("departure_date", "return_date", "hotel_class", "nightly_max")}, None, None),
        ("update", {}, "What is your new nightly cap?", None),
        ("update", {"nightly_max": "3200"}, None, None),
        ("question", {}, None, "Your current nightly cap is ₹3,200."),
        ("update", {"destination": "Mumbai", "transport_mode": "flight"}, None, None),
        ("update", {"nightly_max": "2400"}, None, None),  # No eligible hotel.
    ])
    contexts = []

    def mock_wire(request):
        response = base(request)
        if request.url.host == "api.groq.com":
            wire = json.loads(request.content)
            if wire["response_format"]["json_schema"]["name"] == "SupervisorDecision":
                contexts.append(json.loads(wire["messages"][0]["content"].split("\nContext: ", 1)[1]))
                intent, updates, question, answer = next(decisions)
                body = response.json()
                body["choices"][0]["message"]["content"] = json.dumps({
                    "intent": intent, "updates": [{"field": k, "value": v} for k, v in updates.items()],
                    "clarification_question": question, "answer": answer,
                })
                return httpx.Response(200, json=body)
        return response

    with httpx.Client(transport=httpx.MockTransport(mock_wire), trust_env=False) as http:
        patch_providers(monkeypatch, http)
        api = TestClient(main.app)
        post = httpx.Client.post
        replies = []

        def browser_post(self, url, **kwargs):
            if url == "http://127.0.0.1:8000/chat":
                response = api.request("POST", "/chat", **kwargs)
                assert response.status_code == 200, response.text
                replies.append(response.json())
                return response
            return post(self, url, **kwargs)

        monkeypatch.setattr(httpx.Client, "post", browser_post)
        screen = AppTest.from_file(str(ROOT / "frontend/app.py")).run()
        assert not screen.exception and not base.calls

        def send(message):
            screen.chat_input[0].set_value(message).run(timeout=20)
            assert not screen.exception
            return replies[-1]

        def travel_hosts():
            return [str(call.url.params.get("engine") or call.url.host) for call in base.calls
                    if call.url.host != "api.groq.com"]

        first = send("I want to travel from Delhi to Jaipur by CC train with another adult.")
        assert first["reply"] == "What dates?" and first["plan"] is None and not travel_hosts()
        second = send("February 10 to 13 2027. 3-star under ₹4,000.")
        assert second["session_id"] == first["session_id"] and second["plan"]["days"]
        assert contexts[1]["pending_question"] == "What dates?"
        before = len(travel_hosts())
        assert send("Keep the trains but find a cheaper hotel.")["reply"] == "What is your new nightly cap?"
        assert len(travel_hosts()) == before
        revised = send("₹3,200 per night.")
        assert revised["plan"]["transport"] == second["plan"]["transport"]
        assert travel_hosts()[before:] == ["google_hotels"]  # No rail or Maps refresh.
        assert any("Invented museum" in item.value for item in screen.markdown)
        assert screen.get("download_button")
        before = len(travel_hosts())
        assert send("What is my nightly cap?")["reply"] == "Your current nightly cap is ₹3,200."
        assert "Choose a supported city" in send("Fly to Mumbai instead.")["reply"]
        assert len(travel_hosts()) == before
        rejected = send("Under ₹2,400.")
        assert rejected["plan"] == revised["plan"]
        assert "previous plan" in rejected["reply"] and rejected["turn_warnings"]
        assert travel_hosts()[before:] == ["google_hotels"]
        calls = len(base.calls)
        screen.run()
        assert len(base.calls) == calls


def test_unknown_chat_does_not_load_keys(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unknown chat must not touch provider configuration")
    monkeypatch.setattr(main, "Settings", forbidden)
    response = TestClient(main.app).post("/chat", json={"message": "continue", "session_id": str(uuid4())})
    assert response.status_code == 404


def test_export_keeps_demo_and_unverified_disclosures():
    sample = json.loads((ROOT / "frontend/jaipur_sample.json").read_text(encoding="utf-8"))
    text = plan_markdown(sample)
    assert "Saved snapshot" in text and "Budget fit unverified" in text
    assert text.count("**Demo fare:**") == 2
    assert "₹7,588" in text and "₹2,529" in text
    assert "Opening hours unverified" in text
    assert "Offer sources" in text
    partial = sample | {"snapshot_date": None, "status": "partial_results", "days": []}
    assert "No validated itinerary available" in plan_markdown(partial)
