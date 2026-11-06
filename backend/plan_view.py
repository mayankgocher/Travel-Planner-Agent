"""Project graph results to display fields. Never expose prompts or model notes."""
from datetime import timedelta
from urllib.parse import urlsplit

from backend.schemas import TransportOffer, TripPreferences
from backend.services.offer_filters import transport_leg

HOURS_WARNING = "Opening hours unverified: "


def public_source(record: dict) -> dict:
    source = dict(record)
    if source.get("url"):
        url = urlsplit(source["url"])
        source["url"] = (url._replace(query="", fragment="").geturl()
                         if url.scheme in ("https", "http") and url.hostname and not url.username and not url.password
                         else None)
    return source


def public_offer(offer: dict) -> dict:
    result = {key: value for key, value in offer.items() if key != "recommendation_reason"}
    result["price"] = {key: value for key, value in offer["price"].items() if key != "notes"}
    result["source"] = public_source(offer["source"])
    return result


def plan_view(state: dict, preferences: TripPreferences) -> dict:
    status = state.get("status", "draft_needs_review")
    draft = state.get("itinerary") or {}
    ids = draft.get("recommended_offer_ids", {})
    transport = []
    for component, direction in (("outbound_transport", "Outbound"), ("return_transport", "Return")):
        matches = [offer for offer in state.get("transport", [])
                   if transport_leg(TransportOffer.model_validate(offer), preferences) == component]
        selected = next((offer for offer in matches if offer["id"] == ids.get(component)), None)
        # Partial results can still show the best available option as a draft.
        if selected is None and not ids.get(component) and matches:
            selected = matches[0]
        if selected is not None:
            transport.append(public_offer(selected) | {"direction": direction})

    hotels = state.get("hotels", [])
    hotel = next((offer for offer in hotels if offer["id"] == ids.get("hotel_stay")), None)
    if hotel is None and not ids.get("hotel_stay") and hotels:
        hotel = hotels[0]

    warnings = list(dict.fromkeys(state.get("warnings") or []))
    warnings = [w for w in warnings if not w.startswith(HOURS_WARNING)]
    model_error = state.get("specialist_error") or {}
    if model_error.get("http_status") == 429:
        warnings.append("Groq rate-limited this request. Available search results are shown below.")
    if state.get("input_error"):
        warnings.append(state["input_error"])

    days = []
    # An unresolved schedule is not presented as a usable itinerary.
    if draft.get("plan_status") == "valid_draft" and not draft.get("validation_errors"):
        days = [{"date": (preferences.departure_date + timedelta(days=i)).isoformat(), "activities": []}
                for i in range((preferences.return_date - preferences.departure_date).days + 1)]
        by_date = {day["date"]: day["activities"] for day in days}
        places = {place["id"]: place for place in state.get("places", [])}
        unknown_hours = {w.removeprefix(HOURS_WARNING) for w in draft.get("warnings", [])
                         if w.startswith(HOURS_WARNING)}
        for activity in sorted(draft["activities"], key=lambda row: (row["date"], row["start"])):
            place_id = activity["place_id"]
            place = places[place_id]
            by_date[activity["date"]].append({
                "start": activity["start"], "end": activity["end"], "name": place["name"],
                "hours_unverified": place_id in unknown_hours,
                "source": public_source(place["source"]),
            })

    return {
        "status": status,
        "trip": preferences.model_dump(mode="json", include={
            "origin", "destination", "departure_date", "return_date", "adults", "budget_total", "currency",
        }),
        "transport": transport,
        "hotel": public_offer(hotel) if hotel is not None else None,
        "costs": state.get("costs"),
        "days": days,
        "warnings": warnings,
    }
