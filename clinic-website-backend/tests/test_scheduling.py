import unittest
from datetime import date, datetime

from tests import _env  # noqa: F401
import scheduling as sc

MON = date(2026, 10, 26)   # a Monday
SUN = date(2026, 10, 25)   # a Sunday


def at(day, hh, mm=0):
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=sc.IST)


class SlotTests(unittest.TestCase):
    def test_weekday_slots(self):
        t = sc.slot_times(MON)
        self.assertEqual(len(t), 16)
        self.assertEqual((t[0], t[8], t[9], t[-1]), ("09:30", "13:30", "17:00", "20:00"))

    def test_sunday_slots(self):
        self.assertEqual(sc.slot_times(SUN), ["10:30", "11:00", "11:30", "12:00"])

    def test_closed_date(self):
        self.assertEqual(sc.slot_times(MON, ["2026-10-26"]), [])

    def test_labels(self):
        self.assertEqual(sc.format_label("09:30"), "9:30 AM")
        self.assertEqual(sc.format_label("12:00"), "12:00 PM")
        self.assertEqual(sc.format_label("13:30"), "1:30 PM")
        self.assertEqual(sc.format_label("00:00"), "12:00 AM")


class BookableTests(unittest.TestCase):
    now = at(MON, 10, 0)

    def ok(self, day, t, **kw):
        sc.check_bookable(day, t, now=self.now, **kw)

    def bad(self, day, t, text, **kw):
        with self.assertRaises(sc.ScheduleError) as cm:
            self.ok(day, t, **kw)
        self.assertIn(text, str(cm.exception))

    def test_ok(self):
        self.ok(MON, "17:00")
        self.ok(date(2026, 10, 27), "09:30")

    def test_past_date(self):
        self.bad(SUN, "11:00", "in the past")

    def test_off_grid_and_outside_hours(self):
        self.bad(date(2026, 10, 27), "09:45", "outside booking hours")
        self.bad(date(2026, 10, 27), "15:00", "outside booking hours")
        self.bad(date(2026, 11, 1), "09:30", "outside booking hours")  # Sunday opens 10:30

    def test_lead_time(self):
        self.bad(MON, "10:00", "too close")
        self.bad(MON, "10:30", "too close", lead_minutes=45)
        self.ok(MON, "10:30", lead_minutes=30)

    def test_closed_and_far_future(self):
        self.bad(date(2026, 10, 27), "10:00", "closed", closed_dates=["2026-10-27"])
        self.bad(date(2027, 3, 1), "10:00", "in advance")


class PayloadTests(unittest.TestCase):
    def test_today_marks_past_and_booked(self):
        p = sc.slots_payload(MON, booked={"11:00"}, now=at(MON, 10, 0), lead_minutes=30)
        by = {s["time"]: s["available"] for s in p["slots"]}
        self.assertFalse(by["09:30"])
        self.assertFalse(by["10:00"])
        self.assertTrue(by["10:30"])
        self.assertFalse(by["11:00"])
        self.assertTrue(by["17:00"])
        self.assertFalse(p["closed"])

    def test_closed_and_past_days(self):
        self.assertTrue(sc.slots_payload(MON, now=at(MON, 9), closed_dates=["2026-10-26"])["closed"])
        self.assertTrue(sc.slots_payload(SUN, now=at(MON, 9))["closed"])

    def test_full_day_message(self):
        tue = date(2026, 10, 27)
        p = sc.slots_payload(tue, booked=set(sc.slot_times(tue)), now=at(MON, 9))
        self.assertIn("No slots left", p["message"])


if __name__ == "__main__":
    unittest.main()
