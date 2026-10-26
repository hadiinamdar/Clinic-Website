@echo off
REM Starts the website + API on http://127.0.0.1:8000  (admin: /admin)
cd /d "%~dp0"
set PY=
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if "%PY%"=="" if exist "venv\Scripts\python.exe" set PY=venv\Scripts\python.exe
if "%PY%"=="" (
  echo Creating virtual environment...
  python -m venv .venv || goto :err
  set PY=.venv\Scripts\python.exe
)
%PY% -m pip install -q -r requirements.txt || goto :err
if not exist ".env" echo NOTE: no .env file yet - copy .env.example to .env and set ADMIN_PASSWORD.
%PY% -m uvicorn main:app --host 127.0.0.1 --port 8000
goto :eof
:err
echo Setup failed.
pause
