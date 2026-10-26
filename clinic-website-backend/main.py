import logging
from datetime import date

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

import notifications
import security
import services
import siteconfig
from config import get_clinic_config, get_settings
from database import engine, get_db, init_db

log = logging.getLogger("clinic.api")
settings = get_settings()

app = FastAPI(
    title="Clinic Management API",
    description="Backend API for the Care Scan & Diagnostic Centre website",
    version="2.0.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Creates tables and upgrades older databases in place (safe to run every start).
init_db()
if not settings.admin_enabled:
    log.warning("ADMIN_PASSWORD is not set: the /admin page and appointment management are disabled.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,  # admin uses a Bearer token, never cookies
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.exception_handler(services.ServiceError)
async def service_error_handler(request: Request, exc: services.ServiceError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


booking_limiter = security.RateLimiter(3600)
newsletter_limiter = security.RateLimiter(3600)
login_limiter = security.RateLimiter(900)


# ------------------------------------------------------------------ schemas
class AppointmentCreate(BaseModel):
    patient_name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=8, max_length=20)
    appointment_date: date
    appointment_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    service: str | None = Field(default=None, max_length=60)
    reason: str | None = Field(default=None, max_length=500)
    website: str | None = Field(default=None, max_length=200)  # honeypot: humans leave it empty


class NewsletterSignup(BaseModel):
    email: EmailStr
    website: str | None = Field(default=None, max_length=200)  # honeypot


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


# ------------------------------------------------------------------ helpers
def client_ip(request: Request) -> str:
    """Client address for rate limiting.

    With TRUST_PROXY=true (exactly one reverse proxy in front) the address the
    proxy appended to X-Forwarded-For is used; otherwise the socket peer.
    """
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not settings.admin_enabled:
        raise HTTPException(503, "Admin access is not configured. Set ADMIN_PASSWORD in the .env file.")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not security.verify_token(settings.secret_key, token.strip()):
        raise HTTPException(401, "Your admin session has expired. Please sign in again.", headers={"WWW-Authenticate": "Bearer"})


_site_cache: dict = {"key": None, "html": ""}


def render_site() -> str | None:
    """The public page with clinic_config.json applied (cached until a file changes)."""
    path = settings.frontend_dir / "clinic-website-pro.html"
    if not path.is_file():
        return None
    cfg = get_clinic_config()
    key = (path.stat().st_mtime_ns, repr(sorted(cfg.items())))
    if _site_cache["key"] != key:
        _site_cache.update(key=key, html=siteconfig.apply_config(path.read_text(encoding="utf-8"), cfg))
    return _site_cache["html"]


def _csv_response(text: str, filename: str) -> Response:
    return Response(
        content=text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )


# ------------------------------------------------------------------ website + static files
@app.get("/", include_in_schema=False)
def home():
    page = render_site()
    if page is None:
        return {"message": "Clinic backend is running successfully!"}
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


@app.get("/admin", include_in_schema=False)
def admin_page():
    path = settings.frontend_dir / "admin.html"
    if not path.is_file():
        raise HTTPException(404, "admin.html was not found next to the website file.")
    return FileResponse(
        path,
        media_type="text/html",
        headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    path = settings.frontend_dir / "assets" / "favicon.ico"
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/x-icon")


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse("User-agent: *\nDisallow: /admin\nDisallow: /appointments\nAllow: /\n")


_assets_dir = settings.frontend_dir / "assets"
if _assets_dir.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


# ------------------------------------------------------------------ health
@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/db-health")
def database_health():
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {"database": "connected"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


# ------------------------------------------------------------------ public: booking
@app.get("/appointments/slots")
def appointment_slots(day: date = Query(..., alias="date"), db: Session = Depends(get_db)):
    """Free/booked 30-minute slots for one day (what the booking form shows)."""
    return services.slots_for_date(db, day, settings=settings, closed_dates=get_clinic_config()["closed_dates"])


@app.post("/appointments", status_code=201)
def create_appointment(
    appointment: AppointmentCreate,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if booking_limiter.hit(client_ip(request)) > settings.booking_rate_limit_per_hour:
        raise HTTPException(429, "Too many booking attempts. Please try again later or call the clinic.")

    if appointment.website:  # a bot filled the hidden field: pretend it worked, store nothing
        return {"message": "Appointment saved successfully", "appointment_id": 0, "status": "pending"}

    item = services.create_appointment(
        db,
        patient_name=appointment.patient_name,
        email=str(appointment.email),
        phone=appointment.phone,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment.appointment_time,
        service=appointment.service,
        reason=appointment.reason,
        settings=settings,
        closed_dates=get_clinic_config()["closed_dates"],
    )
    data = services.serialize(item)
    messages = notifications.booking_messages(settings, data)
    if messages:
        background.add_task(notifications.dispatch, settings, messages)

    return {
        "message": "Appointment saved successfully",
        "appointment_id": data["appointment_id"],
        "status": data["status"],
        "appointment_date": data["appointment_date"],
        "appointment_time": data["appointment_time"],
        "time_label": data["time_label"],
        "service": data["service"],
    }


# ------------------------------------------------------------------ public: newsletter
@app.post("/newsletter", status_code=201)
def newsletter_signup(payload: NewsletterSignup, request: Request, db: Session = Depends(get_db)):
    if newsletter_limiter.hit(client_ip(request)) > settings.booking_rate_limit_per_hour:
        raise HTTPException(429, "Too many requests. Please try again later.")
    if not payload.website:
        services.subscribe(db, str(payload.email))
    return {"message": "Thanks for subscribing."}  # same answer whether new or existing


# ------------------------------------------------------------------ admin
@app.post("/admin/login")
def admin_login(payload: LoginRequest, request: Request):
    if not settings.admin_enabled:
        raise HTTPException(503, "Admin access is not configured. Set ADMIN_PASSWORD in the .env file.")
    ip = client_ip(request)
    if login_limiter.count(ip) >= settings.login_max_failures:
        raise HTTPException(429, "Too many failed attempts. Please wait 15 minutes and try again.")
    if not security.passwords_match(payload.password, settings.admin_password):
        login_limiter.hit(ip)
        raise HTTPException(401, "Incorrect password.")
    login_limiter.reset(ip)
    ttl = settings.token_ttl_minutes * 60
    return {"token": security.sign_token(settings.secret_key, ttl), "expires_in": ttl}


@app.get("/admin/stats", dependencies=[Depends(require_admin)])
def admin_stats(db: Session = Depends(get_db)):
    page = render_site() or ""
    return {
        **services.stats(db),
        "email_enabled": settings.email_enabled,
        "unfilled_placeholders": siteconfig.unfilled_keys(page),
    }


@app.get("/appointments", dependencies=[Depends(require_admin)])
def list_appointments(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    order: str = Query(default="newest", pattern="^(newest|date)$"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total, rows = services.list_appointments(
        db, status=status, date_from=date_from, date_to=date_to, q=q, order=order, limit=limit, offset=offset
    )
    return {"total": total, "items": [services.serialize(r) for r in rows]}


@app.get("/admin/appointments.csv", dependencies=[Depends(require_admin)])
def export_appointments(
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
):
    _, rows = services.list_appointments(
        db, status=status, date_from=date_from, date_to=date_to, q=q, order="date", limit=1000
    )
    return _csv_response(services.appointments_csv(rows), "appointments.csv")


@app.patch("/appointments/{appointment_id}/status", dependencies=[Depends(require_admin)])
def update_appointment_status(
    appointment_id: int,
    status: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    item, changed = services.update_status(db, appointment_id, status)
    if changed:
        messages = notifications.status_messages(settings, services.serialize(item))
        if messages:
            background.add_task(notifications.dispatch, settings, messages)
    return {
        "message": "Appointment status updated successfully",
        "appointment_id": item.id,
        "status": item.status,
    }


@app.delete("/appointments/{appointment_id}", dependencies=[Depends(require_admin)])
def delete_appointment(appointment_id: int, db: Session = Depends(get_db)):
    services.delete_appointment(db, appointment_id)
    return {"message": "Appointment deleted successfully", "appointment_id": appointment_id}


@app.get("/admin/subscribers", dependencies=[Depends(require_admin)])
def list_subscribers(db: Session = Depends(get_db)):
    rows = services.list_subscribers(db)
    return {"total": len(rows), "items": rows}


@app.get("/admin/subscribers.csv", dependencies=[Depends(require_admin)])
def export_subscribers(db: Session = Depends(get_db)):
    return _csv_response(services.subscribers_csv(services.list_subscribers(db)), "subscribers.csv")
