import os

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from config import Config


class ProdConfig(Config):
    TESTING = False

    # Cookies should only be sent over HTTPS (TLS terminated at Nginx).
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # When behind an HTTPS reverse proxy, Flask should generate https:// URLs.
    PREFERRED_URL_SCHEME = "https"

    # Use MySQL in production (run.py stays on SQLite via default Config).
    # Example: mysql+pymysql://user:pass@127.0.0.1:3306/estimate_tax?charset=utf8mb4
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")


def _require_env(name: str) -> str:
    v = (os.environ.get(name) or "").strip()
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


def build_app():
    # Fail fast on missing secrets in production.
    _require_env("SECRET_KEY")
    _require_env("ENCRYPTION_KEY")
    _require_env("STRIPE_SECRET_KEY")
    _require_env("STRIPE_SEAT_PRICE_ID")
    _require_env("STRIPE_WEBHOOK_SECRET")
    _require_env("DATABASE_URL")

    app = create_app(ProdConfig)

    # Trust Nginx forwarded headers so Flask sees the real scheme/client IP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    return app


# Export WSGI callable for: waitress-serve --call serve:build_app
app = build_app()

