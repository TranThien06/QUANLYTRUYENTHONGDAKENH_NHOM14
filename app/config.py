"""Đọc .env một lần. Không thay khóa mã hóa khi chuyển từ Node.js."""

import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(os.environ.get("ENV_FILE", ROOT / ".env"), override=False)


class Settings:
    env = os.getenv("APP_ENV", os.getenv("NODE_ENV", "development"))
    port = int(os.getenv("PORT", "3000"))
    app_url = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
    frontend_url = os.getenv("FRONTEND_URL", app_url).rstrip("/")
    storage = Path(os.getenv("STORAGE_DIR", "storage")).resolve()
    social_mode = os.getenv("SOCIAL_MODE", "mock")
    mail_mode = os.getenv("MAIL_MODE", "file")
    max_upload_bytes = int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024


settings = Settings()


def validate_config():
    from app.security import encryption_key

    encryption_key()
    if settings.mail_mode not in ("file", "smtp"):
        raise RuntimeError("MAIL_MODE phải là file hoặc smtp")
    if settings.mail_mode == "smtp":
        required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM")
        missing = [key for key in required if not os.getenv(key, "").strip()]
        if missing:
            raise RuntimeError("Thiếu cấu hình gửi email: " + ", ".join(missing))
        if os.getenv("SMTP_PORT", "587") not in ("465", "587"):
            raise RuntimeError("SMTP_PORT phải là 465 (SSL) hoặc 587 (STARTTLS)")
    if settings.env == "production":
        if settings.social_mode != "live" or settings.mail_mode != "smtp":
            raise RuntimeError("Production cần SOCIAL_MODE=live và MAIL_MODE=smtp")
        if not settings.app_url.startswith("https://"):
            raise RuntimeError("Production cần APP_URL HTTPS")
