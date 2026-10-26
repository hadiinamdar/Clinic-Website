"""Import this first in every test module: points the app at a throw-away database."""
import os
import tempfile

_dir = tempfile.mkdtemp(prefix="clinic-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_dir, "test.db").replace("\\", "/")
os.environ["ADMIN_PASSWORD"] = "test-password-123"
os.environ["APP_ENV"] = "development"
os.environ["SMTP_HOST"] = ""
os.environ["BOOKING_RATE_LIMIT_PER_HOUR"] = "1000"
