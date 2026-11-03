"""Real LangGraph execution with labeled synthetic workers and no networking."""
import socket
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from backend import demo_workers
from backend.graph.builder import build_workflow

REQUEST = {"origin": "Delhi", "destination": "Jaipur", "adults": 2,
           "departure_date": "2027-02-10", "return_date": "2027-02-14"}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Workflow tests must not use the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def make_graph(checkpointer=None, failing_hotel=False):
    calls = []
    def transport(p):
        calls.append("transport")
        return demo_workers.transport(p)
    def hotel(p):
        calls.append("hotels")
        if failing_hotel:
            raise TimeoutError("fixture error that must not leak")
        return demo_workers.hotels(p)
    def itinerary(state):
        calls.append("itinerary")
        return demo_workers.itinerary(state)
    graph = build_workflow(transport, hotel, itinerary,
                           checkpointer if checkpointer is not None else InMemorySaver())
    return graph, calls


def config(thread=None):
    return {"configurable": {"thread_id": thread or str(uuid4())}, "recursion_limit": 30}


def test_complete_request_runs_workers_once_in_dependency_order():
    graph, calls = make_graph()
    result = graph.invoke({"request_patch": REQUEST}, config())
    assert calls == ["transport", "hotels", "itinerary"]
    assert result["status"] == "workflow_complete" and result["pending"] == []
    assert all(o["source"]["synthetic"] for o in result["transport"] + result["hotels"])
    assert result["itinerary"]["synthetic"]
    assert result["itinerary"]["received_hotel_ids"] == ["DEMO-HOTEL"]


def test_clarification_pauses_before_workers_and_resumes_same_trip():
    graph, calls = make_graph(); cfg = config()
    paused = graph.invoke({"request_patch": {"origin": "Delhi", "destination": "Jaipur", "adults": 2}}, cfg)
    assert set(paused["__interrupt__"][0].value["missing_fields"]) == {"departure_date", "return_date"}
    assert calls == []
    done = graph.invoke(Command(resume={"departure_date": "2027-02-10", "return_date": "2027-02-14"}), cfg)
    assert done["preferences"]["origin"] == "Delhi"
    assert calls == ["transport", "hotels", "itinerary"]


def test_invalid_clarification_reprompts_without_searching():
    graph, calls = make_graph(); cfg = config()
    graph.invoke({"request_patch": {"origin": "Delhi"}}, cfg)
    bad = graph.invoke(Command(resume={"adults": 0}), cfg)
    assert bad["__interrupt__"][0].value["kind"] == "clarification"
    assert "adults" in bad["__interrupt__"][0].value["message"] and not calls


def test_interests_change_does_not_repeat_transport_or_hotels():
    graph, calls = make_graph(); cfg = config()
    first = graph.invoke({"request_patch": REQUEST}, cfg); calls.clear()
    revised = graph.invoke({"request_patch": {"interests": ["history"]}}, cfg)
    assert calls == ["itinerary"]
    assert revised["transport"] == first["transport"] and revised["hotels"] == first["hotels"]
    assert revised["invalidated"] == ["itinerary", "places"]


def test_unchanged_request_does_not_repeat_work():
    graph, calls = make_graph(); cfg = config()
    graph.invoke({"request_patch": REQUEST}, cfg); calls.clear()
    result = graph.invoke({"request_patch": {}}, cfg)
    assert calls == [] and result["status"] == "workflow_complete"


def test_date_change_runs_dependent_workers_again():
    graph, calls = make_graph(); cfg = config()
    graph.invoke({"request_patch": REQUEST}, cfg); calls.clear()
    result = graph.invoke({"request_patch": {"departure_date": "2027-02-11"}}, cfg)
    assert calls == ["transport", "hotels", "itinerary"]
    assert result["transport"][0]["departure"].startswith("2027-02-11")
    assert result["itinerary"]["refresh_weather"]


def test_worker_failure_keeps_partial_results_and_unknown_budget():
    graph, calls = make_graph(failing_hotel=True)
    result = graph.invoke({"request_patch": REQUEST | {"currency": "INR"}}, config())
    assert result["hotels"] == [] and len(result["transport"]) == 2
    assert result["warnings"] and "fixture error" not in str(result)
    assert result["costs"]["complete_subtotal"] is None
    assert result["costs"]["budget_status"] == "unknown"


def test_sqlite_checkpoint_can_resume_after_graph_is_rebuilt(tmp_path):
    path = str(tmp_path / "checkpoints.sqlite")
    cfg = config("resume-fixture")
    with SqliteSaver.from_conn_string(path) as saver:
        graph, calls = make_graph(saver)
        graph.invoke({"request_patch": {"origin": "Delhi"}}, cfg)
        assert calls == []
    with SqliteSaver.from_conn_string(path) as saver:
        graph, calls = make_graph(saver)
        result = graph.invoke(Command(resume={k: v for k, v in REQUEST.items() if k != "origin"}), cfg)
        assert result["status"] == "workflow_complete"
        assert calls == ["transport", "hotels", "itinerary"]


def test_thread_ids_keep_trips_separate():
    graph, calls = make_graph()
    first, second = config("one"), config("two")
    graph.invoke({"request_patch": REQUEST}, first)
    paused = graph.invoke({"request_patch": {"origin": "Mumbai"}}, second)
    assert paused["preferences"]["origin"] == "Mumbai" and paused["missing_fields"]
    assert graph.get_state(first).values["preferences"]["origin"] == "Delhi"
