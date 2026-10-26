"""Clinic opening windows and slot rules (pure Python, no web/DB imports).

India has no daylight saving, so a fixed UTC+05:30 offset is used. This also
avoids needing the ``tzdata`` package on Windows.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable

IST = timezone(timedelta(hours=5, minutes=30), "IST")
SLOT_MINUTES = 30

# Booking windows, start inclusive / end exclusive. These mirror the
# ultrasound hours printed on the letterhead and used by the website.
WEEKDAY_WINDOWS = (("09:30", "14:00"), ("17:00", "20:30"))  # Monday-Saturday
SUNDAY_WINDOWS = (("10:30", "12:30"),)

SERVICES = (
    "In-clinic consultation",
    "Online consultation",
    "Ultrasound / scan",
    "Health package",
)
DEFAULT_SERVICE = SERVICES[0]


class ScheduleError(ValueError):
    """The requested date/time cannot be booked. ``str(e)`` is user-facing."""


def now_ist() -> datetime:
    return datetime.now(IST)


def windows_for(day: date) -> tuple[tuple[str, str], ...]:
    return SUNDAY_WINDOWS if day.weekday() == 6 else WEEKDAY_WINDOWS  # Monday == 0


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def slot_times(day: date, closed_dates: Iterable[str] = ()) -> list[str]:
    """All bookable start times (``HH:MM``) for a day; empty if the clinic is closed."""
    if day.isoformat() in set(closed_dates):
        return []
    times: list[str] = []
    for start, end in windows_for(day):
        t, stop = _minutes(start), _minutes(end)
        while t < stop:
            times.append(f"{t // 60:02d}:{t % 60:02d}")
            t += SLOT_MINUTES
    return times


def format_label(hhmm: str) -> str:
    """'17:30' -> '5:30 PM' (matches what the website shows)."""
    hour, minute = (int(x) for x in hhmm.split(":"))
    return f"{hour % 12 or 12}:{minute:02d} {'PM' if hour >= 12 else 'AM'}"


def _slot_start(day: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=IST)


def check_bookable(
    day: date,
    hhmm: str,
    *,
    now: datetime | None = None,
    lead_minutes: int = 30,
    max_days_ahead: int = 60,
    closed_dates: Iterable[str] = (),
) -> None:
    """Raise :class:`ScheduleError` unless ``day`` + ``hhmm`` is a bookable slot."""
    now = now or now_ist()
    if day < now.date():
        raise ScheduleError("Appointment date cannot be in the past")
    if day > now.date() + timedelta(days=max_days_ahead):
        raise ScheduleError(f"Appointments can be booked up to {max_days_ahead} days in advance.")
    if day.isoformat() in set(closed_dates):
        raise ScheduleError("The clinic is closed on that date. Please choose another day.")
    if hhmm not in slot_times(day, closed_dates):
        raise ScheduleError("That time is outside booking hours. Please pick one of the listed slots.")
    if _slot_start(day, hhmm) < now + timedelta(minutes=lead_minutes):
        raise ScheduleError("That time slot has passed or is too close. Please choose a later slot.")


def slots_payload(
    day: date,
    booked: Iterable[str] = (),
    *,
    now: datetime | None = None,
    lead_minutes: int = 30,
    max_days_ahead: int = 60,
    closed_dates: Iterable[str] = (),
) -> dict:
    """Public availability for one day, in the shape the website consumes."""
    now = now or now_ist()
    payload = {"date": day.isoformat(), "closed": False, "message": None, "slots": []}

    if day < now.date():
        payload.update(closed=True, message="That date has passed. Please choose another day.")
        return payload
    if day > now.date() + timedelta(days=max_days_ahead):
        payload.update(closed=True, message=f"Appointments open up to {max_days_ahead} days in advance.")
        return payload

    times = slot_times(day, closed_dates)
    if not times:
        payload.update(closed=True, message="The clinic is closed on that date. Please choose another day.")
        return payload

    taken = set(booked)
    cutoff = now + timedelta(minutes=lead_minutes)
    for t in times:
        payload["slots"].append(
            {
                "time": t,
                "label": format_label(t),
                "available": t not in taken and _slot_start(day, t) >= cutoff,
            }
        )
    if not any(s["available"] for s in payload["slots"]):
        payload["message"] = "No slots left on this day. Please pick another day."
    return payload
