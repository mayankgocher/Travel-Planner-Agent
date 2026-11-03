"""JSON-compatible shared state; no credentials are stored in the graph."""
from typing import Any, TypedDict


class TripState(TypedDict, total=False):
    user_message: str
    supervisor_decision: dict[str, Any] | None
    model_usage: dict[str, int]
    supervisor_failed: bool
    supervisor_http_status: int | None
    supervisor_error_detail: dict[str, str] | None
    message_only: bool
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
