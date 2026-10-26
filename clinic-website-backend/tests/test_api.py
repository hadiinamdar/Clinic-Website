"""End-to-end tests of the HTTP API. Needs:  pip install -r requirements-dev.txt"""
import unittest
from datetime import timedelta

from tests import _env  # noqa: F401
import scheduling as sc

try:
    from fastapi.testclient import TestClient
    import main
    HAVE = True
except ImportError:  # fastapi/httpx not installed
    HAVE = False


def next_open_day(min_days=2):
    d = sc.now_ist().date() + timedelta(days=min_days)
    while d.weekday() == 6:  # skip Sunday (different hours)
        d += timedelta(days=1)
    return d


@unittest.skipUnless(HAVE, "fastapi + httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        import database
        database.Base.metadata.drop_all(database.engine)
        database.init_db()
        main.login_limiter._hits.clear()
        self.c = TestClient(main.app)
        self.day = next_open_day().isoformat()

    def body(self, **kw):
        b = {"patient_name": "Asha Rao", "email": "asha@example.com", "phone": "9880735614",
             "appointment_date": self.day, "appointment_time": "10:00", "service": "Ultrasound / scan"}
        b.update(kw)
        return b

    def token(self):
        r = self.c.post("/admin/login", json={"password": "test-password-123"})
        self.assertEqual(r.status_code, 200)
        return {"Authorization": "Bearer " + r.json()["token"]}

    # ---- public
    def test_slots_and_booking_flow(self):
        r = self.c.get("/appointments/slots", params={"date": self.day})
        self.assertEqual(r.status_code, 200)
        slot = next(s for s in r.json()["slots"] if s["time"] == "10:00")
        self.assertTrue(slot["available"])

        r = self.c.post("/appointments", json=self.body())
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["status"], "pending")

        again = self.c.post("/appointments", json=self.body(phone="9739549031"))
        self.assertEqual(again.status_code, 409)

        slots = self.c.get("/appointments/slots", params={"date": self.day}).json()["slots"]
        self.assertFalse(next(s for s in slots if s["time"] == "10:00")["available"])

    def test_booking_validation(self):
        self.assertEqual(self.c.post("/appointments", json=self.body(appointment_time="10:07")).status_code, 400)
        self.assertEqual(self.c.post("/appointments", json=self.body(email="nope")).status_code, 422)
        self.assertEqual(self.c.post("/appointments", json=self.body(phone="123")).status_code, 422)
        self.assertEqual(self.c.post("/appointments", json=self.body(appointment_date="2020-01-01")).status_code, 400)

    def test_honeypot_stores_nothing(self):
        r = self.c.post("/appointments", json=self.body(website="http://spam"))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.get("/appointments", headers=self.token()).json()["total"], 0)

    def test_newsletter(self):
        self.assertEqual(self.c.post("/newsletter", json={"email": "a@b.com"}).status_code, 201)
        self.assertEqual(self.c.post("/newsletter", json={"email": "a@b.com"}).status_code, 201)
        h = self.token()
        self.assertEqual(self.c.get("/admin/subscribers", headers=h).json()["total"], 1)

    # ---- admin protection
    def test_admin_routes_require_login(self):
        self.assertEqual(self.c.get("/appointments").status_code, 401)
        self.assertEqual(self.c.get("/admin/stats").status_code, 401)
        self.assertEqual(self.c.get("/admin/appointments.csv").status_code, 401)
        self.assertEqual(self.c.patch("/appointments/1/status", params={"status": "confirmed"}).status_code, 401)
        self.assertEqual(self.c.delete("/appointments/1").status_code, 401)
        self.assertEqual(self.c.get("/appointments", headers={"Authorization": "Bearer junk"}).status_code, 401)

    def test_login(self):
        self.assertEqual(self.c.post("/admin/login", json={"password": "wrong"}).status_code, 401)
        for _ in range(main.settings.login_max_failures):
            self.c.post("/admin/login", json={"password": "wrong"})
        self.assertEqual(self.c.post("/admin/login", json={"password": "test-password-123"}).status_code, 429)

    def test_admin_manage_appointments(self):
        self.c.post("/appointments", json=self.body())
        h = self.token()
        listing = self.c.get("/appointments", headers=h).json()
        self.assertEqual(listing["total"], 1)
        ref = listing["items"][0]["appointment_id"]
        self.assertEqual(self.c.get("/admin/stats", headers=h).json()["pending"], 1)

        r = self.c.patch(f"/appointments/{ref}/status", params={"status": "confirmed"}, headers=h)
        self.assertEqual(r.json()["status"], "confirmed")
        self.assertEqual(self.c.patch(f"/appointments/{ref}/status", params={"status": "x"}, headers=h).status_code, 400)
        self.assertEqual(self.c.patch("/appointments/999/status", params={"status": "confirmed"}, headers=h).status_code, 404)

        csv = self.c.get("/admin/appointments.csv", headers=h)
        self.assertEqual(csv.status_code, 200)
        self.assertIn("text/csv", csv.headers["content-type"])
        self.assertIn("Asha Rao", csv.text)

        self.assertEqual(self.c.delete(f"/appointments/{ref}", headers=h).status_code, 200)
        self.assertEqual(self.c.get("/appointments", headers=h).json()["total"], 0)

    # ---- site
    def test_site_pages(self):
        home = self.c.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Care Scan", home.text)
        self.assertEqual(self.c.get("/admin").status_code, 200)
        self.assertIn("Disallow: /admin", self.c.get("/robots.txt").text)
        self.assertEqual(self.c.get("/assets/logo-emblem.png").status_code, 200)
        self.assertEqual(self.c.get("/health").json(), {"status": "healthy"})
        self.assertEqual(self.c.get("/db-health").json(), {"database": "connected"})
        self.assertEqual(self.c.get("/assets/../clinic.db").status_code, 404)
        self.assertEqual(home.headers["x-content-type-options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
