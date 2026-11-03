"""Explicit live LLM check for all four roles; travel evidence stays synthetic."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import traceback
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import InMemorySaver
from backend import specialist_fixtures as fixtures
from backend.agents.hotel import HotelAgent
from backend.agents.itinerary import ItineraryAgent
from backend.agents.supervisor import Supervisor
from backend.agents.transportation import TransportationAgent
from backend.config import Settings
from backend.graph.builder import build_workflow
from backend.llm import create_model
from scripts.check_supervisor import MESSAGE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live:
        print("Preview: zero API calls. --live enables four Groq calls, plus at most one itinerary correction.")
        print("All transport, hotel and place evidence remains synthetic; no travel providers are contacted.")
        return 0
    settings = Settings()
    folder = settings.data_path / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("agents_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6] + ".json")
    report = {"check": "checkpoint05_four_agents", "synthetic_travel_data": True,
              "input": MESSAGE, "model": settings.groq_model, "outcome": "NOT_COMPLETED"}
    # Save before execution so a process interruption leaves an identifiable run.
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    stage = "creating model and graph"
    try:
        model = create_model(settings)
        graph = build_workflow(TransportationAgent(model, fixtures.transport), HotelAgent(model, fixtures.hotels),
            ItineraryAgent(model, fixtures.places, settings.app_timezone), InMemorySaver(), Supervisor(model, settings.app_timezone))
        stage = "executing graph"
        result = graph.invoke({"user_message": MESSAGE}, {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 30})
        for key in ("status", "preferences", "supervisor_decision", "model_usage", "agent_usage", "supervisor_error_detail",
                    "supervisor_http_status", "specialist_error", "trace", "warnings", "transport", "hotels", "itinerary", "costs"):
            report[key] = result.get(key)
        usage = [result.get("model_usage", {}), *result.get("agent_usage", {}).values()]
        known = [item["total_tokens"] for item in usage if "total_tokens" in item]
        report["reported_total_tokens"] = sum(known) if known else None
        report["usage_note"] = "Provider-reported usage includes locally rejected replies. Unreported consumption is unknown, not zero."
        checks = {"draft_validated": result.get("status") in ("draft_ready", "draft_ready_with_warnings"),
                  "synthetic_label": (result.get("itinerary") or {}).get("synthetic") is True,
                  "no_timing_errors": not (result.get("itinerary") or {}).get("validation_errors", ["missing draft"]),
                  "all_four_roles_reported_usage": bool(result.get("model_usage")) and all(result.get("agent_usage", {}).get(r) for r in ("transport", "hotels", "itinerary")),
                  "subtotal_verified": (result.get("costs") or {}).get("complete_subtotal") is not None,
                  "within_stated_budget": (result.get("costs") or {}).get("budget_status") == "within_budget"}
        report["checks"] = checks
        report["outcome"] = "PASS_CHECKS" if all(checks.values()) else "REVIEW_REQUIRED"
        if result.get("supervisor_http_status") or (result.get("specialist_error") or {}).get("http_status"):
            report["outcome"] = "PROVIDER_REQUEST_ERROR"
        if result.get("__interrupt__"):
            report["clarification"] = [i.value for i in result["__interrupt__"]]
    except Exception as exc:
        report.update(outcome="CONFIGURATION_OR_LOCAL_ERROR", error_type=type(exc).__name__, stage=stage,
            error_locations=[dict(file=Path(f.filename).name, function=f.name, line=f.lineno)
                             for f in traceback.extract_tb(exc.__traceback__)])
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Outcome:", report["outcome"])
    total = report.get("reported_total_tokens")
    print("Reported total tokens:", total if total is not None else "unknown")
    if report.get("supervisor_error_detail") or report.get("specialist_error"):
        print("Sanitized error:", report.get("supervisor_error_detail") or report.get("specialist_error"))
    print("Share only this JSON report:", path)
    print("All travel data were synthetic. No real travel searches or bookings occurred.")
    return 0 if report["outcome"] == "PASS_CHECKS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
