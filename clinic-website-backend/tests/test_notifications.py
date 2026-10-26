import unittest
from types import SimpleNamespace
from unittest import mock

from tests import _env  # noqa: F401
import notifications as n

ON = SimpleNamespace(email_enabled=True, notify_email="clinic@x.com", smtp_from="no-reply@x.com",
                     smtp_host="smtp.x.com", smtp_port=587, smtp_user="u", smtp_password="p",
                     smtp_ssl=False, smtp_starttls=True)
OFF = SimpleNamespace(email_enabled=False)
APPT = {"appointment_id": 7, "patient_name": "Asha", "email": "a@x.com", "phone": "9880735614",
        "appointment_date": "2026-10-26", "time_label": "10:00 AM", "service": "Ultrasound / scan",
        "reason": None, "status": "pending"}


class MessageTests(unittest.TestCase):
    def test_disabled_sends_nothing(self):
        self.assertEqual(n.booking_messages(OFF, APPT), [])
        self.assertEqual(n.status_messages(OFF, dict(APPT, status="confirmed")), [])

    def test_booking_messages(self):
        patient, clinic = n.booking_messages(ON, APPT)
        self.assertEqual(patient[0], "a@x.com")
        self.assertIn("Monday, 26 October 2026 at 10:00 AM", patient[2])
        self.assertIn("not yet a confirmed", patient[2])
        self.assertEqual(clinic[0], "clinic@x.com")

    def test_status_messages(self):
        self.assertEqual(n.status_messages(ON, APPT), [])  # pending: nothing
        self.assertIn("confirmed", n.status_messages(ON, dict(APPT, status="confirmed"))[0][1])
        self.assertIn("cancelled", n.status_messages(ON, dict(APPT, status="cancelled"))[0][1])


class SendTests(unittest.TestCase):
    def test_dispatch_uses_starttls_login_and_send(self):
        with mock.patch.object(n.smtplib, "SMTP") as smtp:
            server = smtp.return_value
            self.assertEqual(n.dispatch(ON, [("a@x.com", "Hi", "Body")]), 1)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("u", "p")
        msg = server.send_message.call_args[0][0]
        self.assertEqual((msg["To"], msg["Subject"]), ("a@x.com", "Hi"))

    def test_failure_never_raises(self):
        with mock.patch.object(n.smtplib, "SMTP", side_effect=OSError("down")):
            with self.assertLogs("clinic.mail", level="ERROR"):
                self.assertEqual(n.dispatch(ON, [("a@x.com", "Hi", "Body")]), 0)


if __name__ == "__main__":
    unittest.main()
