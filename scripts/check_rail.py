"""Outbound RailRadar probe: two station lookups, schedules, <=2 details, one fare."""
import argparse
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
import sys
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import Settings
from backend.providers.http import ProviderError
from backend.providers.rail_http import RailRadarHttp
from backend.providers.railradar import CLASSES, RailRadarAdapter, StationBinding
from backend.schemas import TripPreferences


def write_report(folder, report, secret=""):
    content = json.dumps(report, indent=2, ensure_ascii=False)
    if secret:
        content = content.replace(secret, "[REDACTED]")
    (folder / "report.json").write_text(content, encoding="utf-8")
    clean = json.loads(content)
    rows = []
    for offer in clean.get("trains", []):
        values = (offer["train_number"], offer["train_name"], offer["departure_station"], offer["arrival_station"],
                  offer["departure"], offer["arrival"], offer["travel_class"], offer["price"]["amount"], "Unverified")
        rows.append("<tr>" + "".join("<td>" + escape(str(v) if v is not None else "Unknown") + "</td>" for v in values) + "</tr>")
    headers = ("Train", "Name", "From", "To", "Departure", "Arrival", "Fare class", "Quoted INR", "Seats / final payable total")
    table = "<table><tr>" + "".join("<th>" + escape(h) + "</th>" for h in headers) + "</tr>" + "".join(rows) + "</table>"
    html = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Rail provider check</title>"
        "<style>body{font:16px/1.5 system-ui;margin:30px;padding:0 12px}table{border-collapse:collapse;font-size:14px}"
        "td,th{border:1px solid #ccc;padding:8px;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}</style>"
        "<h1>RailRadar outbound retrieval check</h1><p>Outcome: <strong>" + escape(clean["outcome"]) + "</strong></p>"
        "<p>One direction only. At most six RailRadar requests. No LLM, SerpApi, seats, PNR, bookings or payments.</p>"
        "<p>Scheduled services and operated coach classes do not confirm seats. INR quotes are not multiplied by adults. "
        "Passenger coverage and complete payable costs remain unverified. This is not a generated travel plan.</p>"
        "<h2>Scheduled trains and retrieved quote</h2>" + table + "<h2>Inputs, station candidates, details and request ledger</h2><pre>" + escape(content) + "</pre></html>")
    (folder / "report.html").write_text(html, encoding="utf-8")


def run_check(settings, p, *, http_factory=RailRadarHttp):
    folder = settings.data_path / "reports" / ("rail_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6])
    folder.mkdir(parents=True)
    report = {"check": "checkpoint08_rail", "outcome": "NOT_COMPLETED", "synthetic_travel_data": False,
        "preferences": p.model_dump(mode="json"), "selected_stations": {"Delhi": "NDLS", "Jaipur": "JP"},
        "maximum_requests": 6, "requests": [], "station_lookups": [], "trains": [], "stage": "configuration",
        "limitations": ["Explicit NDLS/JP station choices for this probe, not automatic metro-station selection.",
                        "Two shortlisted trains maximum and one fare maximum. Remaining services may be unpriced.",
                        "General quota GN; operated classes are not seat availability.",
                        "No verified passenger/tax/booking-fee completeness, no multiplication by adults.",
                        "The fare documentation currently redirects, although earlier saved fare responses worked; this live check verifies current access.",
                        "Rerunning --live makes fresh requests; a hard process kill may leave an incomplete request record."]}
    secret, http, adapter = "", None, None
    write_report(folder, report)
    try:
        secret = settings.require_provider_key("railradar")
        def audit(event):
            if "seconds" not in event:
                report["requests"].append(event)
                print(f"Rail request {len(report['requests'])}/6: {event['path']} (30-second timeout)...", flush=True)
            write_report(folder, report, secret)
        with http_factory(secret, max_requests=6, on_audit=audit) as http:
            adapter = RailRadarAdapter(http)
            report["stage"] = "station lookup"
            for code in ("NDLS", "JP"):
                result = adapter.stations(code)
                report["station_lookups"].append({"query": code, "candidates": [s.model_dump(mode="json") for s in result.items], "warnings": result.warnings})
                write_report(folder, report, secret)
                if not any(s.code == code for s in result.items):
                    raise ProviderError("selected_station_not_found")
            report["stage"] = "schedules, class verification and fare"
            result = adapter.search_leg(p, StationBinding("NDLS", "Delhi"), StationBinding("JP", "Jaipur"))
            report["outcome"] = "PASS_CHECKS" if adapter.priced_offer_ids else "REVIEW_REQUIRED"
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
        write_report(folder, report, secret)
    with ZipFile(folder / "share_results.zip", "w", ZIP_DEFLATED) as zipped:
        for name in ("report.json", "report.html"):
            zipped.write(folder / name, name)
    print("Outcome:", report["outcome"])
    print("Attempted RailRadar requests:", len(report["requests"]), "/ 6")
    print("Report:", folder / "report.html")
    print("Share only:", folder / "share_results.zip")
    return 0 if report["outcome"] == "PASS_CHECKS" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--class-code", choices=sorted(CLASSES), default="CC")
    args = parser.parse_args(argv)
    if not args.live:
        print("Preview: zero API calls. --live enables at most SIX RailRadar requests.")
        print("NDLS → JP outbound only; explicit CC default; two station lookups, schedules, <=2 timetables, <=1 fare.")
        return 0
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    day = args.date or today + timedelta(days=14)
    if day <= today:
        parser.error("--date must be in the future")
    p = TripPreferences(origin="Delhi", destination="Jaipur", departure_date=day, return_date=day + timedelta(days=3),
        adults=2, transport_mode="train", train_class=args.class_code, currency="INR")
    return run_check(Settings(), p)


if __name__ == "__main__":
    raise SystemExit(main())
