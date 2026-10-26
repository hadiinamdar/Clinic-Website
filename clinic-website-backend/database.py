import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import declarative_base, sessionmaker

from config import get_settings

log = logging.getLogger("clinic.db")

DATABASE_URL = get_settings().database_url  # default: clinic.db next to this file

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # check_same_thread: FastAPI runs sync routes in a thread pool.
    # timeout: wait (seconds) instead of failing if two writes collide.
    _connect_args = {"check_same_thread": False, "timeout": 15}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_LEGACY_PREFIX = "Consultation type: "


def run_migrations(bind=None) -> None:
    """Upgrade databases created by earlier versions, in place and without data loss.

    * adds the ``service`` and ``created_at`` columns,
    * moves the consultation type out of the old ``reason`` text,
    * makes sure the "one active appointment per slot" index exists.
    """
    bind = bind or engine
    if bind.dialect.name != "sqlite":
        return

    with bind.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(appointments)")}
        if not cols:
            return
        if "service" not in cols:
            conn.exec_driver_sql("ALTER TABLE appointments ADD COLUMN service VARCHAR(60)")
        if "created_at" not in cols:
            conn.exec_driver_sql("ALTER TABLE appointments ADD COLUMN created_at VARCHAR(32)")

        legacy = conn.exec_driver_sql(
            "SELECT id, reason FROM appointments WHERE service IS NULL AND reason LIKE ?",
            (_LEGACY_PREFIX + "%",),
        ).fetchall()
        for row_id, reason in legacy:
            head, _, rest = reason[len(_LEGACY_PREFIX):].partition(" | ")
            conn.exec_driver_sql(
                "UPDATE appointments SET service = ?, reason = ? WHERE id = ?",
                (head.strip()[:60] or None, rest.strip() or None, row_id),
            )

    try:
        with bind.begin() as conn:
            conn.exec_driver_sql(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_appointment_date_time "
                "ON appointments (appointment_date, appointment_time) "
                "WHERE status != 'cancelled'"
            )
    except SQLAlchemyError as exc:  # pre-existing double bookings in old data
        log.warning(
            "Could not add the unique slot index (existing duplicate bookings?): %s. "
            "Cancel or delete the duplicates and restart.",
            exc,
        )


def init_db() -> None:
    import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(bind=engine)
    run_migrations()
