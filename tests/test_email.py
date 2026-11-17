from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from app.config import settings, validate_config
from app.jobs import mail
from app.security import encrypt


@pytest.mark.parametrize("port", ["587", "465"])
def test_verification_email_uses_tls_and_one_use_code(monkeypatch, port):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", port)
    monkeypatch.setenv("SMTP_USER", "sender@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("MAIL_FROM", "sender@example.com")
    monkeypatch.setattr(settings, "mail_mode", "smtp")
    link = "012345"
    db = MagicMock()
    db.one.return_value = {
        "email_id": 1,
        "recipient": "recipient@example.com",
        "subject": "verify_email_code",
        "body_enc": encrypt(link),
        "attempt_count": 0,
    }
    db.execute.return_value = 1

    @contextmanager
    def transaction():
        yield db

    monkeypatch.setattr(mail, "transaction", transaction)
    smtp = MagicMock()
    factory = MagicMock()
    factory.return_value.__enter__.return_value = smtp
    other = MagicMock()
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL" if port == "465" else "SMTP", factory)
    monkeypatch.setattr(mail.smtplib, "SMTP" if port == "465" else "SMTP_SSL", other)
    assert mail.send_one_email()
    factory.assert_called_once_with("smtp.gmail.com", int(port), timeout=30)
    other.assert_not_called()
    assert smtp.starttls.call_count == (1 if port == "587" else 0)
    smtp.login.assert_called_once_with("sender@example.com", "test-app-password")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "recipient@example.com"
    assert link in message.get_content()
    assert "10" in message.get_content()
    assert "Mã xác minh email" in message["Subject"]
    assert any("status='sent'" in call.args[0] for call in db.execute.call_args_list)


def test_smtp_config_names_missing_fields_without_exposing_secrets(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setattr(settings, "mail_mode", "smtp")
    for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(RuntimeError, match="SMTP_PASSWORD"):
        validate_config()


def test_verification_page_is_public():
    import asyncio
    import httpx
    from app.main import create_app

    async def check():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app()), base_url="http://test"
        ) as client:
            response = await client.get("/verify-email?token=example")
            assert response.status_code == 200
            assert 'id="verification-dialog"' in response.text
            assert "/assets/verification.js" in response.text
            assert (await client.get("/assets/verification.js")).status_code == 200

    asyncio.run(check())
