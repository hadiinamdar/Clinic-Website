#!/usr/bin/env sh
# Starts the website + API on http://127.0.0.1:8000  (admin: /admin)
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f .env ] || echo "NOTE: no .env yet - copy .env.example to .env and set ADMIN_PASSWORD."
exec .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 8000
