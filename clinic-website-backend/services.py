"""Business logic. Knows about the database but not about HTTP/FastAPI."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models
import scheduling
import validation

STATUSES = ("pending", "confirmed", "cancelled", "completed")
ACTIVE_STATUSES = ("pending", "confirmed")


class ServiceError(Exception):
    """A request that cannot be fulfilled. Maps cleanly onto an HTTP error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ------------------------------------------------------------------ helpers
def serialize(item: models.Appointment) -> dict:
    return {
        "appointment_id": item.id,
        "patient_name": item.patient_name,
        "email": item.email,
        "phone": item.phone,
        "appointment_date": item.appointment_date,
        "appointment_time": item.appointment_time,
        "time_label": scheduling.format_label(item.appointment_time),
        "service": item.service,
        "reason": item.reason,
        "status": item.status,
        "created_at": item.created_at,
    }


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtered_query(db: Session, status, date_from, date_to, q):
    query = db.query(models.Appointment)
    if status:
        if status not in STATUSES:
            raise ServiceError(400, "Invalid status. Use pending, confirmed, cancelled, or completed.")
        query = query.filter(models.Appointment.status == status)
    if date_from:
        query = query.filter(models.Appointment.appointment_date >= date_from.isoformat())
    if date_to:
        query = query.filter(models.Appointment.appointment_date <= date_to.isoformat())
    if q and q.strip():
        like = f"%{_escape_like(q.strip())}%"
        query = query.filter(
            or_(
                models.Appointment.patient_name.ilike(like, escape="\\"),
                models.Appointment.phone.ilike(like, escape="\\"),
                models.Appointment.email.ilike(like, escape="\\"),
            )
        )
    return query


# ------------------------------------------------------------------ availability
def booked_times(db: Session, day: date) -> set[str]:
    rows = (
        db.query(models.Appointment.appointment_time)
        .filter(
            models.Appointment.appointment_date == day.isoformat(),
            models.Appointment.status != "cancelled",
        )
        .all()
    )
    return {r[0] for r in rows}


def slots_for_date(db: Session, day: date, *, settings, closed_dates=(), now: datetime | None = None) -> dict:
    return scheduling.slots_payload(
        day,
        booked_times(db, day),
        now=now,
        lead_minutes=settings.booking_lead_minutes,
        max_days_ahead=settings.booking_max_days_ahead,
        closed_dates=closed_dates,
    )


# ------------------------------------------------------------------ appointments
def create_appointment(
    db: Session,
    *,
    patient_name: str,
    email: str,
    phone: str,
    appointment_date: date,
    appointment_time: str,
    service: str | None,
    reason: str | None,
    settings,
    closed_dates=(),
    now: datetime | None = None,
) -> models.Appointment:
    now = now or scheduling.now_ist()
    try:
        name = validation.normalize_name(patient_name)
        email = validation.normalize_email(email)
        phone = validation.normalize_phone(phone)
        reason = validation.normalize_reason(reason)
    except validation.ValidationFailed as exc:
        raise ServiceError(422, str(exc)) from exc

    service = (service or "").strip() or scheduling.DEFAULT_SERVICE
    if service not in scheduling.SERVICES:
        raise ServiceError(422, "Please choose one of the listed consultation types.")

    try:
        scheduling.check_bookable(
            appointment_date,
            appointment_time,
            now=now,
            lead_minutes=settings.booking_lead_minutes,
            max_days_ahead=settings.booking_max_days_ahead,
            closed_dates=closed_dates,
        )
    except scheduling.ScheduleError as exc:
        raise ServiceError(400, str(exc)) from exc

    active = (
        db.query(models.Appointment)
        .filter(
            models.Appointment.phone == phone,
            models.Appointment.status.in_(ACTIVE_STATUSES),
            models.Appointment.appointment_date >= now.date().isoformat(),
        )
        .count()
    )
    if active >= settings.max_active_per_phone:
        raise ServiceError(
            429,
            "This phone number already has the maximum number of upcoming appointments. "
            "Please call the clinic to book more.",
        )

    item = models.Appointment(
        patient_name=name,
        email=email,
        phone=phone,
        appointment_date=appointment_date.isoformat(),
        appointment_time=appointment_time,
        service=service,
        reason=reason,
        status="pending",
        created_at=now.isoformat(timespec="seconds"),
    )
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise ServiceError(
            409,
            "This appointment date and time is already booked. Please choose another slot.",
        )
    return item


def list_appointments(
    db: Session,
    *,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    order: str = "newest",
    limit: int = 200,
    offset: int = 0,
):
    query = _filtered_query(db, status, date_from, date_to, q)
    total = query.count()
    if order == "date":
        query = query.order_by(models.Appointment.appointment_date.asc(), models.Appointment.appointment_time.asc())
    else:
        query = query.order_by(models.Appointment.id.desc())
    return total, query.offset(max(offset, 0)).limit(max(1, min(limit, 1000))).all()


def update_status(db: Session, appointment_id: int, status: str) -> tuple[models.Appointment, bool]:
    if status not in STATUSES:
        raise ServiceError(400, "Invalid status. Use pending, confirmed, cancelled, or completed.")
    item = db.get(models.Appointment, appointment_id)
    if item is None:
        raise ServiceError(404, "Appointment not found")
    changed = item.status != status
    item.status = status
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ServiceError(409, "This time slot is already reserved by another appointment.")
    db.refresh(item)
    return item, changed


def delete_appointment(db: Session, appointment_id: int) -> None:
    item = db.get(models.Appointment, appointment_id)
    if item is None:
        raise ServiceError(404, "Appointment not found")
    db.delete(item)
    db.commit()


def stats(db: Session, *, today: date | None = None) -> dict:
    today = today or scheduling.now_ist().date()
    iso = today.isoformat()
    A = models.Appointment
    return {
        "today": db.query(A).filter(A.appointment_date == iso, A.status != "cancelled").count(),
        "pending": db.query(A).filter(A.status == "pending").count(),
        "upcoming_confirmed": db.query(A).filter(A.status == "confirmed", A.appointment_date >= iso).count(),
        "total": db.query(A).count(),
        "subscribers": db.query(models.Subscriber).count(),
    }


# ------------------------------------------------------------------ newsletter
def subscribe(db: Session, email: str, *, now: datetime | None = None) -> bool:
    """Add an address. Returns False if it was already subscribed (not an error)."""
    try:
        email = validation.normalize_email(email)
    except validation.ValidationFailed as exc:
        raise ServiceError(422, str(exc)) from exc
    if db.query(models.Subscriber).filter(models.Subscriber.email == email).first():
        return False
    stamp = (now or scheduling.now_ist()).isoformat(timespec="seconds")
    try:
        db.add(models.Subscriber(email=email, created_at=stamp))
        db.commit()
    except IntegrityError:  # lost a race with an identical request
        db.rollback()
        return False
    return True


def list_subscribers(db: Session) -> list[dict]:
    rows = db.query(models.Subscriber).order_by(models.Subscriber.id.desc()).all()
    return [{"id": r.id, "email": r.email, "created_at": r.created_at} for r in rows]


# ------------------------------------------------------------------ CSV export
def _csv_safe(value) -> str:
    """Neutralise spreadsheet formulas (CSV injection) in user-supplied text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def appointments_csv(rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Ref", "Date", "Time", "Patient", "Phone", "Email", "Service", "Reason", "Status", "Requested at"])
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.appointment_date,
                scheduling.format_label(r.appointment_time),
                _csv_safe(r.patient_name),
                _csv_safe(r.phone),
                _csv_safe(r.email),
                _csv_safe(r.service),
                _csv_safe(r.reason),
                r.status,
                r.created_at or "",
            ]
        )
    return "\ufeff" + out.getvalue()  # BOM so Excel reads UTF-8 names correctly


def subscribers_csv(rows: list[dict]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Email", "Subscribed at"])
    for r in rows:
        writer.writerow([_csv_safe(r["email"]), r["created_at"] or ""])
    return "\ufeff" + out.getvalue()
