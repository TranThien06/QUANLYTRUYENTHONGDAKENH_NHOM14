from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from app.common import now
from app.errors import ApiError
from app.modules import auth


@pytest.fixture
def verification_db(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    user = {"user_id": 42, "email": "person@example.com", "status": "pending"}
    item = {
        "code_hash": auth.verification_hash(42, "012345"),
        "expires_at": now() + timedelta(minutes=10),
        "failed_attempts": 0,
        "consumed_at": None,
    }
    db = MagicMock()
    db.committed = False

    def one(sql, args):
        return user if "FROM users" in sql else item

    def execute(sql, args):
        if "failed_attempts=failed_attempts+1" in sql:
            item["failed_attempts"] += 1
        if "SET consumed_at" in sql:
            item["consumed_at"] = now()
        if "SET status='active'" in sql:
            user["status"] = "active"

    db.one.side_effect = one
    db.execute.side_effect = execute

    @contextmanager
    def transaction():
        yield db
        db.committed = True

    monkeypatch.setattr(auth, "transaction", transaction)
    return db, user, item


def test_code_activates_account_and_cannot_be_replayed(verification_db):
    db, user, item = verification_db
    data = auth.VerificationInput(email="person@example.com", code="012345")
    auth.verify_email(data)
    assert user["status"] == "active" and item["consumed_at"] and db.committed
    with pytest.raises(ApiError):
        auth.verify_email(data)


def test_five_wrong_attempts_persist_and_block_correct_code(verification_db):
    db, user, item = verification_db
    for _ in range(5):
        with pytest.raises(ApiError):
            auth.verify_email(auth.VerificationInput(email=user["email"], code="999999"))
        assert db.committed
    assert item["failed_attempts"] == 5
    with pytest.raises(ApiError):
        auth.verify_email(auth.VerificationInput(email=user["email"], code="012345"))
    assert user["status"] == "pending"


def test_expired_code_is_rejected(verification_db):
    db, user, item = verification_db
    item["expires_at"] = now() - timedelta(seconds=1)
    with pytest.raises(ApiError):
        auth.verify_email(auth.VerificationInput(email=user["email"], code="012345"))
    assert user["status"] == "pending"


def test_resend_cooldown_and_new_code_storage(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    monkeypatch.setattr(auth.secrets, "randbelow", lambda _: 12345)
    db = MagicMock()
    user = {"user_id": 42, "email": "person@example.com"}
    db.one.return_value = {"sent_at": now()}
    auth.send_verification_code(db, user)
    db.insert.assert_not_called()
    db.one.return_value = {"sent_at": now() - timedelta(seconds=61)}
    auth.send_verification_code(db, user)
    statement, args = db.execute.call_args_list[0].args
    assert "ON DUPLICATE KEY UPDATE" in statement and "failed_attempts=0" in statement
    assert args[1] == auth.verification_hash(42, "012345")
    assert auth.verification_hash(43, "012345") != args[1]
    assert args[2] > now() + timedelta(minutes=9)
    payload = db.insert.call_args.args[1]
    assert payload["subject"] == "verify_email_code"
    from app.security import decrypt

    assert decrypt(payload["body_enc"]) == "012345"
