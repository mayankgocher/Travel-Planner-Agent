"""Read only a failed connected check's normalized evidence, without loading keys."""
from datetime import datetime
import json
from pathlib import Path
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from backend.agents.ranking import incomplete_price_reason
from backend.schemas import HotelOffer, PlaceCandidate, TransportOffer, TripPreferences
from backend.services.hotel_dates import stay_preferences
from backend.services.offer_filters import eligible_hotels, eligible_transport, transport_leg

MAX_REPORT_BYTES = 8 * 1024 * 1024


def load_itinerary_resume(path):
    """Validate before any network call; do not renew timestamps or infer new data.

    This deliberately supports only the connected Delhi/Jaipur probe after an
    Itinerary model error. It is not general version restoration or replanning.
    """
    path = Path(path)
    if path.suffix.casefold() == ".zip":
        with ZipFile(path) as zipped:
            info = zipped.getinfo("report.json")
            if info.file_size > MAX_REPORT_BYTES:
                raise ValueError("Report is too large")
            payload = zipped.read(info)
    else:
        with path.open("rb") as stream:
            payload = stream.read(MAX_REPORT_BYTES + 1)
        if len(payload) > MAX_REPORT_BYTES:
            raise ValueError("Report is too large")
    report = json.loads(payload.decode("utf-8-sig"))
    if report.get("check") != "checkpoint10_connected":
        raise ValueError("Not a connected check report")
    state = report["workflow"]
    failure = state.get("specialist_error") or {}
    if state.get("status") != "partial_results" or failure.get("role") != "itinerary" or state.get("itinerary"):
        raise ValueError("Only a failed Itinerary model step can be resumed")
    p = TripPreferences.model_validate(state["preferences"])
    if (p.missing_required() or p.origin.casefold() != "delhi" or p.destination.casefold() != "jaipur"
            or p.transport_mode is None or p.currency is None
            or p.departure_date < datetime.now(ZoneInfo("Asia/Kolkata")).date()):
        raise ValueError("Saved probe preferences are unsupported or stale")
    transport = [TransportOffer.model_validate(o) for o in state["transport"]]
    hotels = [HotelOffer.model_validate(o) for o in state["hotels"]]
    places = [PlaceCandidate.model_validate(o) for o in state.get("places") or []]
    if not transport or not hotels:
        raise ValueError("Completed recommendations are missing")
    for items in (transport, hotels, places):
        if len({o.id for o in items}) != len(items) or any(o.source.synthetic for o in items):
            raise ValueError("Expected unique live evidence")
    if len(eligible_transport(transport, p)) != len(transport):
        raise ValueError("Saved transport no longer matches its preferences")
    if {transport_leg(o, p) for o in transport} != {"outbound_transport", "return_transport"}:
        raise ValueError("Both transport legs are required")
    stay = stay_preferences(p, transport, "Asia/Kolkata")
    if len(eligible_hotels(hotels, stay)) != len(hotels):
        raise ValueError("Saved hotels do not cover the transport-derived stay")
    fare_mode = report.get("fare_mode")
    if fare_mode not in ("mock", "live") or (fare_mode == "live" and any(o.price.pricing_mode == "demo" for o in transport)):
        raise ValueError("Invalid saved fare mode")
    # Older schema-valid explanations asserted budget fit with assumed/partial
    # quotes. Replace those explanations, not the evidence or ranking order.
    for offers in (transport, hotels):
        if any(not o.price.complete for o in offers):
            for offer in offers:
                offer.recommendation_reason = incomplete_price_reason(offers)
    warnings = [w for w in state.get("warnings", []) if isinstance(w, str) and w != failure.get("message")]
    warnings.append("Resumed from saved recommendations; train/hotel source timestamps were preserved, not refreshed. "
                    "Earlier incomplete-price explanations were replaced with explicit scope notices.")
    seed = {"user_message": "", "preferences": p.model_dump(mode="json"), "request_patch": {},
            "transport": [o.model_dump(mode="json") for o in transport],
            "hotels": [o.model_dump(mode="json") for o in hotels],
            "places": [o.model_dump(mode="json") for o in places], "itinerary": None, "costs": None,
            "pending": ["itinerary"], "invalidated": ["itinerary", "costs"] + ([] if places else ["places"]),
            "model_failed": False, "specialist_error": None, "agent_usage": {}, "model_usage": {},
            "missing_fields": [], "input_error": None, "status": "planning", "warnings": warnings,
            "trace": ["Resumed only the failed Itinerary step using validated saved recommendations."]}
    history = {"source_report": path.name, "reported_total_tokens": report.get("reported_total_tokens"),
               "request_counts": {k: len(v) for k, v in report.get("requests", {}).items()},
               "failed_role": "itinerary", "http_status": failure.get("http_status"),
               "note": "Previous-run counters are historical; they are excluded from this continuation's usage."}
    return seed, history, fare_mode
