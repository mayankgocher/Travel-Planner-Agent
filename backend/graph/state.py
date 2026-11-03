"""JSON-compatible shared state; no credentials are stored in the graph."""
from typing import Any, TypedDict


class TripState(TypedDict, total=False):
    request_patch: dict[str, Any]
    preferences: dict[str, Any]
    missing_fields: list[str]
    input_error: str | None
    pending: list[str]
    invalidated: list[str]
    transport: list[dict[str, Any]]
    hotels: list[dict[str, Any]]
    itinerary: dict[str, Any] | None
    costs: dict[str, Any] | None
    warnings: list[str]
    trace: list[str]
    status: str
