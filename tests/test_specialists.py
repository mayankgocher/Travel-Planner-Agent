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


def run_agents(fault=None, assumed_fares=False):
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
            if fault in {"repeat_id", "unknown_id", "only_unknown_id", "unknown_with_bad_timing"}:
                visit = answer["activities"][0]
                extra = visit | {"start": "16:30", "end": "17:30"}
                if fault != "repeat_id":
                    extra["place_id"] = "MADE-UP"
                if fault == "only_unknown_id":
                    answer["activities"] = [extra]
                else:
                    answer["activities"].append(extra)
                if fault == "unknown_with_bad_timing":
                    visit.update(start="08:00", end="09:00")
            if fault in {"overlap", "tight_gap", "exact_gap", "overlap_and_unknown", "overlap_and_closed"}:
                ranges = {
                    "overlap": [("10:00", "16:00"), ("10:40", "11:40"), ("12:10", "13:10")],
                    "tight_gap": [("10:00", "11:00"), ("11:20", "12:20"), ("11:30", "12:30")],
                    "exact_gap": [("10:00", "11:00"), ("11:30", "12:30"), ("13:00", "14:00")],
                    "overlap_and_unknown": [("10:00", "11:00"), ("10:30", "11:30"), ("12:00", "13:00")],
                    "overlap_and_closed": [("08:30", "10:00"), ("09:30", "11:00"), ("12:00", "13:00")],
                }[fault]
                answer["activities"] = [
                    dict(place_id=f"FIXTURE-P{n}", date="2027-02-11", start=start, end=end)
                    for n, (start, end) in enumerate(ranges, start=1)
                ]
                if fault == "overlap_and_unknown":
                    answer["activities"][-1]["place_id"] = "MADE-UP"
        else:
            raise AssertionError("Unexpected model request")
        return httpx.Response(200, json={"id": "fixture", "object": "chat.completion", "created": 1,
            "model": "openai/gpt-oss-120b", "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        model = create_model(Settings(_env_file=None, groq_model="openai/gpt-oss-120b", groq_api_key="fixture-secret"), http_client=client)
        def transport_search(p):
            offers = fixtures.transport(p)
            if assumed_fares:
                for offer in offers:
                    if offer.mode == "train":
                        offer.price.pricing_mode = "demo"
                        offer.price.per_adult_amount = offer.price.amount / offer.adults
                        offer.price.demo_rule_version = "test-assumption"
                        offer.price.taxes_included = None
            return offers
        graph = build_workflow(TransportationAgent(model, transport_search), HotelAgent(model, fixtures.hotels),
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


def test_four_agent_graph_discloses_demo_prices_and_never_claims_real_affordability():
    result, calls = run_agents(assumed_fares=True)
    assert result["status"] == "draft_ready_with_warnings" and result["itinerary"]["contains_assumed_prices"]
    assert result["costs"]["budget_status"] == "unknown" and result["costs"]["complete_subtotal"] is None
    assert result["costs"]["illustrative_subtotal"] == "16900"
    assert result["costs"]["illustrative_budget_status"] == "within_assumed_budget"
    assert result["costs"]["known_subtotal"] == "12000"
    assert any("illustrative" in warning for warning in result["warnings"])


def test_invalid_timing_gets_one_successful_correction():
    result, calls = run_agents("repair")
    assert calls.count("Schedule") == 2 and result["itinerary"]["correction_attempts"] == 1
    assert result["status"] == "draft_ready"
    assert result["agent_usage"]["itinerary"]["total_tokens"] == 400


def test_unresolved_conflict_is_visible_and_correction_is_bounded():
    result, calls = run_agents("always_bad")
    assert calls.count("Schedule") == 2
    assert result["status"] == "draft_needs_review" and result["itinerary"]["validation_errors"]


@pytest.mark.parametrize(("fault", "omissions"), [
    ("unknown_id", "unknown place IDs: 1; repeated place IDs: 0"),
    ("repeat_id", "unknown place IDs: 0; repeated place IDs: 1"),
])
def test_shortened_schedule_preserves_the_valid_visit(fault, omissions):
    result, calls = run_agents(fault)
    assert calls.count("Schedule") == 2
    assert result["status"] == "draft_ready_with_warnings"
    itinerary = result["itinerary"]
    assert itinerary["activities"] == [{"place_id": "FIXTURE-P1", "date": "2027-02-10",
                                        "start": "15:00", "end": "16:00"}]
    assert not itinerary["validation_errors"]
    assert any("Itinerary shortened" in warning and omissions in warning for warning in result["warnings"])


@pytest.mark.parametrize("fault", ["only_unknown_id", "unknown_with_bad_timing"])
def test_omission_cannot_publish_an_empty_schedule_or_bypass_timing(fault):
    result, calls = run_agents(fault)
    assert calls.count("Schedule") == 2
    assert result["status"] == "draft_needs_review"
    errors = result["itinerary"]["validation_errors"]
    assert "Unknown place ID: MADE-UP" in errors
    if fault == "unknown_with_bad_timing":
        assert any("arrival/departure buffer" in error for error in errors)
    assert not any("Itinerary shortened" in warning for warning in result["warnings"])


@pytest.mark.parametrize(("fault", "kept"), [
    ("overlap", [("FIXTURE-P2", "10:40", "11:40"), ("FIXTURE-P3", "12:10", "13:10")]),
    ("tight_gap", [("FIXTURE-P1", "10:00", "11:00"), ("FIXTURE-P3", "11:30", "12:30")]),
    ("overlap_and_unknown", [("FIXTURE-P1", "10:00", "11:00")]),
])
def test_unresolved_activity_conflicts_keep_valid_visits_at_original_times(fault, kept):
    result, calls = run_agents(fault)
    itinerary = result["itinerary"]
    assert calls.count("Schedule") == 2
    assert result["status"] == "draft_ready_with_warnings"
    assert [(a["place_id"], a["start"], a["end"]) for a in itinerary["activities"]] == kept
    assert not itinerary["validation_errors"]
    assert any("Visits omitted to keep a 30-minute gap between activities: 1." in w for w in result["warnings"])
    if fault == "overlap_and_unknown":
        assert any("unknown place IDs: 1" in w for w in result["warnings"])


def test_exact_transfer_buffer_keeps_the_whole_schedule_without_correction():
    result, calls = run_agents("exact_gap")
    assert calls.count("Schedule") == 1
    assert result["status"] == "draft_ready" and len(result["itinerary"]["activities"]) == 3


def test_a_closing_hours_error_still_blocks_a_schedule_with_a_short_gap():
    result, calls = run_agents("overlap_and_closed")
    assert calls.count("Schedule") == 2 and result["status"] == "draft_needs_review"
    errors = result["itinerary"]["validation_errors"]
    assert any("opening hours" in error for error in errors)
    assert any("30-minute" in error for error in errors)


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
