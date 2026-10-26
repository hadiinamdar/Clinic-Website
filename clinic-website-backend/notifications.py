"""Optional e-mail notifications (plain text, standard library only).

Nothing is sent unless SMTP_HOST and SMTP_FROM are set in ``.env``. Messages are
built from already-validated data *while the request is still open* and sent
afterwards in a background task, so a slow mail server never delays a booking.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from config import CLINIC

log = logging.getLogger("clinic.mail")

Message = tuple[str, str, str]  # (to, subject, body)


def _when(appt: dict) -> str:
    day = date.fromisoformat(appt["appointment_date"])
    return f"{day.strftime('%A, %d %B %Y')} at {appt['time_label']}"


def _footer() -> str:
    return (
        f"\n--\n{CLINIC['name']}\n{CLINIC['address']}\n"
        f"Phone: {', '.join(CLINIC['phones'])}\n{CLINIC['email']}\n"
    )


def booking_messages(settings, appt: dict) -> list[Message]:
    """Acknowledgement to the patient + alert to the clinic for a new request."""
    msgs: list[Message] = []
    if settings.email_enabled:
        msgs.append(
            (
                appt["email"],
                f"We received your appointment request (Ref #{appt['appointment_id']})",
                f"Dear {appt['patient_name']},\n\n"
                "Thank you for choosing Care Scan & Diagnostic Centre. We have received your request:\n\n"
                f"  Reference : #{appt['appointment_id']}\n"
                f"  Service   : {appt['service']}\n"
                f"  When      : {_when(appt)}\n\n"
                "This is not yet a confirmed booking. The clinic will confirm it shortly, and you will "
                "get another e-mail. If you need to change or cancel, please call us and quote your reference."
                + _footer(),
            )
        )
        msgs.append(
            (
                settings.notify_email,
                f"New appointment request #{appt['appointment_id']} - {appt['patient_name']}",
                "A new appointment request needs confirmation.\n\n"
                f"  Patient : {appt['patient_name']}\n"
                f"  Phone   : {appt['phone']}\n"
                f"  Email   : {appt['email']}\n"
                f"  Service : {appt['service']}\n"
                f"  When    : {_when(appt)}\n"
                f"  Reason  : {appt['reason'] or '-'}\n\n"
                "Open the admin page (/admin) to confirm or cancel it.",
            )
        )
    return msgs


def status_messages(settings, appt: dict) -> list[Message]:
    """Tell the patient when the clinic confirms or cancels."""
    if not settings.email_enabled or appt["status"] not in ("confirmed", "cancelled"):
        return []
    if appt["status"] == "confirmed":
        subject = f"Your appointment is confirmed (Ref #{appt['appointment_id']})"
        lead = "Good news - your appointment is confirmed."
        tail = "Please arrive a few minutes early and bring any previous reports."
    else:
        subject = f"Your appointment was cancelled (Ref #{appt['appointment_id']})"
        lead = "Your appointment has been cancelled."
        tail = "If this is unexpected, or you would like to rebook, please call us."
    body = (
        f"Dear {appt['patient_name']},\n\n{lead}\n\n"
        f"  Reference : #{appt['appointment_id']}\n"
        f"  Service   : {appt['service']}\n"
        f"  When      : {_when(appt)}\n\n{tail}" + _footer()
    )
    return [(appt["email"], subject, body)]


def _send(settings, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(body)

    context = ssl.create_default_context()
    if settings.smtp_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
    with server:
        if not settings.smtp_ssl and settings.smtp_starttls:
            server.starttls(context=context)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


def dispatch(settings, messages: list[Message]) -> int:
    """Send every message, never raising. Returns how many were accepted."""
    sent = 0
    for to, subject, body in messages:
        try:
            _send(settings, to, subject, body)
            sent += 1
        except Exception as exc:  # network/auth problems must not break bookings
            log.error("Could not e-mail %s (%s): %s", to, subject, exc)
    return sent
