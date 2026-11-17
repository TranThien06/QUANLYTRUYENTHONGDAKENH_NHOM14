import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Annotated
from fastapi import APIRouter, Depends, Request
from pydantic import AfterValidator, EmailStr, Field, field_validator
from app.common import Input, now, ok
from app.config import settings
from app.db import transaction
from app.dependencies import current_user
from app.errors import check
from app.events import audit
from app.security import token, hash_token, hash_password, verify_password, encrypt, encryption_key

router = APIRouter(tags=["Tài khoản"])


def validate_password(value):
    if not 8 <= len(value) or len(value.encode()) > 72:
        raise ValueError("Mật khẩu tối thiểu 8 ký tự, tối đa 72 byte UTF-8")
    return value


Password = Annotated[str, AfterValidator(validate_password)]


class EmailInput(Input):
    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalize(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class VerificationInput(EmailInput):
    code: str = Field(pattern=r"^[0-9]{6}$")


class RegisterInput(EmailInput):
    password: Password
    full_name: str = Field(min_length=1, max_length=150)


class LoginInput(EmailInput):
    password: str = Field(max_length=72)


class TokenInput(Input):
    token: str = Field(min_length=1, max_length=100)


class ResetInput(TokenInput):
    password: Password


class ProfileInput(Input):
    full_name: str = Field(min_length=1, max_length=150)
    avatar_url: str | None = Field(None, max_length=500, pattern=r"^https?://")


class ChangePasswordInput(Input):
    old_password: str = Field(max_length=72)
    password: Password


class ConfirmInput(Input):
    confirm: bool


def queue_mail(db, recipient, subject, content):
    db.insert("email_outbox", {"recipient": recipient, "subject": subject, "body_enc": encrypt(content)})


def action_token(db, user, purpose, hours):
    raw = token()
    db.execute(
        "UPDATE auth_action_tokens SET consumed_at=UTC_TIMESTAMP() WHERE user_id=%s AND purpose=%s AND consumed_at IS NULL",
        (user["user_id"], purpose),
    )
    db.insert(
        "auth_action_tokens",
        {
            "user_id": user["user_id"],
            "purpose": purpose,
            "token_hash": hash_token(raw),
            "expires_at": now() + timedelta(hours=hours),
        },
    )
    route = "verify-email" if purpose == "verify_email" else "reset-password"
    queue_mail(db, user["email"], purpose, f"{settings.frontend_url}/{route}?token={raw}")


def verification_hash(user_id, code):
    return hmac.new(encryption_key(), f"verify:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def send_verification_code(db, user):
    previous = db.one("SELECT * FROM email_verification_codes WHERE user_id=%s", (user["user_id"],))
    if previous and previous["sent_at"] > now() - timedelta(seconds=60):
        return
    code = f"{secrets.randbelow(1000000):06d}"
    db.execute(
        """INSERT INTO email_verification_codes(user_id,code_hash,expires_at,sent_at)
        VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE code_hash=VALUES(code_hash),
        expires_at=VALUES(expires_at),sent_at=VALUES(sent_at),failed_attempts=0,consumed_at=NULL""",
        (user["user_id"], verification_hash(user["user_id"], code), now() + timedelta(minutes=10), now()),
    )
    db.execute(
        "UPDATE auth_action_tokens SET consumed_at=UTC_TIMESTAMP() WHERE user_id=%s AND purpose='verify_email' AND consumed_at IS NULL",
        (user["user_id"],),
    )
    queue_mail(db, user["email"], "verify_email_code", code)


@router.post("/auth/register", status_code=201)
def register(data: RegisterInput):
    hashed = hash_password(data.password)
    with transaction() as db:
        check(
            not db.one("SELECT 1 FROM users WHERE email=%s", (str(data.email),)),
            409,
            "EMAIL_EXISTS",
            "Email đã đăng ký",
        )
        user_id = db.insert(
            "users", {"email": str(data.email), "password_hash": hashed, "full_name": data.full_name.strip()}
        )
        send_verification_code(db, {"user_id": user_id, "email": str(data.email)})
    return ok({"message": "Đăng ký thành công. Nhập mã 6 chữ số đã gửi qua email để xác minh."})


@router.post("/auth/resend-verification")
def resend(data: EmailInput):
    with transaction() as db:
        user = db.one("SELECT * FROM users WHERE email=%s FOR UPDATE", (str(data.email),))
        if user and user["status"] == "pending":
            send_verification_code(db, user)
    return ok({"message": "Nếu tài khoản phù hợp, email sẽ được gửi."})


def consume(data, purpose):
    hashed = hash_password(data.password) if purpose == "password_reset" else None
    with transaction() as db:
        item = db.one(
            "SELECT * FROM auth_action_tokens WHERE token_hash=%s AND purpose=%s AND consumed_at IS NULL AND expires_at>UTC_TIMESTAMP() FOR UPDATE",
            (hash_token(data.token), purpose),
        )
        check(item, 422, "INVALID_TOKEN", "Liên kết không hợp lệ hoặc hết hạn")
        user = db.one("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (item["user_id"],))
        check(
            user and user["status"] not in ("disabled", "locked"),
            403,
            "ACCOUNT_UNAVAILABLE",
            "Tài khoản không khả dụng",
        )
        if purpose == "verify_email":
            db.execute(
                "UPDATE users SET status='active',email_verified_at=UTC_TIMESTAMP() WHERE user_id=%s",
                (user["user_id"],),
            )
        else:
            db.execute(
                "UPDATE users SET password_hash=%s,failed_login_attempts=0,locked_until=NULL WHERE user_id=%s",
                (hashed, user["user_id"]),
            )
            db.execute(
                "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s", (user["user_id"],)
            )
        db.execute(
            "UPDATE auth_action_tokens SET consumed_at=UTC_TIMESTAMP() WHERE action_token_id=%s",
            (item["action_token_id"],),
        )
    return ok({"message": "Thành công"})


@router.post("/auth/verify-email")
def verify_email(data: VerificationInput | TokenInput):
    if isinstance(data, TokenInput):
        return consume(data, "verify_email")  # Support emails already sent before the code rollout.
    valid = False
    with transaction() as db:
        user = db.one("SELECT * FROM users WHERE email=%s FOR UPDATE", (str(data.email),))
        if user and user["status"] == "pending":
            item = db.one(
                "SELECT * FROM email_verification_codes WHERE user_id=%s FOR UPDATE", (user["user_id"],)
            )
            if (
                item
                and not item["consumed_at"]
                and item["expires_at"] > now()
                and item["failed_attempts"] < 5
            ):
                valid = hmac.compare_digest(item["code_hash"], verification_hash(user["user_id"], data.code))
                if valid:
                    db.execute(
                        "UPDATE users SET status='active',email_verified_at=UTC_TIMESTAMP() WHERE user_id=%s",
                        (user["user_id"],),
                    )
                    db.execute(
                        "UPDATE email_verification_codes SET consumed_at=UTC_TIMESTAMP() WHERE user_id=%s",
                        (user["user_id"],),
                    )
                else:
                    db.execute(
                        "UPDATE email_verification_codes SET failed_attempts=failed_attempts+1 WHERE user_id=%s",
                        (user["user_id"],),
                    )
    # Commit failed-attempt counters before returning an error.
    check(
        valid,
        422,
        "INVALID_CODE",
        "Mã không đúng, đã hết hạn hoặc nhập sai quá 5 lần. Vui lòng yêu cầu mã mới.",
    )
    return ok({"message": "Email đã được xác minh. Bạn có thể đăng nhập."})


@router.post("/auth/forgot-password")
def forgot(data: EmailInput):
    with transaction() as db:
        user = db.one("SELECT * FROM users WHERE email=%s AND status='active' FOR UPDATE", (str(data.email),))
        if user:
            action_token(db, user, "password_reset", 0.5)
    return ok({"message": "Nếu tài khoản phù hợp, email sẽ được gửi."})


@router.post("/auth/reset-password")
def reset(data: ResetInput):
    return consume(data, "password_reset")


@router.post("/auth/login")
def login(data: LoginInput):
    result = None
    with transaction() as db:
        user = db.one("SELECT * FROM users WHERE email=%s FOR UPDATE", (str(data.email),))
        available = (
            user
            and user["status"] == "active"
            and (not user["locked_until"] or user["locked_until"] <= now())
        )
        if available:
            if verify_password(data.password, user["password_hash"]):
                raw = token()
                db.execute(
                    "UPDATE users SET failed_login_attempts=0,locked_until=NULL,last_login_at=UTC_TIMESTAMP() WHERE user_id=%s",
                    (user["user_id"],),
                )
                db.insert(
                    "auth_sessions",
                    {
                        "user_id": user["user_id"],
                        "token_hash": hash_token(raw),
                        "expires_at": now() + timedelta(days=7),
                    },
                )
                result = {
                    "message": "Đăng nhập thành công",
                    "access_token": raw,
                    "token_type": "Bearer",
                    "expires_in": 604800,
                    "user": {k: user[k] for k in ("user_id", "email", "full_name")},
                }
            else:
                db.execute(
                    "UPDATE users SET failed_login_attempts=failed_login_attempts+1,locked_until=IF(failed_login_attempts>=5,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 15 MINUTE),NULL) WHERE user_id=%s",
                    (user["user_id"],),
                )
    # Commit bộ đếm sai trước khi trả lỗi, không rollback nó.
    check(result, 401, "INVALID_CREDENTIALS", "Thông tin đăng nhập không hợp lệ hoặc tài khoản chưa khả dụng")
    return ok(result)


@router.post("/auth/logout")
def logout(user=Depends(current_user)):
    with transaction() as db:
        db.execute(
            "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE session_id=%s", (user["session_id"],)
        )
    return ok({"message": "Đã đăng xuất"})


@router.get("/me")
def me(user=Depends(current_user)):
    with transaction() as db:
        return ok(
            db.one(
                "SELECT user_id,email,full_name,avatar_url,status,email_verified_at,created_at FROM users WHERE user_id=%s",
                (user["user_id"],),
            )
        )


@router.patch("/me")
def profile(data: ProfileInput, user=Depends(current_user)):
    with transaction() as db:
        db.execute(
            "UPDATE users SET full_name=%s,avatar_url=%s WHERE user_id=%s",
            (data.full_name, data.avatar_url, user["user_id"]),
        )
    return me(user)


@router.post("/me/change-password")
def change_password(data: ChangePasswordInput, request: Request, user=Depends(current_user)):
    with transaction() as db:
        row = db.one("SELECT * FROM users WHERE user_id=%s FOR UPDATE", (user["user_id"],))
        check(
            verify_password(data.old_password, row["password_hash"]),
            422,
            "WRONG_PASSWORD",
            "Mật khẩu cũ không đúng",
        )
        db.execute(
            "UPDATE users SET password_hash=%s WHERE user_id=%s",
            (hash_password(data.password), user["user_id"]),
        )
        db.execute(
            "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s AND session_id<>%s",
            (user["user_id"], user["session_id"]),
        )
        audit(db, request, "user.password_change", "user", user["user_id"])
    return ok({"message": "Đã đổi mật khẩu"})


@router.post("/me/deletion-requests", status_code=202)
def deletion(data: ConfirmInput, request: Request, user=Depends(current_user)):
    check(data.confirm, 422, "CONFIRM_REQUIRED", "Cần xác nhận")
    with transaction() as db:
        check(
            not db.one(
                "SELECT 1 FROM workspaces WHERE owner_id=%s AND deleted_at IS NULL", (user["user_id"],)
            ),
            409,
            "TRANSFER_OWNERSHIP",
            "Chuyển quyền sở hữu workspace trước",
        )
        request_id = db.insert("account_deletion_requests", {"user_id": user["user_id"]})
        db.execute("UPDATE users SET status='disabled' WHERE user_id=%s", (user["user_id"],))
        db.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE user_id=%s", (user["user_id"],))
        audit(db, request, "user.deletion_requested", "user", user["user_id"])
    return ok(
        {
            "request_id": request_id,
            "message": "Tài khoản đã vô hiệu hóa; yêu cầu xóa dữ liệu đã được ghi nhận.",
        }
    )
