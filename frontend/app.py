"""Saved sample and explicit live requests to the local planning server."""

import json
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import streamlit as st


SAMPLE = Path(__file__).with_name("jaipur_sample.json")
PLAN_URL = "http://127.0.0.1:8000/plan"


def money(amount, currency="INR") -> str:
    if amount is None:
        return "Unverified"
    symbol = "₹" if currency == "INR" else f"{currency} "
    return symbol + f"{Decimal(amount):,.2f}".removesuffix(".00")


def day_label(day: str) -> str:
    return date.fromisoformat(day).strftime("%a, %d %b %Y")


def local_time(stamp: str) -> str:
    return datetime.fromisoformat(stamp).strftime("%H:%M")


def show_transport(legs: list[dict], adults: int) -> None:
    st.subheader("Train recommendations" if all(leg.get("mode", "train") == "train" for leg in legs)
                 else "Transport recommendations")
    st.caption("Seats are unverified. All times are IST.")
    for column, leg in zip(st.columns(2), legs):
        with column, st.container(border=True):
            if leg.get("mode", "train") == "train":
                st.markdown(f"**{leg['direction']} · Train {leg['train_number']}**")
                st.text(leg["train_name"] or "Scheduled train")
                origin, destination = leg["departure_station"], leg["arrival_station"]
            else:
                st.markdown(f"**{leg['direction']} · Flight**")
                segments = leg["segments"]
                for segment in segments:
                    st.text(f"{segment['departure_airport']} → {segment['arrival_airport']} · "
                            f"{segment['flight_number'] or segment['airline'] or 'Flight'}")
                origin = segments[0]["departure_airport"] if segments else leg["origin"]
                destination = segments[-1]["arrival_airport"] if segments else leg["destination"]
            st.caption(f"{day_label(leg['departure'][:10])} · Class {leg['travel_class'] or 'unverified'}")
            st.write(f"{origin} {local_time(leg['departure'])} → {destination} {local_time(leg['arrival'])}")
            if leg["arrival"][:10] != leg["departure"][:10]:
                st.caption(f"Arrives {day_label(leg['arrival'][:10])}")
            fare = leg["price"]
            amount = money(fare["amount"], fare["currency"])
            if fare["pricing_mode"] == "demo":
                st.markdown(f"**Demo fare: {amount} for {adults} adults**")
                st.caption(f"{money(fare['per_adult_amount'], fare['currency'])} per adult · "
                           "Illustrative, not a railway quote")
            elif fare["amount"] is not None:
                st.write(f"Quoted fare: {amount}")
                if not fare["covers_all_travelers"] or fare["taxes_included"] is not True:
                    st.caption("Passenger coverage or included taxes are unverified.")
            else:
                st.write("Fare unverified.")


def show_hotel(hotel: dict) -> None:
    st.subheader("Hotel recommendation")
    nights = (date.fromisoformat(hotel["check_out"]) - date.fromisoformat(hotel["check_in"])).days
    with st.container(border=True):
        st.text(hotel["name"])
        star = f"{hotel['hotel_class']}-star" if hotel["hotel_class"] else "Star class unverified"
        rating = f"Guest rating {hotel['guest_rating']}/5" if hotel["guest_rating"] is not None else "Guest rating unverified"
        st.caption(f"{star} · {rating}")
        st.caption(f"{day_label(hotel['check_in'])} to {day_label(hotel['check_out'])} · {nights} nights")
        price = hotel["price"]
        nightly = money(hotel["nightly_price"], price["currency"])
        total = money(price["amount"], price["currency"])
        st.write(f"Quoted {nightly} per night" if hotel["nightly_price"] is not None else "Nightly quote unverified.")
        st.write(f"{total} quoted for the stay" if price["amount"] is not None else "Stay quote unverified.")
        if not price["covers_all_travelers"] or price["taxes_included"] is not True:
            st.caption("Room occupancy, taxes, fees, and the final payable amount are unverified.")


def show_itinerary(days: list[dict]) -> None:
    st.subheader("Day-by-day itinerary")
    st.caption("Times are in IST. Travel gaps are planning buffers. Admission fees were not checked.")
    for day in days:
        st.markdown(f"**{day_label(day['date'])}**")
        if not day["activities"]:
            st.caption("No activities scheduled.")
        for activity in day["activities"]:
            notice = " · Opening hours unverified" if activity["hours_unverified"] else ""
            name = re.sub(r"([\\`*_\[\]<>])", r"\\\1", activity["name"]).replace("\n", " ").replace("\r", " ")
            st.markdown(f"- {activity['start']}–{activity['end']} · {name}{notice}")


def show_trip(plan: dict) -> None:
    trip = plan["trip"]
    st.header(f"{trip['origin']} → {trip['destination']}")
    st.write(f"{day_label(trip['departure_date'])} to {day_label(trip['return_date'])} · {trip['adults']} adults")
    if "snapshot_date" in plan:
        st.caption(f"Snapshot from {day_label(plan['snapshot_date'])}. Prices and availability were not refreshed.")
    elif plan["status"] not in ("draft_ready", "draft_ready_with_warnings"):
        st.warning("This request returned an incomplete draft or needs review.")

    costs = plan.get("costs") or {}
    if trip["budget_total"] is not None:
        st.write(f"Target budget: {money(trip['budget_total'], trip['currency'])}")
    if costs.get("complete_subtotal") is None:
        st.warning("Budget fit unverified. A complete payable total was not established.")
    else:
        st.write(f"Transport and hotel subtotal: {money(costs['complete_subtotal'], trip['currency'])}")
        budget_message = {"within_budget": "This subtotal is within the target budget.",
                          "over_budget": "This subtotal exceeds the target budget."}
        if message := budget_message.get(costs.get("budget_status")):
            st.write(message)
    if exclusions := costs.get("excluded_costs"):
        st.caption("Excluded from the cost comparison: " + ", ".join(v.replace("_", " ") for v in exclusions) + ".")

    if plan["transport"]:
        show_transport(plan["transport"], trip["adults"])
    else:
        st.info("No transport offer is available for this draft.")
    if plan["hotel"]:
        show_hotel(plan["hotel"])
    else:
        st.info("No eligible hotel offer is available for this draft.")
    if plan["days"]:
        show_itinerary(plan["days"])
    else:
        st.info("No validated itinerary is available for this draft.")

    if warnings := plan.get("warnings"):
        with st.expander("Planning warnings", expanded=True):
            for warning in warnings:
                st.text(warning)
    sources = [leg["source"] for leg in plan["transport"]]
    if plan["hotel"]:
        sources.append(plan["hotel"]["source"])
    if sources:
        with st.expander("Offer sources"):
            st.caption("These are source links, not reservation or payment links.")
            for index, source in enumerate(sources):
                label = {"railradar": "RailRadar", "serpapi_google_hotels": "Google Hotels via SerpApi",
                         "serpapi_google_flights": "Google Flights via SerpApi"}.get(source["provider"], source["provider"])
                st.text(f"{label} · Fetched {source['fetched_at']}")
                if url := source.get("url"):
                    prefix = "sample" if "snapshot_date" in plan else "live"
                    st.link_button(f"Open {label} source", url, key=f"{prefix}_source_{index}")


def sample_tab() -> None:
    if st.button("Load sample trip", type="primary"):
        st.session_state["sample_loaded"] = True
    if not st.session_state.get("sample_loaded"):
        st.info("Load the Delhi → Jaipur sample to view trains, a hotel quote, and a daily itinerary.")
        return
    try:
        sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.error("The saved sample could not be loaded. Re-extract the checkpoint files and try again.")
        return
    show_trip(sample)


def request_plan(payload: dict) -> dict:
    # A slow provider may take a while. Do not retry a potentially billable POST.
    with httpx.Client(timeout=httpx.Timeout(480, connect=3), trust_env=False) as client:
        response = client.post(PLAN_URL, json=payload)
        response.raise_for_status()
        return response.json()


def live_tab() -> None:
    st.write("**Delhi → Jaipur round trip**")
    st.caption("Generate plan makes live requests. Train fares are illustrative demo amounts.")
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    with st.form("live_trip"):
        left, right = st.columns(2)
        depart = left.date_input("Departure", today + timedelta(days=14), min_value=today + timedelta(days=1))
        back = right.date_input("Return", today + timedelta(days=17), min_value=today + timedelta(days=2))
        modes = {"Train": "train", "Flight": "flight", "Compare train and flight": "compare"}
        mode = left.selectbox("Transport", list(modes))
        adults = right.number_input("Adults", min_value=1, max_value=6, value=2)
        train_class = left.selectbox("Train class (when used)", ["CC", "EC", "3A", "2A", "1A", "SL"])
        cabin = right.selectbox("Flight cabin (when used)", ["Economy", "Premium Economy", "Business", "First"])
        hotel_class = left.selectbox("Hotel star class", ["Any", "2", "3", "4", "5", "1"], index=2)
        rating = right.number_input("Minimum guest rating", min_value=0.0, max_value=5.0, value=4.2, step=0.1)
        min_price = left.number_input("Minimum nightly quote (₹)", min_value=0, value=2000, step=100)
        max_price = right.number_input("Maximum nightly quote (₹)", min_value=0, value=4000, step=100)
        budget = st.number_input("Trip budget (₹)", min_value=0, value=25000, step=500)
        submit = st.form_submit_button("Generate plan", type="primary")

    if submit:
        st.session_state.pop("live_result", None)
        if not depart or not back or not 1 <= (back - depart).days <= 7 or min_price > max_price:
            st.error("Choose a return date one to seven nights later and a valid nightly price range.")
        else:
            payload = {
                "departure_date": depart.isoformat(), "return_date": back.isoformat(), "adults": adults,
                "transport_mode": modes[mode], "train_class": train_class, "flight_class": cabin,
                "hotel_class": None if hotel_class == "Any" else int(hotel_class),
                "guest_rating_min": rating, "nightly_min": min_price, "nightly_max": max_price,
                "budget_total": budget,
            }
            try:
                with st.spinner("Searching and drafting your plan…"):
                    st.session_state["live_result"] = request_plan(payload)
            except httpx.ConnectError:
                st.error("Start the FastAPI server on port 8000, then submit again.")
            except httpx.TimeoutException:
                st.error("The request timed out. It may have used API quota; check the backend terminal.")
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 503:
                    st.error("Check the backend terminal and the API settings in your local .env.")
                elif error.response.status_code == 422:
                    st.error("Check the trip dates and filters, then submit again.")
                else:
                    st.error("Planning stopped. Check the backend terminal for details.")
            except (httpx.HTTPError, ValueError):
                st.error("Could not read a planning result. Check the backend terminal.")

    if result := st.session_state.get("live_result"):
        show_trip(result)


def main() -> None:
    st.set_page_config(page_title="Travel Planning Agent", page_icon="🧳", layout="centered")
    st.title("Travel Planning Agent")
    saved, live = st.tabs(["Saved sample", "Live planning"])
    with saved:
        sample_tab()
    with live:
        live_tab()


if __name__ == "__main__":
    main()
