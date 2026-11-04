"""Explicit mock/live rail check, or zero-network replay of a saved rail report."""
import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import sys
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import PROJECT_ROOT, Settings
from backend.providers.http import ProviderError
from backend.providers.rail_http import RailRadarHttp
from backend.providers.railradar import CLASSES, RailRadarAdapter, StationBinding
from backend.schemas import TripPreferences, TrainTimetable, TransportOffer
from backend.services.demo_fares import apply_demo_fare
from backend.services.offer_filters import transport_leg


def write_report(folder, report, secret=""):
    content = json.dumps(report, indent=2, ensure_ascii=False)
    if secret:
        content = content.replace(secret, "[REDACTED]")
    (folder / "report.json").write_text(content, encoding="utf-8")
    clean = json.loads(content)
    rows = []
    for offer in clean.get("trains", []):
        values = (offer["train_number"], offer["train_name"], offer["departure_station"], offer["arrival_station"],
                  offer["departure"], offer["arrival"], offer["travel_class"], offer["price"].get("per_adult_amount"),
                  offer["price"]["amount"], "ASSUMED DEMO FARE" if offer["price"].get("pricing_mode") == "demo" else
                  "Unavailable" if offer["price"]["amount"] is None else "Provider quote / unverified scope")
        rows.append("<tr>" + "".join("<td>" + escape(str(v) if v is not None else "Unknown") + "</td>" for v in values) + "</tr>")
    headers = ("Train", "Name", "From", "To", "Departure", "Arrival", "Class", "Demo INR/adult", "INR for requested scope", "Price evidence")
    table = "<table><tr>" + "".join("<th>" + escape(h) + "</th>" for h in headers) + "</tr>" + "".join(rows) + "</table>"
    html = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Rail provider check</title>"
        "<style>body{font:16px/1.5 system-ui;margin:30px;padding:0 12px}table{border-collapse:collapse;font-size:14px}"
        "td,th{border:1px solid #ccc;padding:8px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}</style>"
        "<h1>RailRadar outbound retrieval check</h1><p>Outcome: <strong>" + escape(clean["outcome"]) + "</strong></p>"
        "<p>Fare mode: <strong>" + escape(clean.get("fare_mode", "live")) + "</strong>. Maximum new requests: " + str(clean.get("maximum_requests", 0)) + ". No LLM, SerpApi, seats, PNR, bookings or payments.</p>"
        "<p><strong>ASSUMED DEMO FARE</strong> means an invented repeatable amount, not a railway quote or market estimate. "
        "Only invented per-adult fares are multiplied by adults. Live provider quotes are not multiplied. "
        "Schedules/classes keep their original evidence and do not confirm seats. Real payable totals remain unverified.</p>"
        + ("<p><strong>Saved-report replay:</strong> zero API requests. Source timestamps are historical; no fresh timetable or availability check occurred.</p>" if clean.get("saved_report_replay") else "") +
        "<h2>Scheduled trains and retrieved quote</h2>" + table + "<h2>Inputs, station candidates, details and request ledger</h2><pre>" + escape(content) + "</pre></html>")
    (folder / "report.html").write_text(html, encoding="utf-8")


def run_check(settings, p, *, http_factory=RailRadarHttp, fare_mode=None):
    mode = fare_mode or settings.train_fare_mode
    if mode not in ("mock", "live"):
        raise ValueError("Fare mode must be mock or live")
    limit = 5 if mode == "mock" else 6
    folder = settings.data_path / "reports" / ("rail_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6])
    folder.mkdir(parents=True)
    report = {"check": "checkpoint09_rail", "outcome": "NOT_COMPLETED", "synthetic_travel_data": False,
        "fare_mode": mode, "contains_assumed_prices": False,
        "preferences": p.model_dump(mode="json"), "selected_stations": {"Delhi": "NDLS", "Jaipur": "JP"},
        "maximum_requests": limit, "requests": [], "station_lookups": [], "trains": [], "stage": "configuration",
        "limitations": ["Explicit NDLS/JP station choices for this probe, not automatic metro-station selection.",
                        "Two shortlisted trains maximum. Mock mode prices confirmed shortlist matches; live mode calls at most one paid fare.",
                        "General quota GN; operated classes are not seat availability.",
                        "Mock prices are invented per adult and multiplied by adults. Real payable budget fit is not verified.",
                        "Live fare access returned PLAN_UPGRADE_REQUIRED on this key; mock mode never calls that endpoint.",
                        "Rerunning --live makes fresh requests; a hard process kill may leave an incomplete request record."]}
    secret, http, adapter = "", None, None
    write_report(folder, report)
    try:
        secret = settings.require_provider_key("railradar")
        def audit(event):
            if "seconds" not in event:
                report["requests"].append(event)
                print(f"Rail request {len(report['requests'])}/{limit}: {event['path']} (30-second timeout)...", flush=True)
            write_report(folder, report, secret)
        with http_factory(secret, max_requests=limit, on_audit=audit) as http:
            adapter = RailRadarAdapter(http, fare_mode=mode)
            report["stage"] = "station lookup"
            for code in ("NDLS", "JP"):
                result = adapter.stations(code)
                report["station_lookups"].append({"query": code, "candidates": [s.model_dump(mode="json") for s in result.items], "warnings": result.warnings})
                write_report(folder, report, secret)
                if not any(s.code == code for s in result.items):
                    raise ProviderError("selected_station_not_found")
            report["stage"] = "schedules, class verification and fare"
            result = adapter.search_leg(p, StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur"))
            report["outcome"] = ("PASS_DEMO_CHECKS" if mode == "mock" else "PASS_CHECKS") if adapter.priced_offer_ids else "REVIEW_REQUIRED"
    except ProviderError as exc:
        report.update(outcome="PROVIDER_ERROR", error=exc.public())
    except KeyboardInterrupt:
        report["outcome"] = "INTERRUPTED"
    except Exception as exc:
        report.update(outcome="CONFIGURATION_OR_LOCAL_ERROR", error_type=type(exc).__name__)
        if not secret:
            report["configuration_hint"] = "Fill RAILRADAR_API_KEY in the project's local .env; never share the key."
    finally:
        if http is not None:
            report["requests"] = list(http.audit)
            report["quota_headers"] = dict(http.quota)
        if adapter is not None:
            report["timetables"] = [item.model_dump(mode="json") for item in adapter.timetables]
            report["fare_components"] = adapter.fare_components
            report["priced_offer_ids"] = adapter.priced_offer_ids
            if adapter.last_result:
                report["trains"] = [item.model_dump(mode="json") for item in adapter.last_result.items]
                report["warnings"] = adapter.last_result.warnings
                report["response_shape"] = adapter.last_result.response_shape
                report["contains_assumed_prices"] = any(o.price.pricing_mode == "demo" for o in adapter.last_result.items)
        write_report(folder, report, secret)
    with ZipFile(folder / "share_results.zip", "w", ZIP_DEFLATED) as zipped:
        for name in ("report.json", "report.html"):
            zipped.write(folder / name, name)
    print("Outcome:", report["outcome"])
    print("Fare mode:", mode, "— assumed prices" if mode == "mock" else "— real provider pricing requested")
    print("Attempted RailRadar requests:", len(report["requests"]), "/", limit)
    print("Report:", folder / "report.html")
    print("Share only:", folder / "share_results.zip")
    return 0 if report["outcome"] in ("PASS_CHECKS", "PASS_DEMO_CHECKS") else 2


def run_replay(path, *, output_root=None):
    """Reprice explicitly supplied saved evidence; never initialize settings/HTTP."""
    if path.suffix.casefold() == ".zip":
        with ZipFile(path) as archive:
            if archive.getinfo("report.json").file_size > 2_000_000:
                raise ValueError("Saved report is too large")
            saved = json.loads(archive.read("report.json"))
    else:
        if path.stat().st_size > 2_000_000:
            raise ValueError("Saved report is too large")
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
    p = TripPreferences.model_validate(saved["preferences"])
    if not p.train_class or p.missing_required():
        raise ValueError("Saved rail report must contain a complete trip and explicit class")
    offers = [TransportOffer.model_validate(item) for item in saved.get("trains", [])]
    details = {item.train_number: item for item in (TrainTimetable.model_validate(d) for d in saved.get("timetables", []))}
    updated, ids, warnings = [], [], []
    for offer in offers:
        detail = details.get(offer.train_number)
        try:
            if detail is None or transport_leg(offer, p) != "outbound_transport":
                raise ValueError("Matching stored evidence is unavailable")
            priced = apply_demo_fare(offer, detail, p.train_class)
            updated.append(priced); ids.append(priced.id)
        except ValueError:
            # No invented schedule/class evidence. The existing unpriced offer stays visible.
            updated.append(offer)
            warnings.append(f"Train {offer.train_number}: requested class/ordered route was not confirmed in saved evidence; no demo fare added.")
    folder = (output_root or PROJECT_ROOT / "data") / "reports" / ("rail_demo_replay_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6])
    folder.mkdir(parents=True)
    report = {"check": "checkpoint09_saved_rail_demo", "outcome": "PASS_DEMO_CHECKS" if ids else "REVIEW_REQUIRED",
        "fare_mode": "mock", "saved_report_replay": True, "source_report": path.name,
        "replayed_at": datetime.now(timezone.utc).isoformat(), "preferences": p.model_dump(mode="json"),
        "synthetic_travel_data": all(o.source.synthetic for o in updated) if updated else False,
        "contains_assumed_prices": any(o.price.pricing_mode == "demo" for o in updated),
        "maximum_requests": 0, "requests": [], "original_request_count": len(saved.get("requests", [])),
        "trains": [o.model_dump(mode="json") for o in updated], "timetables": [d.model_dump(mode="json") for d in details.values()],
        "priced_offer_ids": ids, "warnings": warnings + ["ASSUMED DEMO FARES; source data replayed, not freshly fetched. No verified budget claim."],
        "limitations": ["Historical source timestamps are preserved. This is not a new availability check.",
                        "Only train prices are assumed. Real schedules, route and operated-class evidence are required."]}
    write_report(folder, report)
    with ZipFile(folder / "share_results.zip", "w", ZIP_DEFLATED) as zipped:
        for name in ("report.json", "report.html"):
            zipped.write(folder / name, name)
    print("Outcome:", report["outcome"])
    print("Assumed demo fares added:", len(ids), "— zero API calls; no keys loaded.")
    print("Report:", folder / "report.html")
    print("Share only:", folder / "share_results.zip")
    return 0 if ids else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--live", action="store_true")
    action.add_argument("--replay-report", type=Path)
    parser.add_argument("--fare-mode", choices=("mock", "live"))
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--class-code", choices=sorted(CLASSES))
    args = parser.parse_args(argv)
    if args.replay_report:
        if args.fare_mode == "live" or args.date or args.class_code:
            parser.error("Saved replay uses mock fares and the stored dates/class only")
        try:
            return run_replay(args.replay_report)
        except (ValueError, KeyError, OSError, BadZipFile, TypeError, AttributeError) as exc:
            print("Saved replay failed:", type(exc).__name__, "— original files were not modified.")
            return 2
    if not args.live:
        print("Preview: zero API calls. --live uses up to FIVE requests in mock mode or SIX in live fare mode.")
        print("TRAIN_FARE_MODE defaults to mock; --fare-mode overrides it explicitly. Mock mode never calls /fare.")
        return 0
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    day = args.date or today + timedelta(days=14)
    if day <= today:
        parser.error("--date must be in the future")
    p = TripPreferences(origin="Delhi", destination="Jaipur", departure_date=day, return_date=day + timedelta(days=3),
        adults=2, transport_mode="train", train_class=args.class_code or "CC", currency="INR")
    return run_check(Settings(), p, fare_mode=args.fare_mode)


if __name__ == "__main__":
    raise SystemExit(main())
