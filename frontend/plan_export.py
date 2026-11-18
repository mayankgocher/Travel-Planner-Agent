"""Markdown export of the display result. No agent calls or credentials."""
from decimal import Decimal
from html import escape
import re
from urllib.parse import urlsplit


def money(amount, currency="INR") -> str:
    if amount is None:
        return "Unverified"
    symbol = "₹" if currency == "INR" else f"{currency} "
    return symbol + f"{Decimal(amount):,.2f}".removesuffix(".00")


def plain(value) -> str:
    return re.sub(r"([\\`*_\[\]|])", r"\\\1", escape(" ".join(str(value).split()), quote=False))


def plan_markdown(plan: dict) -> str:
    trip = plan["trip"]
    lines = [f"# {plain(trip['origin'])} → {plain(trip['destination'])}", "",
             f"{trip['departure_date']} to {trip['return_date']} · {trip['adults']} adults · IST",
             "Recommendations only. Seat availability and bookings are unverified."]
    if snapshot := plan.get("snapshot_date"):
        lines += [f"Saved snapshot from {snapshot}; prices and availability were not refreshed."]
    elif plan.get("status") not in ("draft_ready", "draft_ready_with_warnings"):
        lines += ["Incomplete draft or needs review."]

    costs = plan.get("costs") or {}
    lines += ["", "## Budget"]
    if trip.get("budget_total") is not None:
        lines += [f"Target budget: {money(trip['budget_total'], trip['currency'])}"]
    if costs.get("complete_subtotal") is None:
        lines += ["Budget fit unverified. A complete payable total was not established."]
    else:
        lines += [f"Transport and hotel subtotal: {money(costs['complete_subtotal'], trip['currency'])}"]
        status = {"within_budget": "Subtotal is within the target budget.",
                  "over_budget": "Subtotal exceeds the target budget."}
        if note := status.get(costs.get("budget_status")):
            lines.append(note)
    if excluded := costs.get("excluded_costs"):
        lines += ["Excluded: " + ", ".join(plain(v.replace("_", " ")) for v in excluded) + "."]

    lines += ["", "## Transport"]
    for leg in plan["transport"]:
        fare = leg["price"]
        if leg.get("mode", "train") == "train":
            service = f"Train {plain(leg['train_number'])} · {plain(leg['train_name'] or 'Scheduled service')}"
            route = f"{plain(leg['departure_station'])} → {plain(leg['arrival_station'])}"
        else:
            service = "Flight · " + ", ".join(plain(s["flight_number"] or s["airline"] or "Flight") for s in leg["segments"])
            route = f"{plain(leg['origin'])} → {plain(leg['destination'])}"
        lines += [f"- {plain(leg['direction'])}: {service} · {route} · Class {plain(leg['travel_class'] or 'unverified')}",
                  f"  - {leg['departure']} to {leg['arrival']}"]
        amount = money(fare["amount"], fare["currency"])
        if fare["pricing_mode"] == "demo":
            lines += [f"  - **Demo fare:** {amount} for {trip['adults']} adults; not a railway quote."]
        else:
            lines += [f"  - Quoted fare: {amount}."]
            if not fare["covers_all_travelers"] or fare["taxes_included"] is not True:
                lines += ["  - Passenger coverage or included taxes are unverified."]
    if not plan["transport"]:
        lines += ["No transport offer available."]

    lines += ["", "## Hotel"]
    if hotel := plan["hotel"]:
        quote = hotel["price"]
        lines += [f"{plain(hotel['name'])} · {hotel['check_in']} to {hotel['check_out']}",
                  f"Nightly quote: {money(hotel['nightly_price'], quote['currency'])}",
                  f"Stay quote: {money(quote['amount'], quote['currency'])}"]
        if not quote["covers_all_travelers"] or quote["taxes_included"] is not True:
            lines += ["Room occupancy, taxes, fees, and the final payable amount are unverified."]
    else:
        lines += ["No eligible hotel offer available."]

    lines += ["", "## Itinerary"]
    if not plan["days"]:
        lines += ["No validated itinerary available."]
    for day in plan["days"]:
        lines += [f"### {day['date']}"]
        for activity in day["activities"]:
            note = " · Opening hours unverified" if activity["hours_unverified"] else ""
            lines += [f"- {activity['start']}–{activity['end']} · {plain(activity['name'])}{note}"]
        if not day["activities"]:
            lines += ["No activities scheduled."]
    if warnings := plan.get("warnings"):
        lines += ["", "## Planning warnings", *[f"- {plain(w)}" for w in warnings]]
    sources = [leg["source"] for leg in plan["transport"]]
    if plan["hotel"]:
        sources.append(plan["hotel"]["source"])
    if sources:
        lines += ["", "## Offer sources", "Source links are not reservation or payment links."]
        for source in sources:
            lines += [f"- {plain(source['provider'])} · fetched {plain(source['fetched_at'])}"]
            url = urlsplit(source.get("url") or "")
            if url.scheme in ("https", "http") and url.hostname and not url.username and not url.password:
                lines += [f"  - {plain(url._replace(query='', fragment='').geturl())}"]
    return "\n".join(lines) + "\n"
