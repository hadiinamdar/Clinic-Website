"""Central configuration.

Settings come from environment variables, optionally loaded from a ``.env``
file that sits next to this file (see ``.env.example``).

Doctor/clinic content that appears on the website lives in
``clinic_config.json`` (see README) and is re-read automatically when the file
changes, so editing it never needs a code change.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("clinic.config")

BASE_DIR = Path(__file__).resolve().parent
CLINIC_CONFIG_PATH = BASE_DIR / "clinic_config.json"

# Facts printed on the clinic letterhead. Used in e-mails and the admin page.
CLINIC = {
    "name": "Care Scan & Diagnostic Centre",
    "tagline": "the care u can trust",
    "address": "#183, A.G. Heights, K.B.A.R Road, Austin Town, Bengaluru - 560047",
    "phones": ["9880735614", "9739549031"],
    "email": "karediagnosticslab@gmail.com",
}


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=value per line). Real environment wins."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        log.warning("%s is not a number; using %s", name, default)
        return default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    frontend_dir: Path
    admin_password: str
    secret_key: str
    token_ttl_minutes: int
    cors_origins: tuple[str, ...]
    trust_proxy: bool
    booking_lead_minutes: int
    booking_max_days_ahead: int
    max_active_per_phone: int
    booking_rate_limit_per_hour: int
    login_max_failures: int
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_ssl: bool
    smtp_starttls: bool
    notify_email: str

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def admin_enabled(self) -> bool:
        return bool(self.admin_password)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


def load_settings() -> Settings:
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    secret = os.getenv("SECRET_KEY", "").strip()
    if not secret:
        # Stable across restarts, and changes (invalidating sessions) when the
        # admin password changes.
        secret = hashlib.sha256(f"clinic-admin-token:{admin_password}".encode()).hexdigest()

    default_db = "sqlite:///" + (BASE_DIR / "clinic.db").as_posix()
    origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    smtp_port = _int("SMTP_PORT", 587)
    smtp_ssl = _bool("SMTP_SSL", smtp_port == 465)

    return Settings(
        env=os.getenv("APP_ENV", "development").strip().lower(),
        database_url=os.getenv("DATABASE_URL", "").strip() or default_db,
        frontend_dir=Path(os.getenv("FRONTEND_DIR", "").strip() or BASE_DIR.parent).resolve(),
        admin_password=admin_password,
        secret_key=secret,
        token_ttl_minutes=_int("ADMIN_SESSION_MINUTES", 480),
        cors_origins=tuple(origins) or ("*",),
        trust_proxy=_bool("TRUST_PROXY", False),
        booking_lead_minutes=_int("BOOKING_LEAD_MINUTES", 30),
        booking_max_days_ahead=_int("BOOKING_MAX_DAYS_AHEAD", 60),
        max_active_per_phone=_int("MAX_ACTIVE_PER_PHONE", 3),
        booking_rate_limit_per_hour=_int("BOOKING_RATE_LIMIT_PER_HOUR", 20),
        login_max_failures=_int("LOGIN_MAX_FAILURES", 5),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=smtp_port,
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        smtp_ssl=smtp_ssl,
        smtp_starttls=_bool("SMTP_STARTTLS", not smtp_ssl),
        notify_email=os.getenv("NOTIFY_EMAIL", "").strip() or CLINIC["email"],
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


# ---------------------------------------------------------------- clinic_config.json
CLINIC_CONFIG_DEFAULTS: dict = {
    "doctor_name": "",
    "specialty": "",
    "years_experience": "",
    "qualifications": "",
    "postgraduate_qualification": "",
    "registration_number": "",
    "memberships": "",
    "fellowships": "",
    "awards_and_research": "",
    "hide_placeholder_notes": False,
    "show_sample_reviews": True,
    "closed_dates": [],
}

_clinic_cache: dict = {"mtime": None, "path": None, "data": dict(CLINIC_CONFIG_DEFAULTS)}


def get_clinic_config(path: Path | None = None) -> dict:
    """Return clinic_config.json merged over the defaults (re-read on change)."""
    path = Path(path) if path else CLINIC_CONFIG_PATH
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return dict(CLINIC_CONFIG_DEFAULTS)
    if _clinic_cache["mtime"] == mtime and _clinic_cache["path"] == str(path):
        return _clinic_cache["data"]

    data = dict(CLINIC_CONFIG_DEFAULTS)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            for key in CLINIC_CONFIG_DEFAULTS:
                if key in loaded:
                    data[key] = loaded[key]
    except (OSError, ValueError) as exc:
        log.error("Could not read %s (%s); using defaults", path.name, exc)

    # normalise types so the rest of the code can rely on them
    for key, default in CLINIC_CONFIG_DEFAULTS.items():
        if isinstance(default, str):
            data[key] = str(data[key] or "").strip()
        elif isinstance(default, bool):
            data[key] = bool(data[key])
    closed = data.get("closed_dates") or []
    data["closed_dates"] = sorted({str(d).strip() for d in closed if str(d).strip()}) if isinstance(closed, list) else []

    _clinic_cache.update(mtime=mtime, path=str(path), data=data)
    return data
