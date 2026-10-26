import unittest
from datetime import date, datetime
from types import SimpleNamespace

from tests import _env  # noqa: F401
import database
import models
import scheduling as sc
import services as svc

S = SimpleNamespace(booking_lead_minutes=30, booking_max_days_ahead=60, max_active_per_phone=3)
NOW = datetime(2026, 10, 24, 9, 0, tzinfo=sc.IST)       # Saturday morning
MON, TUE = date(2026, 10, 26), date(2026, 10, 27)


class DbCase(unittest.TestCase):
    def setUp(self):
        database.Base.metadata.drop_all(database.engine)
        database.init_db()
        self.db = database.SessionLocal()

    def tearDown(self):
        self.db.close()

    def book(self, **kw):
        args = dict(patient_name="Asha Rao", email="Asha@Example.com", phone="98807 35614",
                    appointment_date=MON, appointment_time="10:00", service=None, reason=None,
                    settings=S, now=NOW)
        args.update(kw)
        return svc.create_appointment(self.db, **args)

    def fails(self, code, **kw):
        with self.assertRaises(svc.ServiceError) as cm:
            self.book(**kw)
        self.assertEqual(cm.exception.status_code, code)
        return cm.exception.message


class BookingTests(DbCase):
    def test_success_normalises_input(self):
        a = self.book(reason="  Fever \n for 2 days ")
        self.assertEqual((a.status, a.email, a.phone), ("pending", "asha@example.com", "9880735614"))
        self.assertEqual(a.service, "In-clinic consultation")
        self.assertEqual(a.created_at, "2026-10-24T09:00:00+05:30")
        self.assertEqual(a.reason, "Fever \n for 2 days")

    def test_double_booking_and_cancel_frees_slot(self):
        first = self.book()
        self.assertIn("already booked", self.fails(409, phone="9739549031"))
        svc.update_status(self.db, first.id, "cancelled")
        self.book(phone="9739549031")                    # slot is free again

    def test_reinstating_cancelled_into_taken_slot_is_409(self):
        first = self.book()
        svc.update_status(self.db, first.id, "cancelled")
        self.book(phone="9739549031")
        with self.assertRaises(svc.ServiceError) as cm:
            svc.update_status(self.db, first.id, "pending")
        self.assertEqual(cm.exception.status_code, 409)

    def test_schedule_rules(self):
        self.fails(400, appointment_time="09:45")
        self.fails(400, appointment_date=date(2026, 10, 23))
        self.fails(400, appointment_date=MON, closed_dates=["2026-10-26"])
        self.fails(400, appointment_date=date(2026, 10, 24), appointment_time="09:30",
                   now=datetime(2026, 10, 24, 9, 10, tzinfo=sc.IST))  # inside lead time

    def test_validation(self):
        self.fails(422, patient_name="<script>")
        self.fails(422, patient_name="A")
        self.fails(422, phone="12345")
        self.fails(422, email="nope")
        self.fails(422, service="Free lunch")

    def test_phone_limit(self):
        for t in ("10:00", "10:30", "11:00"):
            self.book(appointment_time=t)
        self.assertIn("maximum", self.fails(429, appointment_time="11:30"))
        self.book(appointment_time="11:30", phone="9739549031")  # other phone unaffected


class AvailabilityTests(DbCase):
    def test_booked_slot_unavailable(self):
        self.book(appointment_time="10:30")
        p = svc.slots_for_date(self.db, MON, settings=S, now=NOW)
        by = {s["time"]: s["available"] for s in p["slots"]}
        self.assertFalse(by["10:30"])
        self.assertTrue(by["10:00"])


class AdminTests(DbCase):
    def setUp(self):
        super().setUp()
        self.a = self.book(patient_name="Asha Rao", appointment_time="10:00")
        self.b = self.book(patient_name="Bilal 100%", phone="9739549031", appointment_date=TUE,
                           appointment_time="09:30", email="b@x.com")
        self.c = self.book(patient_name="Chitra", phone="9000000001", appointment_date=TUE,
                           appointment_time="10:00", email="c@x.com")

    def test_filters_and_order(self):
        total, rows = svc.list_appointments(self.db)
        self.assertEqual((total, [r.id for r in rows]), (3, [3, 2, 1]))
        _, rows = svc.list_appointments(self.db, order="date")
        self.assertEqual([r.id for r in rows], [1, 2, 3])
        self.assertEqual(svc.list_appointments(self.db, date_from=TUE)[0], 2)
        self.assertEqual(svc.list_appointments(self.db, date_to=MON)[0], 1)
        self.assertEqual(svc.list_appointments(self.db, q="chit")[0], 1)
        self.assertEqual(svc.list_appointments(self.db, q="9739549031")[0], 1)
        self.assertEqual(svc.list_appointments(self.db, q="%")[0], 1)    # wildcard is literal
        self.assertEqual(svc.list_appointments(self.db, q="_")[0], 0)
        self.assertEqual(svc.list_appointments(self.db, limit=1, offset=1)[1][0].id, 2)
        with self.assertRaises(svc.ServiceError):
            svc.list_appointments(self.db, status="bogus")

    def test_status_flow_and_stats(self):
        item, changed = svc.update_status(self.db, self.a.id, "confirmed")
        self.assertTrue(changed)
        _, changed = svc.update_status(self.db, self.a.id, "confirmed")
        self.assertFalse(changed)
        st = svc.stats(self.db, today=MON)
        self.assertEqual((st["today"], st["pending"], st["upcoming_confirmed"], st["total"]), (1, 2, 1, 3))
        with self.assertRaises(svc.ServiceError):
            svc.update_status(self.db, 999, "confirmed")
        with self.assertRaises(svc.ServiceError):
            svc.update_status(self.db, self.a.id, "nope")

    def test_delete(self):
        svc.delete_appointment(self.db, self.a.id)
        self.assertEqual(svc.list_appointments(self.db)[0], 2)
        with self.assertRaises(svc.ServiceError):
            svc.delete_appointment(self.db, self.a.id)

    def test_csv_blocks_formula_injection(self):
        evil = self.book(patient_name="=HYPERLINK(\"x\")", phone="9111111111", appointment_time="11:00",
                         email="e@x.com", reason="+cmd")
        text = svc.appointments_csv([evil])
        self.assertTrue(text.startswith("\ufeffRef,"))
        self.assertIn("'=HYPERLINK", text)
        self.assertIn("'+cmd", text)


class NewsletterTests(DbCase):
    def test_subscribe_idempotent(self):
        self.assertTrue(svc.subscribe(self.db, "Fan@Example.com", now=NOW))
        self.assertFalse(svc.subscribe(self.db, "fan@example.com", now=NOW))
        self.assertEqual([r["email"] for r in svc.list_subscribers(self.db)], ["fan@example.com"])
        with self.assertRaises(svc.ServiceError):
            svc.subscribe(self.db, "bad")


if __name__ == "__main__":
    unittest.main()
