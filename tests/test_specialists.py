"""All four real LLM classes run through intercepted ChatGroq HTTP requests."""
import json
import os
import socket

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend import specialist_fixtures as fixtures
from backend.agents.hotel import HotelAgent
from backend.agents.itinerary import ItineraryAgent
from backend.agents.supervisor import Supervisor, SupervisorDecision, SupervisorTurn
from backend.agents.transportation import TransportationAgent
from backend.config import Settings
from backend.graph.builder import build_workflow
from backend.llm import create_model
from backend.schemas import TripPreferences
from backend.services.offer_filters import eligible_hotels, eligible_transport
from backend.services.scheduling import Schedule, validate_schedule

PREFERENCES = dict(origin="Delhi", destination="Jaipur", departure_date="2027-02-10", return_date="2027-02-14",
                   adults=2, transport_mode="train", hotel_class=3, nightly_min="2000", nightly_max="4000",
                   guest_rating_min=4, budget_total="25000", currency="INR", interests=["history"])


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    for name in list(os.environ):
        if name.lower().endswith("_proxy"):
            monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Specialist tests must not contact any service")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def run_agents(fault=None):
    calls, schedule_calls = [], []
    def handle(request):
        wire = json.loads(request.content)
        name = wire["response_format"]["json_schema"]["name"]
        calls.append(name)
        assert wire["response_format"]["json_schema"]["strict"] and "tools" not in wire
        if name == "SupervisorDecision":
            answer = {"intent": "plan", "updates": [{"field": k, "value": v} for k, v in PREFERENCES.items()],
                      "clarification_question": None, "answer": None}
        elif name == "OfferRanking":
            candidates = json.loads(wire["messages"][1]["content"])["candidates"]
            answer = {"ranked_ids": [o["id"] for o in candidates], "reason": "Fixture candidates match the stated preferences."}
            if fault == "unknown_rank":
                answer["ranked_ids"] = ["INVENTED-ID"]
        elif name == "Schedule":
            schedule_calls.append(1)
            bad = fault == "always_bad" or (fault == "repair" and len(schedule_calls) == 1)
            answer = {"activities": [{"place_id": "FIXTURE-P1", "date": "2027-02-10",
                                      "start": "08:00" if bad else "15:00", "end": "09:00" if bad else "16:00"}],
                      "notes": ["Synthetic data. Transfer time is an estimate."]}
        else:
            raise AssertionError("Unexpected model request")
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 1,
            "model": "openai/gpt-oss-120b", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        model = create_model(Settings(_env_file=None, groq_model="openai/gpt-oss-120b", groq_api_key="fixture-secret"), http_client=client)
        graph = build_workflow(TransportationAgent(model, fixtures.transport), HotelAgent(model, fixtures.hotels),
                               ItineraryAgent(model, fixtures.places), InMemorySaver(), Supervisor(model))
        result = graph.invoke({"user_message": "Fixture test request; data are synthetic."},
                              {"configurable": {"thread_id": "all-agents"}, "recursion_limit": 30})
    return result, calls


def test_four_agents_create_grounded_draft_and_python_subtotal():
    result, calls = run_agents()
    assert calls == ["SupervisorDecision", "OfferRanking", "OfferRanking", "Schedule"]
    assert result["status"] == "draft_ready" and result["itinerary"]["synthetic"]
    assert result["costs"]["complete_subtotal"] == "16900"
    assert result["costs"]["budget_status"] == "within_budget"
    assert result["agent_usage"]["itinerary"]["total_tokens"] == 200
    assert {h["id"] for h in result["hotels"]} == {"FIXTURE-H1", "FIXTURE-H2"}
    assert all(o["mode"] == "train" for o in result["transport"])


def test_invalid_timing_gets_one_successful_correction():
    result, calls = run_agents("repair")
    assert calls.count("Schedule") == 2 and result["itinerary"]["correction_attempts"] == 1
    assert result["status"] == "draft_ready"
    assert result["agent_usage"]["itinerary"]["total_tokens"] == 400


def test_unresolved_conflict_is_visible_and_correction_is_bounded():
    result, calls = run_agents("always_bad")
    assert calls.count("Schedule") == 2
    assert result["status"] == "draft_needs_review" and result["itinerary"]["validation_errors"]


def test_unknown_ranking_id_stops_further_model_work():
    result, calls = run_agents("unknown_rank")
    assert calls == ["SupervisorDecision", "OfferRanking"]
    assert result["status"] == "partial_results" and result["transport"] == []
    assert result["specialist_error"]["role"] == "transport"
    assert "fixture-secret" not in str(result)


def test_hotel_filters_exact_stars_rating_occupancy_and_unknown_price():
    p = TripPreferences(**PREFERENCES)
    offers = fixtures.hotels(p)
    assert [h.id for h in eligible_hotels(offers, p)] == ["FIXTURE-H1", "FIXTURE-H2"]
    offers[0].nightly_price = None
    offers[1].adults = 1
    assert eligible_hotels(offers, p) == []


def test_train_flight_comparison_and_unknown_flight_cap():
    p = TripPreferences(**(PREFERENCES | {"transport_mode": "compare"}))
    offers = fixtures.transport(p)
    assert {o.mode for o in eligible_transport(offers, p)} == {"train", "flight"}
    p.flight_max_price = 6000
    assert all(o.mode == "train" for o in eligible_transport(offers, p))


def test_unknown_hours_are_warning_but_unknown_ids_are_errors():
    p = TripPreferences(**PREFERENCES)
    places = fixtures.places(p); places[0].weekly_hours = {}
    transport = fixtures.transport(p)
    schedule = Schedule(activities=[dict(place_id="FIXTURE-P1", date="2027-02-11", start="10:00", end="11:00")], notes=[])
    errors, warnings = validate_schedule(schedule, places, transport[0], transport[1], p, "Asia/Kolkata")
    assert not errors and warnings
    schedule.activities[0].place_id = "MADE-UP"
    errors, _ = validate_schedule(schedule, places, transport[0], transport[1], p, "Asia/Kolkata")
    assert errors


def test_transfer_buffer_and_closed_place_are_rejected():
    p = TripPreferences(**PREFERENCES)
    places, transport = fixtures.places(p), fixtures.transport(p)
    schedule = Schedule(activities=[dict(place_id="FIXTURE-P1", date="2027-02-11", start="10:00", end="11:00"),
        dict(place_id="FIXTURE-P2", date="2027-02-11", start="11:10", end="12:00")], notes=[])
    errors, _ = validate_schedule(schedule, places, transport[0], transport[1], p, "Asia/Kolkata")
    assert any("30-minute" in e for e in errors)
    places[0].weekly_hours = {3: []}  # Thursday: explicitly closed, not unknown.
    schedule = Schedule(activities=[dict(place_id="FIXTURE-P1", date="2027-02-11", start="10:00", end="11:00")], notes=[])
    errors, _ = validate_schedule(schedule, places, transport[0], transport[1], p, "Asia/Kolkata")
    assert any("opening hours" in e for e in errors)


def test_explanation_turn_does_not_reuse_old_specialist_token_counts():
    def forbidden(*args):
        raise AssertionError("No specialists needed")
    def supervisor(message, preferences):
        return SupervisorTurn(SupervisorDecision(intent="question", updates=[], clarification_question=None,
                                                answer="Fixture explanation."), {}, {"total_tokens": 100})
    graph = build_workflow(forbidden, forbidden, forbidden, InMemorySaver(), supervisor)
    result = graph.invoke({"user_message": "Explain my preference.", "agent_usage": {"hotels": {"total_tokens": 900}}},
                          {"configurable": {"thread_id": "question-counts"}})
    assert result["status"] == "message_only" and result["agent_usage"] == {}
