# Care Scan & Diagnostic Centre – website + backend

One FastAPI app serves **the public website**, **the booking API** and **a staff dashboard**.

```
ClinicWebsite/
  clinic-website-pro.html        public website (logo, booking form, chatbot ...)
  admin.html                     staff dashboard  ->  /admin
  assets/                        logo + favicons (cut from your letterhead)
  clinic-website-backend/
    main.py                      API routes          services.py   booking logic
    scheduling.py                opening hours       security.py   login tokens, rate limits
    models.py / database.py      SQLite + auto-migration
    notifications.py             optional e-mail     siteconfig.py fills doctor details
    clinic_config.json           <- YOU EDIT THIS (doctor details, holidays)
    .env                         <- YOU CREATE THIS (admin password, e-mail)
    tests/                       python -m unittest ...
```

## 1. First run (Windows)

1. In `clinic-website-backend`, copy `.env.example` to `.env` and set **`ADMIN_PASSWORD`** (long and unique).
2. Double-click **`run_server.bat`** (creates/uses a virtual environment, installs requirements, starts the server).
   Manual alternative: `pip install -r requirements.txt` then `python -m uvicorn main:app --port 8000`.
3. Open **http://127.0.0.1:8000** (website) and **http://127.0.0.1:8000/admin** (staff).

Your existing `clinic.db` is upgraded automatically on start (new columns + a rule that stops two
active bookings sharing one time slot). Existing appointments are kept. **Back up the file first anyway.**

## 2. Fill in the doctor's details

Edit `clinic_config.json` (no restart needed; refresh the page). Empty values keep the `[placeholder]` text.
`doctor_name` should include the title, e.g. `"Dr. Anita Rao"`.

| Key | Where it appears |
|---|---|
| doctor_name, specialty, years_experience, qualifications | title, hero, About, chatbot, search snippet |
| postgraduate_qualification, registration_number | Credentials card |
| memberships, fellowships, awards_and_research | Credentials cards |
| closed_dates | `["2026-11-09", ...]` – days the clinic is closed; slots disappear |
| hide_placeholder_notes | `true` removes the grey "replace this text" notes before launch |
| show_sample_reviews | `false` removes the **sample** patient reviews (see "Before you go live") |

The staff dashboard shows a yellow banner listing any placeholder still visible on the site.

## 3. What staff can do at /admin

Sign in, see today's/pending/upcoming counts, search and filter appointments, **Confirm / Cancel / Mark done / Reopen / Delete**,
download CSV (opens in Excel), and view/download newsletter subscribers. With e-mail configured, patients get an
acknowledgement and a confirmed/cancelled message automatically, and the clinic is alerted to each new request.

## 4. Booking rules (edit `scheduling.py` / `.env`)

* 30-minute slots: Mon–Sat 9:30–2:00 and 5:00–8:30 pm; Sunday 10:30–12:30 (same as your ultrasound hours).
* One active appointment per time slot for the whole clinic (existing design). Cancelled ones free the slot.
* Min notice 30 min, up to 60 days ahead, max 3 upcoming appointments per phone number.
* The server re-checks everything, so the website cannot be tricked into booking closed hours.

## 5. Tests

```
python -m unittest discover -s tests -t . -v          # logic + database tests, nothing extra to install
pip install -r requirements-dev.txt                    # then the same command also runs tests/test_api.py (HTTP-level)
```

## 6. Going live

* Put it behind HTTPS (Caddy / nginx / your host). Set `APP_ENV=production`, `CORS_ORIGINS=https://yourdomain`,
  and `TRUST_PROXY=true` **only** if exactly one proxy is in front.
* Run: `uvicorn main:app --host 127.0.0.1 --port 8000` as a service (NSSM on Windows, systemd on Linux).
* Back up `clinic.db` daily. It contains patient names, phone numbers and e-mails: keep the server and `.env` private.
* Never expose `clinic-website-backend/` as a web folder; the app only serves the website, `/admin` and `/assets`.

## API summary

| Method & path | Who | Purpose |
|---|---|---|
| GET `/appointments/slots?date=YYYY-MM-DD` | public | free/booked slots |
| POST `/appointments` | public | request an appointment (409 if slot taken) |
| POST `/newsletter` | public | subscribe |
| POST `/admin/login` | staff | password -> short-lived token (`Authorization: Bearer ...`) |
| GET `/appointments`, GET `/admin/stats`, GET `/admin/appointments.csv` | staff | list / counts / export |
| PATCH `/appointments/{id}/status?status=confirmed` | staff | pending, confirmed, cancelled, completed |
| DELETE `/appointments/{id}` | staff | delete |
| GET `/admin/subscribers`, `/admin/subscribers.csv` | staff | newsletter list |
| GET `/health`, `/db-health` | public | monitoring |

Interactive docs at `/docs` (development only).
