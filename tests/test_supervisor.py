"""Exercise the real ChatGroq wrapper with intercepted HTTP, never live requests."""
import json
import os
import socket
from typing import get_args

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from backend import demo_workers
from backend.agents.supervisor import PreferenceField, Supervisor, SupervisorDecision, validated_patch
from backend.config import Settings
from backend.graph.builder import build_workflow
from backend.llm import ModelCallError, create_model, safe_provider_error
from backend.schemas import TripPreferences


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # Do not inherit host proxy/model configuration in an HTTP-intercepted test.
    for name in list(os.environ):
        if name.lower().endswith("_proxy") or name in ("GROQ_API_KEY", "GROQ_MODEL", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
            monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("Supervisor tests must use MockTransport, not the network")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


def decision(updates=None, intent="plan", answer=None):
    return {"intent": intent, "updates": updates or [], "clarification_question": None, "answer": answer}


def update(field, value):
    return {"field": field, "value": value}


def complete_decision():
    return decision([update("origin", "Delhi"), update("destination", "Jaipur"), update("adults", 2),
                     update("departure_date", "2027-02-10"), update("return_date", "2027-02-14")])


def mock_supervisor(payload, requests, status=200, finish="stop"):
    def handle(request):
        requests.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "fixture-secret", "type": "test_error"}})
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"id": "fixture-response", "object": "chat.completion", "created": 1,
            "model": "openai/gpt-oss-120b", "choices": [{"index": 0, "finish_reason": finish,
                "message": {"role": "assistant", "content": content, "reasoning": "not-to-be-retained"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 80, "total_tokens": 180}})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    settings = Settings(_env_file=None, groq_api_key="fixture-secret")
    return Supervisor(create_model(settings, http_client=client)), client


def test_real_wrapper_sends_native_strict_schema_without_tools():
    requests = []
    supervisor, client = mock_supervisor(complete_decision(), requests)
    with client:
        turn = supervisor("Plan Delhi to Jaipur for two adults, February 10 to 14, 2027.", TripPreferences())
    assert turn.patch["adults"] == 2 and turn.usage["total_tokens"] == 180
    wire = requests[0]
    assert wire["response_format"]["type"] == "json_schema"
    assert wire["response_format"]["json_schema"]["strict"] is True
    def no_overlapping_numeric_union(node):
        if isinstance(node, dict):
            types = {s.get("type") for s in node.get("anyOf", []) if isinstance(s, dict) and isinstance(s.get("type"), str)}
            assert not {"integer", "number"}.issubset(types), "Groq rejects integer/number overlap"
            for value in node.values():
                no_overlapping_numeric_union(value)
        elif isinstance(node, list):
            for value in node:
                no_overlapping_numeric_union(value)
    no_overlapping_numeric_union(wire["response_format"]["json_schema"]["schema"])
    assert "tools" not in wire and wire["include_reasoning"] is False
    assert len(requests) == 1 and "not-to-be-retained" not in str(turn)


def test_update_preserves_omitted_preferences_and_field_enum_is_complete():
    current = TripPreferences(origin="Delhi", destination="Jaipur", adults=2, nightly_max=4000)
    d = SupervisorDecision.model_validate(decision([update("interests", ["history"])], intent="update"))
    patch = validated_patch(d, current)
    merged = TripPreferences.model_validate(current.model_dump() | patch)
    assert merged.nightly_max == 4000 and merged.origin == "Delhi" and merged.interests == ["history"]
    assert set(get_args(PreferenceField)) == set(TripPreferences.model_fields)


@pytest.mark.parametrize("field,value,expected", [
    ("adults", 2.0, 2), ("hotel_class", 3.0, 3), ("flight_sort_by", 2.0, 2),
    ("hotel_class", "3", 3), ("hotel_class", "3.0", 3), ("hotel_class", "3-star", 3),
    ("hotel_class", "3 stars", 3), ("adults", "2", 2), ("adults", "2.0", 2), ("flight_sort_by", "2", 2),
])
def test_integral_numeric_updates_become_strict_domain_integers(field, value, expected):
    d = SupervisorDecision.model_validate(decision([update(field, value)]))
    patch = validated_patch(d, TripPreferences())
    assert patch[field] == expected and type(patch[field]) is int


@pytest.mark.parametrize("value", ["3.5", "3-4", "three", "at least 3", "1e100"])
def test_ambiguous_or_fractional_hotel_class_is_not_guessed(value):
    d = SupervisorDecision.model_validate(decision([update("hotel_class", value)]))
    with pytest.raises(ModelCallError):
        validated_patch(d, TripPreferences())


@pytest.mark.parametrize("field", ["adults", "hotel_class", "flight_sort_by"])
def test_fractional_integer_fields_are_rejected_without_truncation(field):
    d = SupervisorDecision.model_validate(decision([update(field, 2.5)]))
    with pytest.raises(ModelCallError, match="whole number"):
        validated_patch(d, TripPreferences())


@pytest.mark.parametrize("value", [True, float("nan")])
def test_boolean_and_nonfinite_updates_are_rejected(value):
    with pytest.raises(ValidationError):
        SupervisorDecision.model_validate(decision([update("adults", value)]))


@pytest.mark.parametrize("updates", [
    [update("adults", 0)], [update("nightly_min", "4000"), update("nightly_max", "2000")],
    [update("origin", "Delhi"), update("origin", "Mumbai")],
])
def test_semantically_invalid_updates_are_rejected(updates):
    with pytest.raises(ModelCallError):
        validated_patch(SupervisorDecision.model_validate(decision(updates)), TripPreferences())


@pytest.mark.parametrize("payload,status,finish", [
    ("invalid JSON", 200, "stop"), (complete_decision(), 200, "length"),
    ({}, 401, "stop"), ({}, 429, "stop"),
])
def test_bad_responses_fail_safely_without_automatic_retry(payload, status, finish):
    requests = []
    supervisor, client = mock_supervisor(payload, requests, status, finish)
    with client, pytest.raises(ModelCallError) as caught:
        supervisor("Plan my trip.", TripPreferences())
    assert "fixture-secret" not in str(caught.value)
    assert "fixture-secret" not in str(caught.value.provider_error)
    assert len(requests) == 1
    if status == 200:
        assert caught.value.model_usage["total_tokens"] == 180


def test_rejected_supervisor_decision_retains_usage_and_bad_value_in_graph():
    payload = complete_decision()
    payload["updates"].append(update("hotel_class", "3-4"))
    requests = []; supervisor, client = mock_supervisor(payload, requests)
    with client:
        graph = build_workflow(demo_workers.transport, demo_workers.hotels, demo_workers.itinerary,
                               InMemorySaver(), supervisor)
        result = graph.invoke({"user_message": "Use exactly three-star hotels."},
                              {"configurable": {"thread_id": "rejected-slot"}})
    assert result["status"] == "supervisor_error" and len(requests) == 1
    assert result["model_usage"]["total_tokens"] == 180
    assert result["supervisor_decision"]["updates"][-1]["value"] == "3-4"
    assert "preferences" not in result


def test_message_only_intent_cannot_mutate_preferences():
    d = SupervisorDecision.model_validate(decision([update("adults", 3)], intent="question"))
    with pytest.raises(ModelCallError):
        validated_patch(d, TripPreferences())


def test_supervisor_connects_to_graph_and_failure_preserves_preferences():
    requests = []; supervisor, client = mock_supervisor(complete_decision(), requests)
    with client:
        graph = build_workflow(demo_workers.transport, demo_workers.hotels, demo_workers.itinerary,
                               InMemorySaver(), supervisor)
        cfg = {"configurable": {"thread_id": "supervisor-fixture"}, "recursion_limit": 30}
        result = graph.invoke({"user_message": "Plan Delhi to Jaipur for two adults, February 10-14, 2027."}, cfg)
    assert result["status"] == "workflow_complete" and result["model_usage"]["total_tokens"] == 180
    assert len(requests) == 1 and result["user_message"] == ""
    failed_requests = []; failing, failed_client = mock_supervisor({}, failed_requests, status=401)
    with failed_client:
        broken = build_workflow(demo_workers.transport, demo_workers.hotels, demo_workers.itinerary,
                                InMemorySaver(), failing)
        failed = broken.invoke({"preferences": result["preferences"], "user_message": "Change my hotel."}, cfg)
    assert failed["status"] == "supervisor_error" and failed["preferences"] == result["preferences"]
    assert "fixture-secret" not in str(failed)


@pytest.mark.parametrize("intent", ["question", "unsupported"])
def test_message_only_response_stops_before_specialists(intent):
    requests = []; supervisor, client = mock_supervisor(decision(intent=intent, answer="Fixture explanation."), requests)
    def forbidden_worker(*args):
        raise AssertionError("Message-only requests must not run specialists")
    with client:
        graph = build_workflow(forbidden_worker, forbidden_worker, forbidden_worker, InMemorySaver(), supervisor)
        result = graph.invoke({"user_message": "Explain the supported scope."}, {"configurable": {"thread_id": intent}})
    assert result["status"] == "message_only" and result["supervisor_decision"]["answer"] == "Fixture explanation."


def test_natural_language_clarification_runs_supervisor_on_resume():
    requests = []; supervisor, client = mock_supervisor(complete_decision(), requests)
    with client:
        graph = build_workflow(demo_workers.transport, demo_workers.hotels, demo_workers.itinerary,
                               InMemorySaver(), supervisor)
        cfg = {"configurable": {"thread_id": "nl-resume"}, "recursion_limit": 30}
        paused = graph.invoke({"request_patch": {"origin": "Delhi"}}, cfg)
        assert "__interrupt__" in paused and not requests
        result = graph.invoke(Command(resume="Two adults, Jaipur, February 10 to 14, 2027."), cfg)
    assert result["status"] == "workflow_complete" and len(requests) == 1
    assert result["itinerary"]["refresh_places"] and result["itinerary"]["refresh_weather"]


def test_live_check_preview_does_not_load_settings_or_create_client(monkeypatch):
    from scripts import check_supervisor as check
    def forbidden(*args, **kwargs):
        raise AssertionError("Preview must not load configuration or instantiate a model")
    monkeypatch.setattr(check, "Settings", forbidden)
    monkeypatch.setattr(check, "create_model", forbidden)
    monkeypatch.setattr(check.sys, "argv", ["check_supervisor.py"])
    assert check.main() == 0


def test_live_check_writes_parsed_report_with_intercepted_request(tmp_path, monkeypatch):
    from scripts import check_supervisor as check
    payload = complete_decision()
    payload["updates"] += [update("transport_mode", "train"), update("hotel_class", 3),
        update("nightly_min", "2000.00"), update("nightly_max", "4000.0"),
        update("guest_rating_min", 4), update("budget_total", "25000"),
        update("currency", "INR"), update("interests", ["History"])]
    requests = []; supervisor, client = mock_supervisor(payload, requests)
    monkeypatch.setattr(check, "Settings", lambda: Settings(_env_file=None, data_dir=tmp_path))
    monkeypatch.setattr(check, "create_model", lambda settings: supervisor.model)
    monkeypatch.setattr(check.sys, "argv", ["check_supervisor.py", "--live"])
    with client:
        assert check.main() == 0
    path = next((tmp_path / "reports").glob("*.json"))
    report = json.loads(path.read_text())
    assert report["outcome"] == "PASS_CHECKS" and len(requests) == 1
    assert report["synthetic_downstream"] and report["model_usage"]["total_tokens"] == 180
    assert "fixture-secret" not in path.read_text() and "not-to-be-retained" not in path.read_text()


def test_error_details_exclude_generation_and_redact_before_truncation():
    secret = "fixture-secret-" * 100
    body = {"error": {"message": "Schema rejected. " + secret + " wrong parameter",
                      "code": "invalid_schema", "param": "response_format", "type": "invalid_request_error",
                      "failed_generation": "private output", "request": {"Authorization": "Bearer " + secret}}}
    details = safe_provider_error(body, secret)
    assert set(details) == {"message", "code", "param", "type"}
    assert "fixture-secret" not in str(details) and "private output" not in str(details)
    assert details["message"] == "Schema rejected. [REDACTED] wrong parameter"
    assert safe_provider_error("raw error body must not be copied", secret) == {}


def test_http_400_reason_survives_graph_and_report_without_secrets(tmp_path, monkeypatch):
    from scripts import check_supervisor as check
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "Invalid response_format. fixture-secret",
            "code": "invalid_schema", "param": "response_format", "type": "invalid_request_error",
            "failed_generation": "private output"}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        settings = Settings(_env_file=None, groq_api_key="fixture-secret", data_dir=tmp_path)
        model = create_model(settings, http_client=client)
        monkeypatch.setattr(check, "Settings", lambda: settings)
        monkeypatch.setattr(check, "create_model", lambda settings: model)
        monkeypatch.setattr(check.sys, "argv", ["check_supervisor.py", "--live"])
        assert check.main() == 2
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert len(requests) == 1 and report["outcome"] == "PROVIDER_REQUEST_ERROR"
    assert report["supervisor_http_status"] == 400
    assert report["supervisor_error_detail"]["code"] == "invalid_schema"
    assert "fixture-secret" not in str(report) and "private output" not in str(report)


@pytest.mark.parametrize("status,expected_total", [(200, 180), (400, None)])
def test_four_agent_report_preserves_rejected_reply_usage_or_unknown(tmp_path, monkeypatch, status, expected_total):
    from scripts import check_agents as check
    payload = complete_decision()
    payload["updates"].append(update("hotel_class", "3-4"))
    requests = []; supervisor, client = mock_supervisor(payload, requests, status=status)
    monkeypatch.setattr(check, "Settings", lambda: Settings(_env_file=None, data_dir=tmp_path))
    monkeypatch.setattr(check, "create_model", lambda settings: supervisor.model)
    monkeypatch.setattr(check.sys, "argv", ["check_agents.py", "--live"])
    with client:
        assert check.main() == 2
    report = json.loads(next((tmp_path / "reports").glob("*.json")).read_text())
    assert report["reported_total_tokens"] == expected_total and len(requests) == 1
    assert report["agent_usage"] == {}
    if status == 200:
        assert report["supervisor_decision"]["updates"][-1]["value"] == "3-4"
    assert "fixture-secret" not in str(report)
