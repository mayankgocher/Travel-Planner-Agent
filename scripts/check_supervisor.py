"""One explicitly enabled Groq call, then synthetic downstream workflow only."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import InMemorySaver

from backend import demo_workers
from backend.agents.supervisor import Supervisor
from backend.config import Settings
from backend.graph.builder import build_workflow
from backend.llm import create_model

MESSAGE = ("Plan Delhi to Jaipur for two adults, departing 10 February 2027 and returning "
           "14 February 2027. Prefer trains, exactly 3-star hotels, 2000 to 4000 INR per "
           "night, guest rating at least 4 out of 5. Transport and hotel budget 25000 INR. "
           "Interest: history.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Permit one Groq request; downstream workers stay synthetic")
    args = parser.parse_args()
    if not args.live:
        print("Preview only. No key loaded, model instantiated or API request made.")
        print("Live check uses one Groq Supervisor call; it is not a real travel search.")
        return 0

    settings = Settings()
    report = {"check": "checkpoint04_supervisor", "live_supervisor": True,
              "synthetic_downstream": True, "notice": demo_workers.LABEL,
              "model": settings.groq_model, "automatic_retries": 0,
              "at": datetime.now(timezone.utc).isoformat(), "input": MESSAGE}
    try:
        graph = build_workflow(demo_workers.transport, demo_workers.hotels, demo_workers.itinerary,
                               InMemorySaver(), Supervisor(create_model(settings), settings.app_timezone))
        result = graph.invoke({"user_message": MESSAGE},
                              {"configurable": {"thread_id": str(uuid4())}, "recursion_limit": 30})
        for key in ("status", "preferences", "supervisor_decision", "supervisor_http_status", "model_usage", "trace", "warnings"):
            report[key] = result.get(key)
        expected = {"origin": "Delhi", "destination": "Jaipur", "adults": 2,
                    "departure_date": "2027-02-10", "return_date": "2027-02-14",
                    "transport_mode": "train", "hotel_class": 3, "hotel_class_rule": "exact",
                    "nightly_min": "2000", "nightly_max": "4000", "guest_rating_min": 4.0,
                    "budget_total": "25000", "currency": "INR", "interests": ["history"]}
        preferences = result.get("preferences", {})
        checks = {key: preferences.get(key) == value for key, value in expected.items()}
        for key in ("nightly_min", "nightly_max", "budget_total"):
            try:
                checks[key] = Decimal(str(preferences.get(key))) == Decimal(expected[key])
            except InvalidOperation:
                checks[key] = False
        checks["interests"] = [s.casefold() for s in preferences.get("interests", [])] == ["history"]
        checks["workflow_reached_end"] = result.get("status") == "workflow_complete"
        report["checks"] = checks
        report["outcome"] = "PASS_CHECKS" if all(checks.values()) else "REVIEW_REQUIRED"
        # These are usage counters for this run, not full-app cost measurements.
        # Missing usage after a failed request means unknown consumption, not zero.
        if result.get("__interrupt__"):
            report["clarification"] = [i.value for i in result["__interrupt__"]]
    except Exception as exc:
        # Console/report contain no exception text, provider bodies or tracebacks.
        report.update(outcome="CONFIGURATION_OR_LOCAL_ERROR", error_type=type(exc).__name__)

    folder = settings.data_path / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("supervisor_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6] + ".json")
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Outcome:", report["outcome"])
    print("Usage:", report.get("model_usage") or "Unknown / no completed request reported")
    print("Share only this JSON report:", path)
    print("No real transport, hotel or place searches were made.")
    return 0 if report["outcome"] == "PASS_CHECKS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
