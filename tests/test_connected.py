"""Full composition uses invented responses over MockTransport, never a network."""
from datetime import date, timedelta
from copy import deepcopy
import json
import os
import socket

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from backend.config import Settings
from backend.llm import create_model
from backend.providers.http import SerpApiHttp
from backend.providers.rail_http import RailRadarHttp
from backend.providers.session import TravelProviderSession, jaipur_probe_bindings
from backend.runtime import build_provider_workflow
from backend.schemas import TripPreferences
from backend.services.hotel_dates import stay_preferences
from scripts import check_connected
from scripts.connected_recovery import load_itinerary_resume

P = dict(origin="Delhi", destination="Jaipur", departure_date="2027-02-10", return_date="2027-02-13",
    adults=2, transport_mode="train", train_class="CC", currency="INR", hotel_class=3, nightly_min="2000",
    nightly_max="4000", guest_rating_min=4.2, budget_total="25000", interests=["history"], pace="relaxed")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*a, **k): raise AssertionError("Connected tests cannot access real sockets")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    for key in list(os.environ):
        if key.lower().endswith("_proxy"): monkeypatch.delenv(key)


class Responses:
    def __init__(self, *, overnight=False, rail_error=False, hotel_error=False, mode="train"):
        self.overnight, self.rail_error, self.hotel_error, self.mode = overnight, rail_error, hotel_error, mode
        self.calls, self.roles = [], []

    def __call__(self, request):
        self.calls.append(request)
        path, host, q = request.url.path, request.url.host, dict(request.url.params)
        if host == "api.railradar.in":
            if self.rail_error:
                return httpx.Response(401, json={"success": False, "error": {"message": "bad rail-secret", "code": "UNAUTHORIZED"}})
            assert not path.endswith("/fare")  # Default mock mode must not query a paid fare.
            if "/between/" in path:
                a, b = path.split("/")[-2:]
                outward = a == "NDLS"
                row = {"train": {"number": "12015" if outward else "12016", "name": "Invented test service"},
                    "from": {"code": a, "day": 2, "departure": "23:00" if outward and self.overnight else "08:00" if outward else "16:00"},
                    "to": {"code": b, "day": 3 if outward and self.overnight else 2, "arrival": "03:00" if outward and self.overnight else "12:00" if outward else "20:00"}, "duration": 240}
                data = {"from": {"code": a}, "to": {"code": b}, "trains": [row]}
            else:
                number = path.rsplit("/", 1)[1]
                codes = ["NDLS", "JP"] if number == "12015" else ["JP", "NDLS"]
                data = {"train": {"number": number, "name": "Invented test service", "availableClasses": ["CC", "EC"], "isPrsBookable": True},
                        "route": [{"station": {"code": c}} for c in codes]}
            return httpx.Response(200, json={"success": True, "data": data})
        if host == "serpapi.com":
            if q["engine"] == "google_hotels":
                if self.hotel_error:
                    return httpx.Response(403, json={"error": "blocked serp-secret"})
                nights = (date.fromisoformat(q["check_out_date"]) - date.fromisoformat(q["check_in_date"])).days
                body = {"search_parameters": q, "properties": [{"type": "hotel", "name": "Invented hotel", "property_token": "test-hotel",
                    "extracted_hotel_class": 3, "overall_rating": 4.5, "rate_per_night": {"extracted_lowest": 3000},
                    "total_rate": {"extracted_lowest": 3000 * nights}, "link": "https://example.com/hotel"}]}
            elif q["engine"] == "google_flights":
                day = q["outbound_date"]
                outward = q["departure_id"] == "DEL"
                body = {"search_parameters": q, "other_flights": [{"type": "One way", "price": 9000, "flights": [{
                    "departure_airport": {"id": q["departure_id"], "time": day + (" 08:00" if outward else " 16:00")},
                    "arrival_airport": {"id": q["arrival_id"], "time": day + (" 09:00" if outward else " 17:00")},
                    "flight_number": "ZZ 100", "airline": "Invented Airline", "travel_class": "Economy"}]}]}
            else:
                body = {"local_results": [{"place_id": "test-museum", "title": "Invented museum",
                    "gps_coordinates": {"latitude": 26.9, "longitude": 75.8},
                    "operating_hours": {d: "9 AM–5 PM" for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}}]}
            return httpx.Response(200, json=body)
        assert host == "api.groq.com"
        wire = json.loads(request.content); name = wire["response_format"]["json_schema"]["name"]
        assert "tools" not in wire  # Structured calls remain separate from tools invoked by Python.
        self.roles.append(name)
        if name == "SupervisorDecision":
            prefs = P | {"transport_mode": self.mode}
            answer = {"intent": "plan", "updates": [{"field": k, "value": v} for k, v in prefs.items()], "clarification_question": None, "answer": None}
        elif name == "OfferRanking":
            candidates = json.loads(wire["messages"][1]["content"])["candidates"]
            answer = {"ranked_ids": [o["id"] for o in candidates], "reason": "Test ranking; any demo fares remain assumed."}
        else:
            assert name == "Schedule"
            day = "2027-02-11" if self.overnight else "2027-02-10"
            answer = {"activities": [{"place_id": "place:test-museum", "date": day, "start": "15:00", "end": "16:00"}], "notes": ["Test schedule; no booking."]}
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1, "model": "openai/gpt-oss-120b",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": json.dumps(answer)}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}})


def setup(settings, client):
    services = TravelProviderSession(settings, jaipur_probe_bindings(),
        serp_http=SerpApiHttp("serp-secret", http_client=client, max_requests=4),
        rail_http=RailRadarHttp("rail-secret", max_requests=6, http_client=client))
    return services, create_model(settings, http_client=client)


def config(tmp_path=None):
    values = dict(_env_file=None, groq_api_key="groq-secret", serpapi_api_key="serp-secret", railradar_api_key="rail-secret", train_fare_mode="mock", groq_model="openai/gpt-oss-120b")
    if tmp_path: values["data_dir"] = tmp_path
    return Settings(**values)


@pytest.mark.parametrize("mode", ["train", "flight", "compare"])
def test_all_four_roles_are_connected_to_real_adapter_code_with_no_fare_endpoint(mode):
    handler = Responses(mode=mode)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        with services:
            graph = build_provider_workflow(model, InMemorySaver(), services)
            result = graph.invoke({"user_message": "Offline test input"}, {"configurable": {"thread_id": mode}})
    assert handler.roles == ["SupervisorDecision", "OfferRanking", "OfferRanking", "Schedule"]
    assert services.tool_calls == ["transport", "hotels", "places"]
    assert result["status"] == "draft_ready_with_warnings" and not result["itinerary"]["synthetic"]
    assert result["costs"]["budget_status"] == "unknown" and result["costs"]["complete_subtotal"] is None
    assert len(services.audit()["railradar"]) == (0 if mode == "flight" else 4)
    assert len(services.audit()["serpapi"]) == (2 if mode == "train" else 4)
    if mode != "flight": assert result["itinerary"]["contains_assumed_prices"]


def test_overnight_transport_changes_hotel_search_dates_without_rewriting_user_trip_dates():
    handler = Responses(overnight=True)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        graph = build_provider_workflow(model, InMemorySaver(), services)
        result = graph.invoke({"user_message": "Offline test"}, {"configurable": {"thread_id": "overnight"}})
    hotel_request = next(r for r in handler.calls if r.url.params.get("engine") == "google_hotels")
    assert hotel_request.url.params["check_in_date"] == "2027-02-11"
    assert result["preferences"]["departure_date"] == "2027-02-10" and result["hotels"][0]["check_in"] == "2027-02-11"
    assert not result["itinerary"]["validation_errors"]


def test_hotel_provider_error_prevents_place_spending_and_does_not_invent_hotel():
    handler = Responses(hotel_error=True)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        result = build_provider_workflow(model, InMemorySaver(), services).invoke({"user_message": "Test"}, {"configurable": {"thread_id": "failed-hotel"}})
    assert result["hotels"] == [] and result["status"] == "draft_needs_review"
    assert handler.roles == ["SupervisorDecision", "OfferRanking"]
    assert len(services.audit()["serpapi"]) == 1 and "places" not in services.tool_calls
    assert any("serpapi hotels failed" in w for w in result["warnings"])
    assert "serp-secret" not in json.dumps(services.errors)


def test_rail_auth_error_stops_second_rail_leg_but_compare_can_use_flights():
    handler = Responses(rail_error=True, mode="compare")
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        result = build_provider_workflow(model, InMemorySaver(), services).invoke({"user_message": "Compare"}, {"configurable": {"thread_id": "partial"}})
    assert len(services.audit()["railradar"]) == 1 and len(services.audit()["serpapi"]) == 4
    assert all(o["mode"] == "flight" for o in result["transport"])
    assert result["status"] == "draft_ready_with_warnings" and any("railradar" in w for w in result["warnings"])


def test_missing_mode_class_currency_clarifies_before_any_provider_spending():
    handler = Responses()
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        graph = build_provider_workflow(model, InMemorySaver(), services)
        patch = {k: v for k, v in P.items() if k not in ("transport_mode", "train_class", "currency")}
        result = graph.invoke({"request_patch": patch}, {"configurable": {"thread_id": "clarify"}})
    assert set(result["missing_fields"]) >= {"transport_mode", "currency"}
    assert not handler.calls and result.get("__interrupt__")


def test_connected_report_captures_each_request_and_redacts_all_configured_keys(tmp_path):
    handler = Responses()
    settings = config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(settings, client)
        code = check_connected.run_check(settings, "Offline test input", model=model, providers=services)
    path = next((tmp_path / "reports").glob("*/report.json")); text = path.read_text(encoding="utf-8"); report = json.loads(text)
    assert code == 0 and report["outcome"] == "PASS_CONNECTED_CHECKS" and all(report["checks"].values())
    assert len(report["requests"]["serpapi"]) == 2 and len(report["requests"]["railradar"]) == 4
    assert report["reported_total_tokens"] == 800
    assert not any(key in text for key in ("serp-secret", "rail-secret", "groq-secret"))
    assert (path.parent / "share_results.zip").exists()


def test_connected_preview_has_zero_calls_and_no_key_loading(monkeypatch, capsys):
    def forbidden(*a, **k): raise AssertionError("Preview cannot load settings")
    monkeypatch.setattr(check_connected, "Settings", forbidden)
    assert check_connected.main([]) == 0 and "zero calls" in capsys.readouterr().out


def test_past_live_trip_date_clarifies_before_any_search():
    handler = Responses()
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        graph = build_provider_workflow(model, InMemorySaver(), services)
        patch = P | {"departure_date": "2020-01-01", "return_date": "2020-01-04"}
        result = graph.invoke({"request_patch": patch}, {"configurable": {"thread_id": "past"}})
    assert not handler.calls and result.get("__interrupt__") and "departure_date" in result["missing_fields"]


def test_transport_replan_refreshes_incompatible_hotel_dates_and_keeps_places():
    handler = Responses(); saver = InMemorySaver(); cfg = {"configurable": {"thread_id": "replan"}}
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        initial = build_provider_workflow(model, saver, services).invoke({"user_message": "Test"}, cfg)
        handler.overnight = True
        # A new execution gets new HTTP clients/audit budgets but the same stored trip state.
        services, model = setup(config(), client)
        changed = build_provider_workflow(model, saver, services).invoke({"request_patch": {"train_class": "EC"}}, cfg)
    assert initial["hotels"][0]["check_in"] == "2027-02-10" and changed["hotels"][0]["check_in"] == "2027-02-11"
    assert services.tool_calls == ["transport", "hotels"] and changed["places"] == initial["places"]
    assert "hotels" in changed["invalidated"] and any("different hotel dates" in w for w in changed["warnings"])


def test_flight_class_filters_run_before_the_four_option_shortlist():
    base = Responses(mode="flight")
    def handler(request):
        response = base(request)
        if request.url.host == "serpapi.com" and request.url.params.get("engine") == "google_flights":
            body = response.json(); original = body["other_flights"][0]; rows = []
            for index in range(6):
                item = deepcopy(original)
                item["flights"][0]["flight_number"] = f"ZZ {100 + index}"
                item["flights"][0]["travel_class"] = "Business" if index == 5 else "Economy"
                rows.append(item)
            body["other_flights"] = rows
            return httpx.Response(200, json=body)
        return response
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, _ = setup(config(), client)
        result = services.transport(TripPreferences(**(P | {"transport_mode": "flight", "flight_class": "Business"})))
    assert len(result.items) == 2 and all(o.travel_class == "Business" for o in result.items)


def itinerary_rate_limit(base):
    def handler(request):
        if request.url.host == "api.groq.com":
            name = json.loads(request.content)["response_format"]["json_schema"]["name"]
            if name == "Schedule":
                base.calls.append(request); base.roles.append(name)
                return httpx.Response(429, json={"error": {"message": "Test TPM limit groq-secret", "code": "rate_limit_exceeded"}})
        return base(request)
    return handler


def saved_failed_itinerary(tmp_path):
    base = Responses(); settings = config(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(itinerary_rate_limit(base)), trust_env=False) as client:
        services, model = setup(settings, client)
        code = check_connected.run_check(settings, "Offline test", model=model, providers=services)
    path = next((tmp_path / "reports").glob("*/report.json"))
    assert code == 2 and len(services.audit()["serpapi"]) == 2
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_rate_limit_preserves_successful_places_and_does_not_automatically_retry(tmp_path):
    path, report = saved_failed_itinerary(tmp_path)
    state = report["workflow"]
    assert state["status"] == "partial_results" and state["specialist_error"]["http_status"] == 429
    assert state["places"][0]["id"] == "place:test-museum" and len(state["transport"]) == 2 and state["hotels"]
    assert report["reported_total_tokens"] == 600 and state["agent_usage"]["itinerary"] == {}
    assert "groq-secret" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("old_report_without_places", [False, True])
def test_resume_executes_only_itinerary_and_separates_old_usage(tmp_path, old_report_without_places):
    path, original = saved_failed_itinerary(tmp_path)
    if old_report_without_places:
        original["workflow"]["places"] = []
        path.write_text(json.dumps(original), encoding="utf-8")
    original_bytes = path.read_bytes()
    # Exercise both accepted forms: JSON and the generated ZIP.
    source = path if old_report_without_places else path.parent / "share_results.zip"
    resume_data = load_itinerary_resume(source)
    handler = Responses(); settings = config(tmp_path / "continued")
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(settings, client)
        code = check_connected.run_check(settings, "Continue saved Itinerary step", model=model, providers=services, resume_data=resume_data)
    result_path = next((settings.data_path / "reports").glob("*/report.json"))
    report = json.loads(result_path.read_text(encoding="utf-8")); state = report["workflow"]
    assert code == 0 and handler.roles == ["Schedule"]
    assert services.tool_calls == (["places"] if old_report_without_places else [])
    assert not services.audit()["railradar"] and len(services.audit()["serpapi"]) == int(old_report_without_places)
    assert state["transport"] == resume_data[0]["transport"] and state["hotels"] == resume_data[0]["hotels"]
    assert state["preferences"] == original["workflow"]["preferences"]
    assert state["transport"][0]["source"] == original["workflow"]["transport"][0]["source"]
    assert report["reported_total_tokens"] == 200 and report["previous_run"]["reported_total_tokens"] == 600
    assert report["previous_run"]["request_counts"] == {"serpapi": 2, "railradar": 4}
    assert "four_roles_reported_usage" not in report["checks"] and all(report["checks"].values())
    assert report["limits"] == {"groq_calls": 2, "serpapi_requests": int(old_report_without_places), "railradar_requests": 0}
    assert path.read_bytes() == original_bytes
    assert state["costs"]["budget_status"] == "unknown" and state["itinerary"]["contains_assumed_prices"]


def test_resume_failure_still_preserves_evidence_for_another_continuation(tmp_path):
    path, _ = saved_failed_itinerary(tmp_path)
    resume_data = load_itinerary_resume(path)
    base = Responses(); settings = config(tmp_path / "continued")
    with httpx.Client(transport=httpx.MockTransport(itinerary_rate_limit(base)), trust_env=False) as client:
        services, model = setup(settings, client)
        code = check_connected.run_check(settings, "Continue", model=model, providers=services, resume_data=resume_data)
    result_path = next((settings.data_path / "reports").glob("*/report.json"))
    report = json.loads(result_path.read_text(encoding="utf-8"))
    assert code == 2 and not services.tool_calls and base.roles == ["Schedule"]
    assert report["reported_total_tokens"] is None  # Failed-call consumption is unknown.
    again, history, mode = load_itinerary_resume(result_path)
    assert again["places"] == resume_data[0]["places"] and mode == "mock"
    assert again["transport"] == resume_data[0]["transport"]


def test_resume_allows_only_one_schedule_correction_without_any_new_search(tmp_path):
    path, _ = saved_failed_itinerary(tmp_path)
    resume_data = load_itinerary_resume(path)
    base = Responses(); schedules = []
    def handler(request):
        response = base(request)
        if request.url.host == "api.groq.com":
            name = json.loads(request.content)["response_format"]["json_schema"]["name"]
            assert name == "Schedule"  # No intake or ranking calls during resume.
            schedules.append(name)
            if len(schedules) == 1:
                body = response.json()
                answer = json.loads(body["choices"][0]["message"]["content"])
                answer["activities"][0].update(start="08:00", end="09:00")
                body["choices"][0]["message"]["content"] = json.dumps(answer)
                return httpx.Response(200, json=body)
        return response
    settings = Settings(_env_file=None, data_dir=tmp_path / "continued", groq_api_key="groq-secret",
                        groq_model="openai/gpt-oss-120b", train_fare_mode="mock")
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        # No SerpApi/RailRadar keys or HTTP clients are needed with retained places.
        model = create_model(settings, http_client=client)
        services = TravelProviderSession(settings, jaipur_probe_bindings())
        code = check_connected.run_check(settings, "Continue", model=model, providers=services, resume_data=resume_data)
    assert code == 0 and schedules == ["Schedule", "Schedule"] and not services.tool_calls
    assert services.audit() == {"serpapi": [], "railradar": []}
    report = json.loads(next((settings.data_path / "reports").glob("*/report.json")).read_text(encoding="utf-8"))
    assert report["reported_total_tokens"] == 400 and report["workflow"]["itinerary"]["correction_attempts"] == 1


@pytest.mark.parametrize("extra", [["--live"], ["--fare-mode=live"], ["--transport-mode", "flight"], ["--departure", "2027-02-10"]])
def test_resume_refuses_new_trip_overrides_before_loading_keys(monkeypatch, extra):
    def forbidden(*a, **k): raise AssertionError("Conflicting options cannot load settings")
    monkeypatch.setattr(check_connected, "Settings", forbidden)
    with pytest.raises(SystemExit) as exc:
        check_connected.main(["--resume-report", "ignored.json", *extra])
    assert exc.value.code == 2


@pytest.mark.parametrize("damage", ["missing_hotels", "wrong_route", "synthetic", "past_date", "wrong_role"])
def test_invalid_resume_is_rejected_before_loading_keys(tmp_path, monkeypatch, damage):
    path, report = saved_failed_itinerary(tmp_path)
    state = report["workflow"]
    if damage == "missing_hotels": state["hotels"] = []
    elif damage == "wrong_route": state["transport"][0]["origin"] = "Mumbai"
    elif damage == "synthetic": state["hotels"][0]["source"]["synthetic"] = True
    elif damage == "past_date": state["preferences"]["departure_date"] = "2020-01-01"
    elif damage == "wrong_role": state["specialist_error"]["role"] = "hotels"
    path.write_text(json.dumps(report), encoding="utf-8")
    def forbidden(*a, **k): raise AssertionError("Invalid resume cannot load settings/keys")
    monkeypatch.setattr(check_connected, "Settings", forbidden)
    assert check_connected.main(["--resume-report", str(path)]) == 2


def test_ranking_short_aliases_map_back_to_full_ids_and_do_not_claim_affordability():
    base = Responses(); sent = []; token_prefix = "opaque-provider-token-" + "x" * 250
    def handler(request):
        response = base(request)
        body = response.json()
        if request.url.host == "serpapi.com" and request.url.params.get("engine") == "google_hotels":
            row = body["properties"][0]
            body["properties"] = [dict(row, name=f"Test hotel {i}", property_token=token_prefix + str(i)) for i in range(16)]
        elif request.url.host == "api.groq.com":
            wire = json.loads(request.content)
            if wire["response_format"]["json_schema"]["name"] == "OfferRanking":
                data = json.loads(wire["messages"][1]["content"]); sent.append(data)
                answer = json.loads(body["choices"][0]["message"]["content"])
                answer["ranked_ids"].reverse()
                answer["reason"] = "The whole trip is definitely within your budget."
                body["choices"][0]["message"]["content"] = json.dumps(answer)
        return httpx.Response(response.status_code, json=body)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        state = build_provider_workflow(model, InMemorySaver(), services).invoke({"user_message": "Test"}, {"configurable": {"thread_id": "aliases"}})
    assert [o["id"] for o in sent[1]["candidates"]] == [f"H{i:02d}" for i in range(1, 17)]
    assert all("budget_total" not in data["preferences"] for data in sent)
    assert token_prefix not in json.dumps(sent)
    assert state["hotels"][0]["name"] == "Test hotel 15" and token_prefix in state["hotels"][0]["id"]
    assert "ASSUMED DEMO FARES" in state["transport"][0]["recommendation_reason"]
    assert "affordability remains unknown" in state["hotels"][0]["recommendation_reason"]
    assert not any("definitely within" in o["recommendation_reason"] for o in state["transport"] + state["hotels"])


def test_alias_ranking_rejects_an_invented_or_duplicate_alias():
    from backend.agents.ranking import OfferRanking, apply_ranking
    from backend.llm import ModelCallError
    from backend import specialist_fixtures
    offers = specialist_fixtures.hotels(TripPreferences(**P))[:2]
    aliases = {"H01": offers[0].id, "H02": offers[1].id}
    for ids in (["H01", "H01"], ["H01", "H99"], ["H01"]):
        with pytest.raises(ModelCallError):
            apply_ranking(OfferRanking(ranked_ids=ids, reason="Test"), offers, aliases=aliases)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "unknown"])
def test_bad_hotel_ranking_keeps_eligible_offers_and_reaches_itinerary(fault):
    base = Responses()

    def handler(request):
        response = base(request)
        body = response.json()
        if request.url.params.get("engine") == "google_hotels":
            row = body["properties"][0]
            properties = [dict(row, name=f"Hotel {i}", property_token=f"hotel-{i}") for i in range(16)]
            for i, rating in ((1, 4.4), (2, 4.8)):
                properties[i].update(overall_rating=rating, rate_per_night={"extracted_lowest": 2100})
            properties.append(dict(row, name="Wrong class", property_token="wrong-class",
                                   extracted_hotel_class=2, rate_per_night={"extracted_lowest": 2000}))
            body["properties"] = properties
        elif request.url.host == "api.groq.com" and base.roles == ["SupervisorDecision", "OfferRanking", "OfferRanking"]:
            message = body["choices"][0]["message"]
            answer = json.loads(message["content"])
            ids = answer["ranked_ids"]
            if fault == "missing":
                ids.pop()
            elif fault == "duplicate":
                ids[-1] = ids[0]
            else:
                ids[-1] = "H99"
            answer["reason"] = "Guaranteed to fit the entire budget."
            message["content"] = json.dumps(answer)
        return httpx.Response(response.status_code, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as client:
        services, model = setup(config(), client)
        graph = build_provider_workflow(model, InMemorySaver(), services)
        result = graph.invoke({"user_message": "Test"}, {"configurable": {"thread_id": fault}})

    assert base.roles == ["SupervisorDecision", "OfferRanking", "OfferRanking", "Schedule"]
    assert services.tool_calls == ["transport", "hotels", "places"]
    assert result["status"] == "draft_ready_with_warnings"
    assert len(result["hotels"]) == 16
    assert [offer["name"] for offer in result["hotels"][:2]] == ["Hotel 2", "Hotel 1"]
    assert all(offer["hotel_class"] == 3 for offer in result["hotels"])
    assert all("Guaranteed" not in offer["recommendation_reason"] for offer in result["hotels"])
    assert result["agent_usage"]["hotels"]["total_tokens"] == 200
    assert result["costs"]["budget_status"] == "unknown"
    assert any("Hotel model ranking rejected" in warning for warning in result["warnings"])
