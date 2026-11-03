"""Validate proposed activities against known IDs, hours and travel buffers."""
from collections import Counter
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict


class Activity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    place_id: str
    date: str
    start: str
    end: str


class Schedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    activities: list[Activity]
    notes: list[str]


def validate_schedule(schedule, places, outward, returning, p, timezone):
    errors, warnings, intervals, seen = [], [], [], set()
    known = {place.id: place for place in places}
    selected = {activity.place_id for activity in schedule.activities}
    if any(selected.intersection(known[id].possible_duplicate_ids) for id in selected if id in known):
        errors.append("Possible duplicate attractions: schedule only one candidate from each flagged alias pair.")
    tz = ZoneInfo(timezone)
    if not schedule.activities:
        errors.append("Schedule must contain an activity from the supplied candidates.")
    for activity in schedule.activities:
        if activity.place_id not in known or activity.place_id in seen:
            errors.append("Unknown or repeated place ID: " + activity.place_id)
            continue
        seen.add(activity.place_id)
        try:
            # Activity strings represent destination-local times, never UTC by assumption.
            day = datetime.strptime(activity.date, "%Y-%m-%d").date()
            start = datetime.combine(day, datetime.strptime(activity.start, "%H:%M").time(), tz)
            end = datetime.combine(day, datetime.strptime(activity.end, "%H:%M").time(), tz)
        except ValueError:
            errors.append("Invalid activity date/time format.")
            continue
        if not (p.departure_date <= day <= p.return_date) or end <= start:
            errors.append("Activity outside trip dates or has invalid duration.")
        if start < outward.arrival + timedelta(hours=1) or end > returning.departure - timedelta(hours=1):
            errors.append("Activity violates the 60-minute arrival/departure buffer.")
        place = known[activity.place_id]
        # Conflicting listings must not make a 24-hour alias look verified.
        windows = None if place.possible_duplicate_ids else place.weekly_hours.get(day.weekday())
        if windows is None:
            warnings.append("Opening hours unverified: " + activity.place_id)
        else:
            fits, unverified = False, False
            for opening, closing in windows:
                try:
                    opens = datetime.combine(day, time.fromisoformat(opening), tz)
                    closes = datetime.combine(day, time.fromisoformat(closing), tz)
                except ValueError:
                    unverified = True
                    continue
                if closes <= opens:
                    unverified = True  # Overnight hours need adapter-level normalization.
                    continue
                fits |= opens <= start < end <= closes
            if not fits:
                if unverified:
                    warnings.append("Opening hours unverified: " + activity.place_id)
                else:
                    errors.append("Activity outside known opening hours: " + activity.place_id)
        intervals.append((start, end))
    intervals.sort()
    if any(later[0] < earlier[1] + timedelta(minutes=30) for earlier, later in zip(intervals, intervals[1:])):
        errors.append("Activities overlap or have less than the estimated 30-minute transfer buffer.")
    limit = {"relaxed": 3, "balanced": 5, "busy": 7}.get(p.pace, 5)
    if any(count > limit for count in Counter(a.date for a in schedule.activities).values()):
        errors.append("Daily activity count exceeds the selected pace.")
    return errors, sorted(set(warnings))
