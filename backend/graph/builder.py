"""Readable orchestration with injected workers and optional live intake rules.

An optional Supervisor turns natural language into validated preference updates.
Specialists may be fixture workers or real agents. runtime.py supplies the
provider-backed composition; graph state never contains provider credentials.
"""
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from backend.graph.state import TripState
from backend.agents.supervisor import SupervisorTurn
from backend.llm import ModelCallError
from backend.schemas import HotelOffer, TransportOffer, TripPreferences
from backend.services.costs import summarize_costs
from backend.services.replanning import affected_components
from backend.services.offer_filters import transport_leg
from backend.services.hotel_dates import stay_preferences

TransportWorker = Callable[[TripPreferences], list[TransportOffer]]
HotelWorker = Callable[[TripPreferences], list[HotelOffer]]
ItineraryWorker = Callable[[TripState], dict]


def prepare(state: TripState) -> dict:
    previous = TripPreferences.model_validate(state.get("preferences", {}))
    try:
        preferences = TripPreferences.model_validate(previous.model_dump() | state.get("request_patch", {}))
    except ValidationError as exc:
        # Do not retain raw invalid input or exception text in the response.
        fields = sorted({str(e["loc"][0]) if e["loc"] else "request constraints"
                         for e in exc.errors(include_input=False)})
        return {"request_patch": {}, "input_error": "Please correct: " + ", ".join(fields),
                "missing_fields": previous.missing_required(), "status": "needs_input",
                "trace": ["Input validation requested clarification."]}
    first_plan = "preferences" not in state or not state.get("itinerary")
    affected = ({"transport", "hotels", "places", "weather", "itinerary", "costs"}
                if first_plan else affected_components(previous, preferences))
    # Places/weather work belongs inside the Itinerary specialist. Pass its
    # invalidation flags through state; no separate place/weather agent exists.
    pending = [name for name in ("transport", "hotels", "itinerary") if name in affected]
    updates = {"preferences": preferences.model_dump(mode="json"), "request_patch": {},
               "missing_fields": preferences.missing_required(), "input_error": None,
               "pending": pending, "invalidated": sorted(affected), "warnings": [],
               "agent_usage": {}, "model_failed": False, "specialist_error": None,
               "status": "needs_input" if preferences.missing_required() else "planning",
               "trace": (["Supervisor interpreted the user request."] if state.get("supervisor_decision") else [])
                        + ["Validated structured preferences."]}
    # Invalidated data must not be offered as fresh evidence during replanning.
    if "transport" in affected:
        updates["transport"] = []
    if "hotels" in affected:
        updates["hotels"] = []
    if "itinerary" in affected:
        updates["itinerary"] = None
    if "costs" in affected:
        updates["costs"] = None
    return updates


def clarify(state: TripState) -> dict:
    decision = state.get("supervisor_decision") or {}
    response = interrupt({"kind": "clarification", "missing_fields": state.get("missing_fields", []),
                          "message": state.get("input_error") or decision.get("clarification_question") or "Please supply the missing trip details."})
    # The node restarts when resumed. It has no side effects before interrupt().
    if isinstance(response, str):
        return {"user_message": response, "request_patch": {}}
    if not isinstance(response, dict):
        return {"request_patch": {}, "input_error": "Reply with structured trip fields.",
                "status": "needs_input"}
    return {"request_patch": response}


def dispatch(state: TripState) -> str:
    if state.get("input_error") or state.get("missing_fields"):
        return "clarify"
    if state.get("model_failed"):
        return "finalize"
    return state["pending"][0] if state.get("pending") else "finalize"


def build_workflow(transport_worker: TransportWorker, hotel_worker: HotelWorker,
                   itinerary_worker: ItineraryWorker, checkpointer,
                   supervisor_worker: Callable[[str, TripPreferences], SupervisorTurn] | None = None,
                   *, destination_timezone="Asia/Kolkata", require_search_preferences=False):
    """Workers do the task; this graph enforces the sequence and state updates.

    The caller owns the checkpointer's lifetime. No in-memory fallback silently
    substitutes for durable storage. Checkpoint 05 can inject all four real
    LLM roles with synthetic travel evidence, or use zero-call demo workers.
    """
    def supervise(state: TripState) -> dict:
        message = state.get("user_message", "")
        if not message:
            return {"supervisor_failed": False, "message_only": False,
                    "agent_usage": {}, "model_failed": False, "specialist_error": None,
                    "supervisor_decision": None, "model_usage": {}, "supervisor_http_status": None,
                    "supervisor_error_detail": None}
        if state.get("request_patch"):
            return {"user_message": "", "supervisor_failed": True, "status": "supervisor_error",
                    "agent_usage": {}, "model_failed": False, "specialist_error": None,
                    "warnings": ["Supply either a user message or a structured patch, not both."],
                    "supervisor_http_status": None, "supervisor_error_detail": None}
        try:
            if supervisor_worker is None:
                raise ModelCallError("Natural-language intake is not configured for this graph.")
            turn = supervisor_worker(message, TripPreferences.model_validate(state.get("preferences", {})))
        except ModelCallError as exc:
            return {"user_message": "", "supervisor_failed": True, "status": "supervisor_error",
                    "agent_usage": {}, "model_failed": False, "specialist_error": None,
                    "warnings": [str(exc)], "trace": ["Supervisor failed; prior preferences preserved."],
                    "supervisor_decision": exc.parsed_decision, "model_usage": exc.model_usage or {}, "supervisor_http_status": exc.http_status,
                    "supervisor_error_detail": exc.provider_error}
        message_only = turn.decision.intent in ("question", "unsupported")
        return {"user_message": "", "request_patch": turn.patch, "supervisor_failed": False,
                "agent_usage": {}, "model_failed": False, "specialist_error": None,
                "message_only": message_only, "supervisor_decision": turn.decision.model_dump(),
                "supervisor_http_status": None,
                "supervisor_error_detail": None,
                "model_usage": turn.usage, "status": "message_only" if message_only else "intake_complete",
                "warnings": [], "trace": ["Supervisor interpreted the user request."]}

    def after_supervisor(state: TripState) -> str:
        return END if state.get("supervisor_failed") or state.get("message_only") else "prepare"

    def prepare_step(state):
        updates = prepare(state)
        if require_search_preferences and not updates.get("input_error"):
            p = TripPreferences.model_validate(updates["preferences"])
            extra = [field for field in ("transport_mode", "currency") if getattr(p, field) is None]
            if p.transport_mode in ("train", "compare") and not p.train_class:
                extra.append("train_class")
            if p.departure_date and p.departure_date < datetime.now(ZoneInfo(destination_timezone)).date():
                extra.append("departure_date")
                updates["input_error"] = "Please provide a departure date that is not in the past."
            updates["missing_fields"] += extra
            if updates["missing_fields"]:
                updates["status"] = "needs_input"
        return updates

    def model_failure(state, role, exc, worker):
        return {"model_failed": True, "specialist_error": {"role": role, "http_status": exc.http_status,
                    "details": exc.provider_error, "message": str(exc)},
                "warnings": state.get("warnings", []) + list(getattr(worker, "warnings", [])) + [str(exc)],
                "agent_usage": state.get("agent_usage", {}) | {role: {
                    key: getattr(worker, "usage", {}).get(key, 0) + (exc.model_usage or {}).get(key, 0)
                    for key in set(getattr(worker, "usage", {})) | set(exc.model_usage or {})}},
                "trace": state["trace"] + [role + " model failed; further model work stopped."]}

    def transport(state: TripState) -> dict:
        try:
            offers = transport_worker(TripPreferences.model_validate(state["preferences"]))
            data = [TransportOffer.model_validate(o).model_dump(mode="json") for o in offers]
            warnings = list(getattr(transport_worker, "warnings", [])) + ([] if data else ["No transport offers returned."])
        except ModelCallError as exc:
            return model_failure(state, "transport", exc, transport_worker) | {"transport": []}
        except (ValueError, OSError, TimeoutError):
            data, warnings = [], ["Transport step failed; no replacement offers were invented."]
        pending = [p for p in state["pending"] if p != "transport"]
        extra = {}
        if state.get("hotels") and data:
            try:
                stay = stay_preferences(TripPreferences.model_validate(state["preferences"]), data, destination_timezone)
                incompatible = any(h["check_in"] != stay.departure_date.isoformat() or h["check_out"] != stay.return_date.isoformat() for h in state["hotels"])
            except ValueError:
                incompatible = True
            if incompatible:
                extra = {"hotels": [], "itinerary": None, "costs": None,
                         "invalidated": sorted(set(state.get("invalidated", [])) | {"hotels", "itinerary", "costs"})}
                pending = ["hotels", "itinerary"]
                warnings.append("Changed transport requires different hotel dates; refreshing the stay.")
        return {**extra, "transport": data, "pending": pending,
                "agent_usage": state.get("agent_usage", {}) | {"transport": getattr(transport_worker, "usage", {})},
                "warnings": state.get("warnings", []) + warnings,
                "trace": state["trace"] + ["Transport step completed."]}

    def hotels(state: TripState) -> dict:
        try:
            p = TripPreferences.model_validate(state["preferences"])
            stay = stay_preferences(p, state.get("transport", []), destination_timezone)
            offers = hotel_worker(stay)
            data = [HotelOffer.model_validate(o).model_dump(mode="json") for o in offers]
            warnings = list(getattr(hotel_worker, "warnings", [])) + ([] if data else ["No hotel offers returned."])
            legs = {transport_leg(TransportOffer.model_validate(o), p) for o in state.get("transport", [])}
            if not {"outbound_transport", "return_transport"}.issubset(legs):
                warnings.append("Hotel search uses requested trip dates because transport coverage is incomplete.")
        except ModelCallError as exc:
            return model_failure(state, "hotels", exc, hotel_worker) | {"hotels": []}
        except (ValueError, OSError, TimeoutError):
            data, warnings = [], ["Hotel step failed; no replacement offers were invented."]
        return {"hotels": data, "pending": [p for p in state["pending"] if p != "hotels"],
                "agent_usage": state.get("agent_usage", {}) | {"hotels": getattr(hotel_worker, "usage", {})},
                "warnings": state.get("warnings", []) + warnings,
                "trace": state["trace"] + ["Hotel step completed."]}

    def itinerary(state: TripState) -> dict:
        try:
            draft = itinerary_worker(state)
            if not isinstance(draft, dict):
                raise ValueError("Invalid itinerary worker output")
            warnings = []
        except ModelCallError as exc:
            return model_failure(state, "itinerary", exc, itinerary_worker) | {"itinerary": None}
        except (ValueError, OSError, TimeoutError):
            draft, warnings = None, ["Itinerary step failed; draft is unavailable."]
        warnings += (draft or {}).get("warnings", []) + (draft or {}).get("validation_errors", [])
        return {"itinerary": draft, "pending": [p for p in state["pending"] if p != "itinerary"],
                "places": (draft or {}).get("places", state.get("places", [])),
                "agent_usage": state.get("agent_usage", {}) | {"itinerary": getattr(itinerary_worker, "usage", {})},
                "warnings": state.get("warnings", []) + warnings,
                "trace": state["trace"] + ["Itinerary step completed."]}

    def finalize(state: TripState) -> dict:
        preferences = TripPreferences.model_validate(state["preferences"])
        draft, quotes = state.get("itinerary") or {}, {}
        ids = draft.get("recommended_offer_ids", {})
        # Recommendations are supplied by the ranked-offer scheduling path;
        # legacy routing-only fixtures have no selections and keep costs unknown.
        for data in state.get("transport", []):
            offer = TransportOffer.model_validate(data)
            leg = transport_leg(offer, preferences)
            if leg and ids.get(leg) == offer.id:
                quotes[leg] = offer.price
        for data in state.get("hotels", []):
            offer = HotelOffer.model_validate(data)
            if ids.get("hotel_stay") == offer.id:
                quotes["hotel_stay"] = offer.price
        costs = summarize_costs(quotes, preferences.currency, preferences.budget_total).model_dump(mode="json") if preferences.currency else None
        warnings = list(state.get("warnings", []))
        status = "workflow_complete"
        if draft.get("plan_status"):
            status = "draft_ready" if draft["plan_status"] == "valid_draft" and len(quotes) == 3 else "draft_needs_review"
            if costs is None or costs["complete_subtotal"] is None:
                warnings.append("Complete transport/hotel cost is unverified.")
            elif costs["budget_status"] == "over_budget":
                warnings.append("Recommended transport/hotel subtotal exceeds the stated budget.")
                status = "draft_needs_review"
            if costs and costs["assumed_components"]:
                warnings.append(costs["pricing_notice"])
                if costs["illustrative_budget_status"] == "over_assumed_budget":
                    warnings.append("Illustrative subtotal exceeds the budget under the demo assumptions.")
                    status = "draft_needs_review"
            if status == "draft_ready" and warnings:
                status = "draft_ready_with_warnings"
        if state.get("model_failed"):
            status = "partial_results"
        return {"status": status, "costs": costs, "warnings": warnings,
                "trace": state["trace"] + ["Draft recommendation finalized; bookings, locks and version storage are not applied."]}

    builder = StateGraph(TripState)
    builder.add_node("supervisor", supervise)
    builder.add_node("prepare", prepare_step)
    builder.add_node("clarify", clarify)
    builder.add_node("transport", transport)
    builder.add_node("hotels", hotels)
    builder.add_node("itinerary", itinerary)
    builder.add_node("finalize", finalize)
    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges("supervisor", after_supervisor, {END: END, "prepare": "prepare"})
    builder.add_edge("clarify", "supervisor")
    routes = {name: name for name in ("clarify", "transport", "hotels", "itinerary", "finalize")}
    for node in ("prepare", "transport", "hotels", "itinerary"):
        builder.add_conditional_edges(node, dispatch, routes)
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer)
