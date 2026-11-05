"""Read-only demo of a saved trip. No agent, provider or credential imports."""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import streamlit as st


SAMPLE = Path(__file__).with_name("jaipur_sample.json")


def money(amount: str) -> str:
    return f"₹{Decimal(amount):,.2f}".removesuffix(".00")


def day_label(day: str) -> str:
    return date.fromisoformat(day).strftime("%a, %d %b %Y")


def local_time(stamp: str) -> str:
    return datetime.fromisoformat(stamp).strftime("%H:%M")


def show_transport(legs: list[dict], adults: int) -> None:
    st.subheader("Train recommendations")
    st.caption("Timetables from the saved search. Seats are unverified. All times are IST.")
    for column, leg in zip(st.columns(2), legs):
        with column, st.container(border=True):
            st.markdown(f"**{leg['direction']} · Train {leg['train_number']}**")
            st.write(leg["train_name"])
            st.caption(f"{day_label(leg['departure'][:10])} · Class {leg['travel_class']}")
            st.write(f"{leg['departure_station']} {local_time(leg['departure'])} → "
                     f"{leg['arrival_station']} {local_time(leg['arrival'])}")
            fare = leg["price"]
            st.markdown(f"**Demo fare: {money(fare['amount'])} for {adults} adults**")
            st.caption(f"{money(fare['per_adult_amount'])} per adult · Illustrative, not a railway quote")


def show_hotel(hotel: dict) -> None:
    st.subheader("Hotel recommendation")
    nights = (date.fromisoformat(hotel["check_out"]) - date.fromisoformat(hotel["check_in"])).days
    with st.container(border=True):
        st.markdown(f"**{hotel['name']}** · {hotel['hotel_class']}-star · Guest rating {hotel['guest_rating']}/5")
        st.caption(f"{day_label(hotel['check_in'])} to {day_label(hotel['check_out'])} · {nights} nights")
        st.write(f"Quoted {money(hotel['nightly_price'])} per night · "
                 f"{money(hotel['price']['amount'])} quoted for the stay")
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
            st.markdown(f"- {activity['start']}–{activity['end']} · {activity['name']}{notice}")


def main() -> None:
    st.set_page_config(page_title="Travel Planning Agent", page_icon="🧳", layout="centered")
    st.title("Travel Planning Agent")
    st.caption("Offline demo · Saved trip")
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

    trip = sample["trip"]
    st.header(f"{trip['origin']} → {trip['destination']}")
    st.write(f"{day_label(trip['departure_date'])} to {day_label(trip['return_date'])} · {trip['adults']} adults")
    st.caption(f"Snapshot from {day_label(sample['snapshot_date'])}. Prices and availability were not refreshed.")
    st.warning(f"Target budget: {money(trip['budget_total'])} · Budget fit unverified. "
               "Train fares are demo amounts and the hotel quote is incomplete.")
    st.caption("Excluded from the cost comparison: "
               + ", ".join(value.replace("_", " ") for value in sample["costs"]["excluded_costs"]) + ".")

    show_transport(sample["transport"], trip["adults"])
    show_hotel(sample["hotel"])
    show_itinerary(sample["days"])

    with st.expander("Saved sources"):
        st.write("Train schedules: RailRadar. Hotel quote: Google Hotels via SerpApi. "
                 "Places and saved hours: Google Maps via SerpApi.")
        st.caption("These are source links, not reservation or payment links.")
        st.link_button("RailRadar schedule source", sample["transport"][0]["source"]["url"])
        st.link_button("Hotel website", sample["hotel"]["source"]["url"])


if __name__ == "__main__":
    main()
