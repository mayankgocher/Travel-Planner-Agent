"""Readable orchestration tested with injected, explicitly synthetic workers.

An optional Supervisor turns natural language into validated preference updates.
Other LLM specialists/provider adapters are not integrated yet.
"""
from collections.abc import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from backend.graph.state import TripState
from backend.agents.supervisor import SupervisorTurn
from backend.llm import ModelCallError
from backend.schemas import HotelOffer, TransportOffer, TripPreferences
from backend.services.costs import summarize_costs
from backend.services.replanning import affected_components

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
    return state["pending"][0] if state.get("pending") else "finalize"


def build_workflow(transport_worker: TransportWorker, hotel_worker: HotelWorker,
                   itinerary_worker: ItineraryWorker, checkpointer,
                   supervisor_worker: Callable[[str, TripPreferences], SupervisorTurn] | None = None):
    """Workers do the task; this graph enforces the sequence and state updates.

    The caller owns the checkpointer's lifetime. No in-memory fallback silently
    substitutes for durable storage. Only Supervisor has a live LLM path in
    checkpoint 04; demo specialists remain explicitly synthetic.
    """
    def supervise(state: TripState) -> dict:
        message = state.get("user_message", "")
        if not message:
            return {"supervisor_failed": False, "message_only": False,
                    "supervisor_decision": None, "model_usage": {}, "supervisor_http_status": None,
                    "supervisor_error_detail": None}
        if state.get("request_patch"):
            return {"user_message": "", "supervisor_failed": True, "status": "supervisor_error",
                    "warnings": ["Supply either a user message or a structured patch, not both."],
                    "supervisor_http_status": None, "supervisor_error_detail": None}
        try:
            if supervisor_worker is None:
                raise ModelCallError("Natural-language intake is not configured for this graph.")
            turn = supervisor_worker(message, TripPreferences.model_validate(state.get("preferences", {})))
        except ModelCallError as exc:
            return {"user_message": "", "supervisor_failed": True, "status": "supervisor_error",
                    "warnings": [str(exc)], "trace": ["Supervisor failed; prior preferences preserved."],
                    "supervisor_decision": None, "model_usage": {}, "supervisor_http_status": exc.http_status,
                    "supervisor_error_detail": exc.provider_error}
        message_only = turn.decision.intent in ("question", "unsupported")
        return {"user_message": "", "request_patch": turn.patch, "supervisor_failed": False,
                "message_only": message_only, "supervisor_decision": turn.decision.model_dump(),
                "supervisor_http_status": None,
                "supervisor_error_detail": None,
                "model_usage": turn.usage, "status": "message_only" if message_only else "intake_complete",
                "warnings": [], "trace": ["Supervisor interpreted the user request."]}

    def after_supervisor(state: TripState) -> str:
        return END if state.get("supervisor_failed") or state.get("message_only") else "prepare"

    def transport(state: TripState) -> dict:
        try:
            offers = transport_worker(TripPreferences.model_validate(state["preferences"]))
            data = [TransportOffer.model_validate(o).model_dump(mode="json") for o in offers]
            warnings = [] if data else ["No transport offers returned."]
        except (ValueError, OSError, TimeoutError):
            data, warnings = [], ["Transport step failed; no replacement offers were invented."]
        return {"transport": data, "pending": [p for p in state["pending"] if p != "transport"],
                "warnings": state.get("warnings", []) + warnings,
                "trace": state["trace"] + ["Transport step completed."]}

    def hotels(state: TripState) -> dict:
        try:
            offers = hotel_worker(TripPreferences.model_validate(state["preferences"]))
            data = [HotelOffer.model_validate(o).model_dump(mode="json") for o in offers]
            warnings = [] if data else ["No hotel offers returned."]
        except (ValueError, OSError, TimeoutError):
            data, warnings = [], ["Hotel step failed; no replacement offers were invented."]
        return {"hotels": data, "pending": [p for p in state["pending"] if p != "hotels"],
                "warnings": state.get("warnings", []) + warnings,
                "trace": state["trace"] + ["Hotel step completed."]}

    def itinerary(state: TripState) -> dict:
        try:
            draft = itinerary_worker(state)
            if not isinstance(draft, dict):
                raise ValueError("Invalid itinerary worker output")
            warnings = []
        except (ValueError, OSError, TimeoutError):
            draft, warnings = None, ["Itinerary step failed; draft is unavailable."]
        return {"itinerary": draft, "pending": [p for p in state["pending"] if p != "itinerary"],
                "warnings": state.get("warnings", []) + warnings,
                "trace": state["trace"] + ["Itinerary step completed."]}

    def finalize(state: TripState) -> dict:
        # Selection/ranking/offer compatibility are not implemented here yet.
        # Therefore this orchestration checkpoint cannot claim a payable total
        # by arbitrarily treating the first returned offer as a selection.
        preferences = TripPreferences.model_validate(state["preferences"])
        costs = summarize_costs({}, preferences.currency).model_dump(mode="json") if preferences.currency else None
        return {"status": "workflow_complete", "costs": costs,
                "trace": state["trace"] + ["Workflow complete; offer selection and plan validation still pending."]}

    builder = StateGraph(TripState)
    builder.add_node("supervisor", supervise)
    builder.add_node("prepare", prepare)
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
