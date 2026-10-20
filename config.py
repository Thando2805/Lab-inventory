import os
import secrets
from dotenv import load_dotenv

load_dotenv()


def _env_flag(name, default=False):
    value = os.environ.get(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


class Config:
    DEBUG = _env_flag("FLASK_DEBUG", False)
    ENVIRONMENT = os.environ.get("APP_ENV", "development").strip().lower()
    SECRET_KEY = os.environ.get("SECRET_KEY")

    _db_url = os.environ.get("DATABASE_URL", "sqlite:///lab_inventory.db")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql+psycopg://", 1)
    elif _db_url.startswith("postgresql://"):
        _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE", ENVIRONMENT == "production")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"

    WTF_CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
    ADMIN_FULLNAME = os.environ.get("ADMIN_FULLNAME", "System Administrator")

    if ENVIRONMENT == "production":
        if DEBUG:
            raise RuntimeError("FLASK_DEBUG must be disabled in production.")
        if not SECRET_KEY or len(SECRET_KEY) < 32:
            raise RuntimeError("Production requires SECRET_KEY with at least 32 characters.")
        if ADMIN_USERNAME == "admin":
            raise RuntimeError("Production requires a non-default ADMIN_USERNAME.")
        if not ADMIN_PASSWORD or len(ADMIN_PASSWORD) < 16 or ADMIN_PASSWORD == "ChangeMeNow123!":
            raise RuntimeError("Production requires an ADMIN_PASSWORD of at least 16 characters.")
    elif not SECRET_KEY:
        SECRET_KEY = secrets.token_hex(32)
        # Local convenience only; production always requires an explicit key.
        os.environ["SECRET_KEY"] = SECRET_KEY

    if not ADMIN_PASSWORD:
        ADMIN_PASSWORD = "ChangeMeNow123!"
