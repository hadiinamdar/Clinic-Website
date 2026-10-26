import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine

from tests import _env  # noqa: F401
import database

LEGACY = """
CREATE TABLE appointments (
 id INTEGER NOT NULL, patient_name VARCHAR(100) NOT NULL, email VARCHAR(255) NOT NULL,
 phone VARCHAR(20) NOT NULL, appointment_date VARCHAR(10) NOT NULL, appointment_time VARCHAR(5) NOT NULL,
 reason VARCHAR(500), status VARCHAR(20) NOT NULL, PRIMARY KEY (id));
CREATE INDEX ix_appointments_id ON appointments (id);
"""


class MigrationTests(unittest.TestCase):
    def make(self, rows):
        path = Path(tempfile.mkdtemp()) / "old.db"
        con = sqlite3.connect(path)
        con.executescript(LEGACY)
        con.executemany("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?)", rows)
        con.commit(); con.close()
        return path

    def test_upgrades_in_place_without_losing_rows(self):
        path = self.make([
            (1, "Old Patient", "o@x.com", "9880735614", "2026-10-26", "10:00",
             "Consultation type: Ultrasound / scan | Pain in abdomen", "pending"),
            (2, "Plain", "p@x.com", "9880735615", "2026-10-26", "10:30", "no prefix", "confirmed"),
            (3, "OnlyType", "q@x.com", "9880735616", "2026-10-26", "11:00", "Consultation type: Health package", "pending"),
        ])
        eng = create_engine(f"sqlite:///{path.as_posix()}")
        database.run_migrations(eng)
        database.run_migrations(eng)  # idempotent
        with eng.connect() as c:
            rows = c.exec_driver_sql("SELECT id, service, reason FROM appointments ORDER BY id").fetchall()
            idx = [r[1] for r in c.exec_driver_sql("PRAGMA index_list(appointments)")]
        self.assertEqual(rows, [(1, "Ultrasound / scan", "Pain in abdomen"), (2, None, "no prefix"),
                                (3, "Health package", None)])
        self.assertIn("uq_active_appointment_date_time", idx)

    def test_duplicate_legacy_bookings_do_not_crash_startup(self):
        path = self.make([
            (1, "A", "a@x.com", "9880735614", "2026-10-26", "10:00", None, "pending"),
            (2, "B", "b@x.com", "9880735615", "2026-10-26", "10:00", None, "pending"),
        ])
        eng = create_engine(f"sqlite:///{path.as_posix()}")
        with self.assertLogs("clinic.db", level="WARNING"):
            database.run_migrations(eng)
        with eng.connect() as c:
            self.assertEqual(c.exec_driver_sql("SELECT count(*) FROM appointments").scalar(), 2)


if __name__ == "__main__":
    unittest.main()
