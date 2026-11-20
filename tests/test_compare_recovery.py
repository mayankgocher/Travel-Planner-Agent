"""Exercise timed transport revisions against rejected structured model calls."""
import json

import httpx
import pytest

from test_airport_chat import AirportResponses, airport_queries, flight_routes, open_client
from test_connected import offline
from test_station_chat import lookup_queries, send

COMPARE_REQUEST = (
    "Compare trains and flights for a round trip from Delhi to Lucknow for 2 adults. "
    "Depart on 10 February 2027 and return on 13 February 2027. Use CC for trains and Economy for flights."
)


class RejectedRevision(AirportResponses):
    def __init__(self, failure):
        super().__init__([("update", {"train_class": "3A"})])
        self.failure = failure
        self.revising = False
        self.checked_both_modes = False

    def __call__(self, request):
        response = super().__call__(request)
        bits = request.url.path.split("/")
        if request.url.host == "api.railradar.in" and bits[-1] in ("99921", "99922"):
            body = response.json()
            body["data"]["train"]["availableClasses"] = ["CC", "3A"]
            return httpx.Response(200, json=body)
        if (request.url.host == "api.railradar.in" and request.url.path.endswith("/between/NDLS/LKO")
                and self.revising and self.failure == "itinerary_incompatible"):
            body = response.json()
            row = body["data"]["trains"][0]
            row["to"]["arrival"], row["duration"] = "15:15", 375
            return httpx.Response(200, json=body)
        if request.url.host == "api.groq.com" and self.revising:
            role = self.roles[-1]
            if role == "OfferRanking":
                wire = json.loads(request.content)
                candidates = json.loads(wire["messages"][1]["content"])["candidates"]
                self.checked_both_modes = {c["mode"] for c in candidates} == {"train", "flight"}
                if self.failure in ("ranking", "rate_limit"):
                    status = 400 if self.failure == "ranking" else 429
                    return httpx.Response(status, json={"error": {"message": "test response rejected groq-secret"}})
            if role == "Schedule" and self.failure.startswith("itinerary"):
                return httpx.Response(400, json={"error": {"message": "test response rejected groq-secret"}})
        return response


@pytest.mark.parametrize("failure", ["ranking", "itinerary", "itinerary_incompatible", "rate_limit"])
def test_comparison_revision_recovers_only_when_it_has_valid_evidence(monkeypatch, failure):
    handler = RejectedRevision(failure)
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        api = open_client(monkeypatch, http)
        waiting = send(api, COMPARE_REQUEST)
        assert "Confirm the destination station" in waiting["reply"]
        assert "SupervisorDecision" not in handler.roles
        session = waiting["session_id"]
        original = send(api, "LKO", session)["plan"]
        assert original["days"] and all(leg["travel_class"] == "CC" for leg in original["transport"])
        before = len(handler.calls)
        handler.revising = True
        response = send(api, "Compare both again using 3A for trains.", session)
    revised_calls = handler.calls[before:]
    assert handler.checked_both_modes and len(flight_routes(revised_calls)) == 2
    assert len([r for r in revised_calls if "/between/" in r.url.path]) == 2
    assert not airport_queries(revised_calls) and not lookup_queries(revised_calls)
    assert not any(r.url.params.get("engine") in ("google_hotels", "google_maps") for r in revised_calls)
    assert "groq-secret" not in str(response)
    if failure == "ranking":
        assert response["plan"]["days"] and all(leg["mode"] == "flight" for leg in response["plan"]["transport"])
        assert any("Fares were not used to compare modes" in w for w in response["plan"]["warnings"])
    elif failure == "itinerary":
        assert response["plan"]["days"] == original["days"]
        assert all(leg["travel_class"] == "3A" for leg in response["plan"]["transport"])
        assert any("Kept the previous activities" in w for w in response["plan"]["warnings"])
    else:
        assert response["plan"] == original
        warning = ("Itinerary planning could not finish (HTTP 400)." if failure == "itinerary_incompatible"
                   else "Transport ranking could not finish (HTTP 429).")
        assert warning in response["turn_warnings"]
        assert not any("Kept the previous activities" in w for w in response["turn_warnings"])
