"""One explicit dependency table; no LLM is needed to calculate invalidation."""
from backend.schemas import Component, Selection, TripPreferences

DEPENDENCIES = {
    "origin": {"transport", "itinerary", "costs"},
    "destination": {"transport", "hotels", "places", "weather", "itinerary", "costs"},
    "departure_date": {"transport", "hotels", "weather", "itinerary", "costs"},
    "return_date": {"transport", "hotels", "weather", "itinerary", "costs"},
    "adults": {"transport", "hotels", "itinerary", "costs"},
    "currency": {"transport", "hotels", "itinerary", "costs"},
    "budget_total": {"transport", "hotels", "itinerary", "costs"},
    "transport_mode": {"transport", "itinerary", "costs"},
    "train_class": {"transport", "itinerary", "costs"},
    "flight_class": {"transport", "itinerary", "costs"},
    "flight_sort_by": {"transport", "itinerary", "costs"},
    "flight_max_price": {"transport", "itinerary", "costs"},
    "hotel_class": {"hotels", "itinerary", "costs"},
    "hotel_class_rule": {"hotels", "itinerary", "costs"},
    "nightly_min": {"hotels", "itinerary", "costs"},
    "nightly_max": {"hotels", "itinerary", "costs"},
    "guest_rating_min": {"hotels", "itinerary", "costs"},
    "interests": {"places", "itinerary"},
    "pace": {"itinerary"},
}


def affected_components(before: TripPreferences, after: TripPreferences) -> set[str]:
    changed = {name for name in type(before).model_fields if getattr(before, name) != getattr(after, name)}
    return set().union(*(DEPENDENCIES[name] for name in changed))


def enforce_selection_locks(current: dict[Component, Selection],
                            proposed: dict[Component, Selection]) -> list[Component]:
    """Return blocked components; never mutate or silently unlock selections.

    This protects direct replacement/removal only. The graph must separately
    validate retained locked offers against changed dates, route and preferences.
    """
    blocked = []
    for component, selection in current.items():
        if selection.component != component:
            raise ValueError("Selection component does not match dictionary key")
        replacement = proposed.get(component)
        if replacement and replacement.component != component:
            raise ValueError("Proposed selection component does not match dictionary key")
        if selection.locked and (replacement is None or replacement.offer_id != selection.offer_id or not replacement.locked):
            blocked.append(component)
    return blocked
