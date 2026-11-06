"""Drive the browser form through FastAPI and the graph with fake provider HTTP."""
from datetime import date
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend import main
from test_connected import P, Responses, config, offline, setup


def patch_providers(monkeypatch, http):
    settings = config()
    service, model = setup(settings, http)
    monkeypatch.setattr(main, "Settings", lambda **_: settings)
    monkeypatch.setattr(main, "TravelProviderSession", lambda *args: service)
    monkeypatch.setattr(main, "create_model", lambda *args, **kwargs: model)
    return service


def test_browser_submit_runs_local_endpoint_and_existing_graph_once(monkeypatch):
    providers = Responses()
    with httpx.Client(transport=httpx.MockTransport(providers), trust_env=False) as http:
        service = patch_providers(monkeypatch, http)
        api = TestClient(main.app)
        post = httpx.Client.post
        submitted = []

        def browser_post(self, url, **kwargs):
            if url == "http://127.0.0.1:8000/plan":
                submitted.append(kwargs["json"])
                return api.request("POST", "/plan", **kwargs)
            return post(self, url, **kwargs)

        monkeypatch.setattr(httpx.Client, "post", browser_post)
        screen = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "frontend/app.py")).run()
        assert not screen.exception and not providers.calls
        screen.button[0].click().run()
        assert not screen.exception and not providers.calls
        screen.date_input[0].set_value(date.fromisoformat(P["departure_date"]))
        screen.date_input[1].set_value(date.fromisoformat(P["return_date"]))
        next(b for b in screen.button if b.label == "Generate plan").click().run(timeout=20)
        assert not screen.exception and not screen.error
        assert len(submitted) == 1 and submitted[0]["nightly_max"] == 4000
        assert providers.roles == ["OfferRanking", "OfferRanking", "Schedule"]
        assert service.tool_calls == ["transport", "hotels", "places"]
        assert any(x.value == "Invented hotel" for x in screen.text)
        assert any("Invented museum" in x.value for x in screen.markdown)
        assert len(screen.header) == 2  # Saved sample survives the live result.
        screen.run()
        assert len(submitted) == 1


@pytest.mark.parametrize("mode", ["flight", "compare"])
def test_api_uses_correct_transport_providers_and_safe_projection(monkeypatch, mode):
    handler = Responses(mode=mode)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        service = patch_providers(monkeypatch, http)
        payload = {k: P[k] for k in ("departure_date", "return_date", "adults", "hotel_class", "budget_total")}
        response = TestClient(main.app).post("/plan", json=payload | {"transport_mode": mode})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "draft_ready_with_warnings"
    assert len(result["transport"]) == 2 and result["days"][0]["activities"]
    assert result["costs"]["complete_subtotal"] is None
    assert len(service.audit()["railradar"]) == (0 if mode == "flight" else 4)
    assert len(service.audit()["serpapi"]) == 4
    if mode == "flight":
        assert all(leg["mode"] == "flight" for leg in result["transport"])
    assert not any(value in response.text for value in ("Test schedule; no booking.", "groq-secret", "recommendation_reason"))


def test_itinerary_rate_limit_returns_partial_offers_without_a_fake_schedule(monkeypatch):
    base = Responses()

    def handler(request):
        if request.url.host == "api.groq.com" and json.loads(request.content)["response_format"]["json_schema"]["name"] == "Schedule":
            return httpx.Response(429, json={"error": {"message": "Limit: groq-secret"}})
        return base(request)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        service = patch_providers(monkeypatch, http)
        response = TestClient(main.app).post("/plan", json={k: P[k] for k in ("departure_date", "return_date")})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "partial_results"
    assert result["hotel"] and len(result["transport"]) == 2
    assert result["days"] == [] and result["costs"]["complete_subtotal"] is None
    assert len(service.audit()["serpapi"]) == 2
    assert any("Groq rate-limited" in w for w in result["warnings"])
    assert "groq-secret" not in response.text


def test_health_and_invalid_dates_do_not_load_credentials(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Credentials must not be loaded")
    monkeypatch.setattr(main, "Settings", forbidden)
    client = TestClient(main.app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.post("/plan", json={"departure_date": P["return_date"], "return_date": P["departure_date"]}).status_code == 422
