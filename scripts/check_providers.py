"""Bounded real hotel/place or flight checks, separate from Groq and the graph."""
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
from backend.providers.http import ProviderError, SerpApiHttp
from backend.providers.flights import AirportLocation, FlightAdapter
from backend.providers.serpapi import SerpApiAdapter
from backend.schemas import TripPreferences
from backend.services.offer_filters import eligible_hotels, eligible_transport


def write_report(folder, report, secret=""):
    """Escape source text in HTML and remove the known key from all saved text."""
    content = json.dumps(report, indent=2, ensure_ascii=False)
    if secret:
        content = content.replace(secret, "[REDACTED]")
    (folder / "report.json").write_text(content, encoding="utf-8")
    clean = json.loads(content)
    def cell(value):
        return escape(str(value) if value is not None else "Unknown")
    def table(headers, records):
        return "<table><thead><tr>" + "".join("<th>" + cell(h) + "</th>" for h in headers) + "</tr></thead><tbody>" + \
            "".join("<tr>" + "".join("<td>" + cell(v) + "</td>" for v in row) + "</tr>" for row in records) + "</tbody></table>"
    rows = []
    for case in clean["cases"]:
        parameters = [r["parameters"] for r in case.get("requests", [])]
        inputs = "<h3>Input parameters</h3><pre>" + escape(json.dumps(parameters, indent=2, ensure_ascii=False)) + "</pre>"
        if case["category"] == "hotels":
            summary = table(["Hotel", "Stars", "Guest rating / 5", "Nightly quote", "Stay quote", "Currency", "Matches filters?", "Occupancy verified?", "Taxes included?"],
                [(h["name"], h["hotel_class"], h["guest_rating"], h["nightly_price"], h["price"]["amount"], h["price"]["currency"],
                  "Yes" if h["id"] in case.get("eligible_hotel_ids", []) else "No", "Unverified",
                  "Yes" if h["price"]["taxes_included"] is True else "No" if h["price"]["taxes_included"] is False else "Unverified")
                 for h in case.get("items", [])])
        elif case["category"] == "places":
            summary = table(["Place", "Rating / 5", "Address", "Latitude", "Longitude", "Hours available?"],
                [(p["name"], p["rating"], p["address"], p["latitude"], p["longitude"], "Some weekdays" if p["weekly_hours"] else "Unverified")
                 for p in case.get("items", [])])
        else:
            summary = table(["Route", "Departure", "Arrival", "Flight numbers", "Airlines", "Quoted price", "Currency", "All-traveler coverage", "Taxes"],
                [(f["origin"] + " → " + f["destination"], f["departure"], f["arrival"],
                  ", ".join(s["flight_number"] or "Unknown" for s in f["segments"]),
                  ", ".join(s["airline"] or "Unknown" for s in f["segments"]), f["price"]["amount"], f["price"]["currency"],
                  "Yes" if f["price"]["covers_all_travelers"] else "Unverified", "Unverified")
                 for f in case.get("items", [])])
        warnings = "<ul>" + "".join("<li>" + cell(w) + "</li>" for w in case.get("warnings", [])) + "</ul>"
        rows.append("<section><h2>" + escape(case["category"]) + " — " + escape(case["outcome"]) + "</h2>" + inputs + summary + warnings +
                    "<details><summary>Normalized data, source links and timestamps</summary><pre>" +
                    escape(json.dumps(case, indent=2, ensure_ascii=False)) + "</pre></details></section>")
    html = ("<!doctype html><html lang='en'><meta charset='utf-8'><title>Travel provider check</title>"
            "<style>body{font:16px/1.5 system-ui;max-width:1100px;margin:32px auto;padding:0 20px}"
            "pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f8;padding:16px}"
            "section{border-top:1px solid #ccc;margin-top:24px}table{border-collapse:collapse;width:100%;font-size:14px}"
            "td,th{border:1px solid #ddd;padding:8px;text-align:left}th{background:#e9eef3}</style>"
            "<h1>Travel provider check</h1><p>Outcome: <strong>" + escape(report["outcome"]) +
            "</strong></p><p>Real retrieval only. No LLM requests, reservations, payments or rail searches.</p>"
            "<p>Prices are source quotes. Room occupancy/type and any unspecified taxes remain unverified. "
            "Places have no verified admission prices. This does not validate a complete travel plan.</p>" +
            "".join(rows) + "<h2>Request ledger and full report</h2><pre>" + escape(content) + "</pre></html>")
    (folder / "report.html").write_text(html, encoding="utf-8")


def run_check(settings, p, categories, *, http_factory=SerpApiHttp, flight_airports=None):
    folder = settings.data_path / "reports" / ("providers_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + uuid4().hex[:6])
    folder.mkdir(parents=True)
    report = {"check": "checkpoint07_providers", "outcome": "NOT_COMPLETED",
              "preferences": p.model_dump(mode="json"), "synthetic_travel_data": False,
              "maximum_requests": len(categories), "requested_categories": categories, "cases": [], "requests": [],
              "limitations": ["One response page per category; no pagination, retries or property-detail calls.",
                              "Hotel dates are this probe's stay dates, not dates derived from a transport booking.",
                              "Provider may serve cached data; fetched_at and provider_data_at are separate.",
                              "Nearby possible place aliases are flagged, not automatically merged; relevance still needs review.",
                              "Flight checks use explicit airport/timezone bindings; automatic city-to-airport resolution is pending.",
                              "Outbound/return flights are independent one-way quotes, not an airline round-trip bundle."]}
    if flight_airports:
        report["flight_airports"] = [vars(airport) for airport in flight_airports]
    secret = ""
    write_report(folder, report)
    try:
        secret = settings.require_provider_key("serpapi")
        with http_factory(secret) as http:
            adapter = SerpApiAdapter(http)
            # Known zones for this domestic probe's potential connections, not a city resolver.
            flights = FlightAdapter(http, airport_timezones={code: "Asia/Kolkata" for code in
                ("DEL", "JAI", "BOM", "BLR", "HYD", "MAA", "CCU", "AMD", "LKO", "UDR", "JDH", "GOI", "GOX", "PNQ", "COK")})
            for category in categories:
                case = {"category": category, "outcome": "REQUESTING"}
                report["cases"].append(case)
                write_report(folder, report, secret)
                print(category + ": requesting (30-second timeout, no retries)...", flush=True)
                request_start = len(http.audit)
                try:
                    if category == "hotels":
                        result = adapter.hotels(p)
                    elif category == "places":
                        result = adapter.places(p)
                    elif category in ("outbound_flights", "return_flights") and flight_airports:
                        a, b = flight_airports
                        result = flights.search_leg(p, a, b) if category == "outbound_flights" else flights.search_leg(p, b, a, leg="return")
                    else:
                        raise ValueError("Unknown category or missing explicit airport bindings")
                    case.update(outcome="DATA_RETURNED" if result.items else "EMPTY_RESULT",
                        normalized_count=len(result.items), warnings=result.warnings,
                        response_shape=result.response_shape, skipped_records=result.skipped_records,
                        items=[item.model_dump(mode="json") for item in result.items])
                    if category == "hotels":
                        eligible = eligible_hotels(result.items, p)
                        case["eligible_hotel_ids"] = [item.id for item in eligible]
                        case["filter_note"] = "Nightly price, exact star class and guest rating checked in Python; occupancy/type remain unverified."
                        if result.items and not eligible:
                            case["outcome"] = "NO_HOTELS_MATCH_FILTERS"
                    elif category.endswith("flights"):
                        case["eligible_flight_ids"] = [item.id for item in eligible_transport(result.items, p)]
                        case["filter_note"] = "Route/date/class checked in Python. An explicit total-price cap requires a complete quote; unknown coverage/taxes cannot verify it."
                        case["known_quote_count"] = sum(item.price.amount is not None for item in result.items)
                        if result.items and not case["eligible_flight_ids"]:
                            case["outcome"] = "NO_FLIGHTS_MATCH_VERIFIED_FILTERS"
                        elif result.items and not case["known_quote_count"]:
                            case["outcome"] = "PRICE_DATA_MISSING"
                except ProviderError as exc:
                    case.update(outcome="PROVIDER_ERROR", error=exc.public())
                    # A quota/auth/network error stops the run; do not spend another request.
                    break
                except KeyboardInterrupt:
                    case["outcome"] = "INTERRUPTED"
                    break
                except Exception as exc:
                    case.update(outcome="LOCAL_ERROR", error_type=type(exc).__name__)
                    break
                finally:
                    report["requests"] = list(http.audit)
                    case["requests"] = list(http.audit[request_start:])
                    write_report(folder, report, secret)
                print(category + ": " + case["outcome"], flush=True)
        report["outcome"] = "PASS_CHECKS" if len(report["cases"]) == len(categories) and all(c["outcome"] == "DATA_RETURNED" for c in report["cases"]) else "REVIEW_REQUIRED"
    except Exception as exc:
        # Exception strings and tracebacks can contain credential-bearing request URLs.
        report.update(outcome="CONFIGURATION_OR_LOCAL_ERROR", error_type=type(exc).__name__)
    write_report(folder, report, secret)
    # Create once, after report writes finish. Avoid replacing an open ZIP on Windows.
    archive = folder / "share_results.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as zipped:
        for name in ("report.json", "report.html"):
            zipped.write(folder / name, name)
    print("Outcome:", report["outcome"])
    print("Attempted SerpApi requests:", len(report["requests"]), "/", len(categories))
    print("Report:", folder / "report.html")
    print("Share only:", archive)
    return 0 if report["outcome"] == "PASS_CHECKS" else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--category", choices=("hotels", "places", "all", "flights"), default="all")
    parser.add_argument("--check-in", type=date.fromisoformat)
    args = parser.parse_args(argv)
    if not args.live:
        print("Preview: zero API calls. --live --category all or flights enables at most TWO SerpApi requests.")
        if args.category == "flights":
            print("Delhi DEL → Jaipur JAI, then the return route, as independent one-way flight searches. No Groq/rail calls.")
        else:
            print("One Jaipur hotel search and one Maps place search. No Groq, flight, rail or booking calls.")
        return 0
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    check_in = args.check_in or today + timedelta(days=14)
    if check_in <= today:
        parser.error("--check-in must be a future stay date")
    values = dict(origin="Delhi", destination="Jaipur", departure_date=check_in, return_date=check_in + timedelta(days=3), adults=2, currency="INR")
    if args.category == "flights":
        p = TripPreferences(**values, transport_mode="flight", flight_class="Economy", flight_sort_by=2)
        airports = (AirportLocation("DEL", "Delhi", "Asia/Kolkata"), AirportLocation("JAI", "Jaipur", "Asia/Kolkata"))
        return run_check(Settings(), p, ["outbound_flights", "return_flights"], flight_airports=airports)
    p = TripPreferences(**values, hotel_class=3, nightly_min="2000", nightly_max="4000", guest_rating_min=4.2, interests=["history"])
    categories = ["hotels", "places"] if args.category == "all" else [args.category]
    return run_check(Settings(), p, categories)


if __name__ == "__main__":
    raise SystemExit(main())
