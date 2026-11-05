"""Explicit four-agent check using real retrieval, with assumed train prices by default."""
import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import sys
import traceback
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.checkpoint.memory import InMemorySaver
from backend.config import Settings
from backend.llm import create_model
from backend.providers.session import TravelProviderSession, jaipur_probe_bindings
from backend.runtime import build_provider_workflow
from scripts.connected_recovery import load_itinerary_resume

STATE_FIELDS = ("status", "preferences", "supervisor_decision", "model_usage", "agent_usage", "specialist_error", "supervisor_http_status", "input_error",
                "supervisor_error_detail", "warnings", "trace", "transport", "hotels", "places", "itinerary", "costs", "missing_fields")


def write_report(folder, report, secrets):
    content = json.dumps(report, indent=2, ensure_ascii=False)
    for secret in secrets:
        if secret:
            content = content.replace(secret, "[REDACTED]")
    (folder / "report.json").write_text(content, encoding="utf-8")
    (folder / "report.html").write_text("<!doctype html><html lang='en'><meta charset='utf-8'><title>Connected workflow check</title>"
        "<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:32px auto;padding:0 18px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}</style>"
        "<h1>Four-agent connected workflow check</h1><p>Train prices in mock mode are <strong>ASSUMED DEMO FARES</strong>. "
        "Hotel/flight quotes may have unverified passenger/tax scope. Real budget fit remains unknown. No reservation or payment occurred.</p>"
        "<h2>Checks, workflow, normalized results and matching request inputs</h2><pre>" + escape(content) + "</pre></html>", encoding="utf-8")


def run_check(settings, message, *, transport_mode="train", model=None, providers=None, resume_data=None):
    folder = settings.data_path / "reports" / ("connected_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6])
    folder.mkdir(parents=True)
    secrets = [getattr(settings, k).get_secret_value() for k in ("groq_api_key", "serpapi_api_key", "railradar_api_key")]
    report = {"check": "checkpoint10_connected", "outcome": "NOT_COMPLETED", "input": message,
        "fare_mode": settings.train_fare_mode, "model": settings.groq_model, "workflow": {}, "requests": {},
        "limits": {"groq_calls": 5, "serpapi_requests": 4, "railradar_requests": 6 if settings.train_fare_mode == "mock" else 8},
        "limitations": ["Explicit Delhi/Jaipur airport/station bindings; arbitrary location selection remains pending.",
                        "One destination; provider search order is deterministic Python, not an LLM tool-calling loop.",
                        "This is not the FastAPI/Streamlit product. Locks, versions, export and weather remain pending.",
                        "Each live rerun spends fresh requests. No automatic HTTP retries or synthetic schedule/place fallback."]}
    if resume_data is not None:
        seed, history, fare_mode = resume_data
        if settings.train_fare_mode != fare_mode:
            raise ValueError("Saved fare mode must be preserved")
        transport_mode = seed["preferences"]["transport_mode"]
        report.update(previous_run=history, continuation="itinerary_only",
            limits={"groq_calls": 2, "serpapi_requests": 0 if seed["places"] else 1, "railradar_requests": 0})
    write_report(folder, report, secrets)
    service = providers or TravelProviderSession(settings, jaipur_probe_bindings())
    try:
        with service:
            model = model if model is not None else create_model(settings)
            graph = build_provider_workflow(model, InMemorySaver(), service)
            config = {"configurable": {"thread_id": uuid4().hex}, "recursion_limit": 30}
            observed = dict(seed) if resume_data is not None else {}
            if resume_data is not None:
                # LangGraph resumes after the last completed node. No Supervisor,
                # transport worker or hotel worker executes in this continuation.
                graph.update_state(config, seed, as_node="hotels")
                print("Resuming Itinerary only; reusing saved transport and hotels...", flush=True)
            else:
                print("Starting Supervisor and connected provider workflow...", flush=True)
            for update in graph.stream(None if resume_data is not None else {"user_message": message}, config, stream_mode="updates"):
                for node, values in update.items():
                    if node == "__interrupt__":
                        report["clarification"] = [i.value for i in values]
                    else:
                        observed.update(values)
                        failed = values.get("model_failed") or values.get("supervisor_failed")
                        print(node + (": failed; details saved in report" if failed else ": completed"), flush=True)
                report["workflow"] = {key: observed.get(key) for key in STATE_FIELDS}
                report["requests"], report["provider_errors"] = service.audit(), service.errors
                write_report(folder, report, secrets)
            result = graph.get_state(config).values
            report["workflow"] = {key: result.get(key) for key in STATE_FIELDS}
            itinerary, costs = result.get("itinerary") or {}, result.get("costs") or {}
            all_offers = result.get("transport", []) + result.get("hotels", []) + result.get("places", [])
            checks = {"draft_created": result.get("status") in ("draft_ready", "draft_ready_with_warnings"),
                "no_timing_errors": bool(itinerary) and not itinerary.get("validation_errors"),
                "real_schedule_place_sources": bool(all_offers) and all(not o["source"]["synthetic"] for o in all_offers),
                "requested_mode_preserved": result.get("preferences", {}).get("transport_mode") == transport_mode,
                "four_roles_reported_usage": bool(result.get("model_usage")) and all(result.get("agent_usage", {}).get(k) for k in ("transport", "hotels", "itinerary")),
                "no_false_affordability": costs.get("budget_status") == "unknown" and costs.get("complete_subtotal") is None}
            if resume_data is not None:
                checks.pop("four_roles_reported_usage")
                checks["itinerary_reported_usage"] = bool(result.get("agent_usage", {}).get("itinerary"))
                checks["saved_recommendations_preserved"] = all(result.get(key) == seed[key] for key in ("transport", "hotels", "preferences"))
                checks["no_transport_or_hotel_search"] = not any(t in ("transport", "hotels") for t in service.tool_calls) and not service.audit()["railradar"]
                checks["bounded_place_search"] = len(service.audit()["serpapi"]) <= report["limits"]["serpapi_requests"]
            if transport_mode == "train" and settings.train_fare_mode == "mock":
                checks["assumed_fares_disclosed"] = itinerary.get("contains_assumed_prices") is True and bool(costs.get("assumed_components"))
            report["checks"] = checks
            report["outcome"] = "PASS_CONNECTED_CHECKS" if all(checks.values()) else "REVIEW_REQUIRED"
            if (result.get("specialist_error") or {}).get("http_status") == 429:
                report["outcome"] = "MODEL_RATE_LIMITED"
            usage = [result.get("model_usage", {}), *result.get("agent_usage", {}).values()]
            known = [u["total_tokens"] for u in usage if "total_tokens" in u]
            report["reported_total_tokens"] = sum(known) if known else None
            report["usage_note"] = "Known provider counters only; any unreported consumption is unknown, not zero."
    except KeyboardInterrupt:
        report["outcome"] = "INTERRUPTED"
    except Exception as exc:
        report.update(outcome="CONFIGURATION_OR_LOCAL_ERROR", error_type=type(exc).__name__,
            error_locations=[{"file": Path(f.filename).name, "function": f.name, "line": f.lineno} for f in traceback.extract_tb(exc.__traceback__)])
    finally:
        report["requests"], report["provider_errors"], report["tool_calls"] = service.audit(), service.errors, service.tool_calls
        write_report(folder, report, secrets)
    with ZipFile(folder / "share_results.zip", "w", ZIP_DEFLATED) as zipped:
        for name in ("report.json", "report.html"):
            zipped.write(folder / name, name)
    print("Outcome:", report["outcome"])
    print("Reported total tokens:", report.get("reported_total_tokens", "unknown"))
    print("Provider request counts:", {k: len(v) for k, v in service.audit().items()})
    print("Report:", folder / "report.html")
    print("Share only:", folder / "share_results.zip")
    return 0 if report["outcome"] == "PASS_CONNECTED_CHECKS" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--transport-mode", choices=("train", "flight", "compare"), default="train")
    parser.add_argument("--fare-mode", choices=("mock", "live"), default="mock")
    parser.add_argument("--departure", type=date.fromisoformat)
    parser.add_argument("--resume-report", type=Path, help="Live continuation of only a failed Itinerary step from a saved connected report")
    args = parser.parse_args(argv)
    if args.resume_report is not None:
        supplied = argv if argv is not None else sys.argv[1:]
        if args.live or args.departure or any(a.split("=", 1)[0] in ("--transport-mode", "--fare-mode") for a in supplied):
            parser.error("--resume-report is a live continuation; do not combine it with new-trip options")
        try:
            resume_data = load_itinerary_resume(args.resume_report)
        except Exception as exc:
            print("Resume validation failed (" + type(exc).__name__ + "); no keys loaded or requests made.")
            return 2
        return run_check(Settings(train_fare_mode=resume_data[2]), "Continue saved Itinerary step", resume_data=resume_data)
    if not args.live:
        print("Preview: zero calls, no keys loaded. --live enables <=5 Groq calls, <=4 SerpApi calls,")
        print("and <=6 RailRadar requests with mock fares (<=8 only with explicit --fare-mode live).")
        print("Default: Delhi → Jaipur, train CC, assumed demo fares. No paid fare endpoint in mock mode.")
        print("--resume-report PATH is a LIVE continuation: <=2 Groq calls and <=1 Maps call; no train/hotel searches.")
        return 0
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    day = args.departure or today + timedelta(days=14)
    if day <= today:
        parser.error("--departure must be in the future")
    travel = {"train": "Travel by train in CC class.", "flight": "Travel by Economy flight, sort flight options by price.",
              "compare": "Compare CC trains and Economy flights; sort flight options by price."}[args.transport_mode]
    message = (f"Plan Delhi to Jaipur leaving {day.isoformat()} and returning {(day + timedelta(days=3)).isoformat()} for 2 adults. "
        + travel + " Exactly 3-star hotel, INR 2000–4000 per night, guest rating at least 4.2 out of 5. "
        "Total budget INR 25000, currency INR. Interests: history. Relaxed pace.")
    return run_check(Settings(train_fare_mode=args.fare_mode), message, transport_mode=args.transport_mode)


if __name__ == "__main__":
    raise SystemExit(main())
