import json
from datetime import timedelta
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import Field
from app.common import Input, Id, Pagination, now, ok
from app.config import settings
from app.db import transaction
from app.dependencies import current_user, membership, workspace
from app.errors import ApiError, check
from app.events import audit, change_status, notify
from app.security import token, hash_token, encrypt, decrypt
from app import social

router = APIRouter(tags=["Kênh và OAuth"])
Platform = Literal["facebook", "instagram", "tiktok"]
ConnectionStatus = Literal["connected", "expired", "revoked", "error", "disconnected"]
TOKEN_STATUS = {"TOKEN_EXPIRED": "expired", "TOKEN_REVOKED": "revoked"}
EFFECTIVE_STATUS = """CASE
    WHEN a.status<>'connected' THEN a.status
    WHEN t.social_account_id IS NULL THEN 'expired'
    WHEN t.expires_at<=UTC_TIMESTAMP() THEN 'expired'
    ELSE 'connected'
END"""


class SelectionInput(Input):
    connection_token: str = Field(min_length=1, max_length=100)
    external_account_ids: list[str] = Field(min_length=1, max_length=100)


def account(db, workspace_id, account_id, lock=False):
    row = db.one(
        "SELECT a.*,(SELECT p.code FROM platforms p WHERE p.platform_id=a.platform_id) AS code "
        "FROM social_accounts a WHERE a.workspace_id=%s AND a.social_account_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (workspace_id, account_id),
    )
    check(row, 404, "CHANNEL_NOT_FOUND", "Không tìm thấy kênh")
    return row


def credentials(db, account_id):
    row = db.one("SELECT * FROM social_account_tokens WHERE social_account_id=%s", (account_id,))
    check(row, 409, "TOKEN_MISSING", "Cần kết nối lại kênh")
    return {
        "access_token": decrypt(row["access_token_enc"]),
        "refresh_token": decrypt(row["refresh_token_enc"]),
        "expires_at": row.get("expires_at"),
    }


@router.get("/platforms")
def platforms(user=Depends(current_user)):
    with transaction() as db:
        return ok(db.all("SELECT * FROM platforms WHERE is_active=1"))


@router.get("/platforms/capabilities")
def all_capabilities(user=Depends(current_user)):
    return ok([social.capabilities(platform) for platform in ("facebook", "instagram", "tiktok")])


@router.get("/platforms/{platform}/capabilities")
def capabilities(platform: Platform, user=Depends(current_user)):
    return ok(social.capabilities(platform))


@router.get("/workspaces/{workspace_id}/social-accounts", dependencies=[Depends(workspace())])
def list_accounts(
    workspace_id: Id,
    paging: Pagination = Depends(),
    platform: Platform | None = None,
    status: ConnectionStatus | None = None,
    q: Annotated[str, Query(max_length=255)] = "",
    include_pagination: bool = False,
):
    clauses, params = [], [workspace_id]
    if platform:
        clauses.append("p.code=%s")
        params.append(platform)
    if status:
        clauses.append(f"({EFFECTIVE_STATUS})=%s")
        params.append(status)
    if q.strip():
        clauses.append(
            "LOCATE(LOWER(%s),LOWER(CONCAT_WS(' ',a.account_name,a.external_account_id,p.code)))>0"
        )
        params.append(q.strip())
    filters = "".join(" AND " + clause for clause in clauses)
    limit, offset = paging.sql
    with transaction() as db:
        rows = db.all(
            f"""SELECT a.*,p.code platform,t.expires_at token_expires_at,t.scopes,
            {EFFECTIVE_STATUS} connection_status
            FROM social_accounts a JOIN platforms p ON p.platform_id=a.platform_id
            LEFT JOIN social_account_tokens t ON t.social_account_id=a.social_account_id
            WHERE a.workspace_id=%s{filters} ORDER BY a.social_account_id LIMIT %s OFFSET %s""",
            (*params, limit + int(include_pagination), offset),
        )
    if include_pagination:
        return ok({"rows": rows[:limit], "has_next": len(rows) > limit})
    return ok(rows)


ACCOUNT_ROUTE = "/workspaces/{workspace_id}/social-accounts/{account_id}"


@router.get(ACCOUNT_ROUTE, dependencies=[Depends(workspace())])
def account_detail(workspace_id: Id, account_id: Id):
    with transaction() as db:
        row = db.one(
            f"""SELECT a.*,p.code platform,t.expires_at token_expires_at,{EFFECTIVE_STATUS} connection_status
                FROM social_accounts a JOIN platforms p ON p.platform_id=a.platform_id
                LEFT JOIN social_account_tokens t ON t.social_account_id=a.social_account_id
                WHERE a.workspace_id=%s AND a.social_account_id=%s""",
            (workspace_id, account_id),
        )
        check(row, 404, "CHANNEL_NOT_FOUND", "Không tìm thấy kênh")
        row["sync_logs"] = db.all(
            """SELECT kind,status,records_updated,error_code,started_at,finished_at
            FROM channel_sync_logs WHERE social_account_id=%s ORDER BY sync_id DESC LIMIT 10""",
            (account_id,),
        )
    return ok(row)


@router.get(ACCOUNT_ROUTE + "/permissions", dependencies=[Depends(workspace())])
def account_permissions(workspace_id: Id, account_id: Id):
    with transaction() as db:
        account(db, workspace_id, account_id)
        row = db.one("SELECT scopes FROM social_account_tokens WHERE social_account_id=%s", (account_id,))
    scopes = row["scopes"] if row else None
    return ok({"known": scopes is not None, "scopes": scopes.split(",") if scopes else []})


@router.get(ACCOUNT_ROUTE + "/activity-logs", dependencies=[Depends(workspace())])
def account_activity(workspace_id: Id, account_id: Id, paging: Pagination = Depends()):
    with transaction() as db:
        account(db, workspace_id, account_id)
        return ok(
            db.all(
                """SELECT action,user_id,created_at FROM audit_logs
            WHERE workspace_id=%s AND entity_type='social_account' AND entity_id=%s
            ORDER BY audit_id DESC LIMIT %s OFFSET %s""",
                (workspace_id, account_id, *paging.sql),
            )
        )


@router.post(ACCOUNT_ROUTE + "/check", dependencies=[Depends(workspace("channel.manage"))])
def check_account(workspace_id: Id, account_id: Id, request: Request):
    with transaction() as db:
        row = account(db, workspace_id, account_id, True)
        check(row["status"] != "disconnected", 409, "CHANNEL_UNAVAILABLE", "Kênh đã ngắt kết nối")
        auth = credentials(db, account_id)
        error_code = None
        try:
            if auth["expires_at"] is not None and auth["expires_at"] <= now():
                raise social.ProviderError("TOKEN_EXPIRED")
            profile = social.channel_profile(row, auth["access_token"])
        except social.ProviderError as error:
            error_code = error.code
            status = TOKEN_STATUS.get(error.code, row["status"] if error.retryable else "error")
            db.execute(
                "UPDATE social_accounts SET status=%s,status_message=%s WHERE social_account_id=%s",
                (status, error.code, account_id),
            )
        else:
            status = "connected"
            db.execute(
                """UPDATE social_accounts SET status='connected',status_message=NULL,
                account_name=COALESCE(%s,account_name),avatar_url=COALESCE(%s,avatar_url)
                WHERE social_account_id=%s""",
                (profile.get("name"), profile.get("avatar_url"), account_id),
            )
        audit(
            db,
            request,
            "channel.check",
            "social_account",
            account_id,
            new={"status": status, "error": error_code},
        )
    return ok({"status": status, "error_code": error_code})


@router.post(ACCOUNT_ROUTE + "/refresh", dependencies=[Depends(workspace("channel.manage"))])
def refresh_account(workspace_id: Id, account_id: Id, request: Request):
    with transaction() as db:
        row = account(db, workspace_id, account_id, True)
        check(
            row["status"] not in ("disconnected", "revoked"),
            409,
            "CHANNEL_UNAVAILABLE",
            "Vui lòng kết nối lại kênh",
        )
        auth = credentials(db, account_id)
        check(
            row["code"] == "tiktok" or settings.social_mode == "mock",
            409,
            "RECONNECT_REQUIRED",
            "Vui lòng cấp quyền lại trên Meta",
        )
        check(
            auth["refresh_token"], 409, "RECONNECT_REQUIRED", "Kênh thiếu token làm mới. Vui lòng kết nối lại"
        )
        fresh = social.refresh_remote(row, auth)
        expires = now() + timedelta(seconds=fresh["expires_in"])
        db.execute(
            """UPDATE social_account_tokens SET access_token_enc=%s,refresh_token_enc=%s,
            expires_at=%s,scopes=COALESCE(%s,scopes),last_refreshed_at=UTC_TIMESTAMP(),refresh_fail_count=0
            WHERE social_account_id=%s""",
            (
                encrypt(fresh["access_token"]),
                encrypt(fresh.get("refresh_token") or auth["refresh_token"]),
                expires,
                fresh.get("scope"),
                account_id,
            ),
        )
        db.execute(
            "UPDATE social_accounts SET status='connected',status_message=NULL WHERE social_account_id=%s",
            (account_id,),
        )
        audit(db, request, "channel.refresh", "social_account", account_id)
    return ok({"status": "connected", "expires_at": expires})


def save_connected_account(db, workspace_id, request, item):
    external_id = item["external_account_id"]
    platform = db.one("SELECT platform_id FROM platforms WHERE code=%s", (item["platform"],))
    linked_id = None
    if item["platform"] == "instagram":
        linked = db.one(
            """SELECT a.social_account_id FROM social_accounts a JOIN platforms p ON p.platform_id=a.platform_id
            WHERE a.workspace_id=%s AND a.external_account_id=%s AND p.code='facebook'
            AND a.account_type='page' AND a.status='connected' FOR UPDATE""",
            (workspace_id, item.get("linked_page_external_id")),
        )
        check(linked or settings.social_mode == "mock", 422, "LINK_PAGE_FIRST", "Kết nối Facebook Page liên kết trước")
        linked_id = linked["social_account_id"] if linked else None
    db.execute(
        """INSERT INTO social_accounts(workspace_id,platform_id,external_account_id,account_name,account_type,avatar_url,linked_account_id,connected_by)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE account_name=VALUES(account_name),avatar_url=VALUES(avatar_url),linked_account_id=VALUES(linked_account_id),status='connected',status_message=NULL,disconnected_at=NULL,connected_by=VALUES(connected_by),connected_at=UTC_TIMESTAMP()""",
        (
            workspace_id,
            platform["platform_id"],
            external_id,
            item["account_name"],
            item["account_type"],
            item.get("avatar_url"),
            linked_id,
            request.state.user["user_id"],
        ),
    )
    saved = db.one(
        "SELECT social_account_id FROM social_accounts WHERE workspace_id=%s AND platform_id=%s AND external_account_id=%s",
        (workspace_id, platform["platform_id"], external_id),
    )
    expires = now() + timedelta(seconds=item["expires_in"]) if item.get("expires_in") else None
    db.execute(
        """INSERT INTO social_account_tokens(social_account_id,access_token_enc,refresh_token_enc,expires_at,scopes,token_type) VALUES (%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE access_token_enc=VALUES(access_token_enc),refresh_token_enc=VALUES(refresh_token_enc),expires_at=VALUES(expires_at),scopes=VALUES(scopes),token_type=VALUES(token_type),last_refreshed_at=NULL,refresh_fail_count=0""",
        (
            saved["social_account_id"],
            encrypt(item["access_token"]),
            encrypt(item.get("refresh_token")),
            expires,
            item.get("scope"),
            item.get("token_type"),
        ),
    )
    audit(db, request, "channel.connect", "social_account", saved["social_account_id"])
    return saved


@router.post(
    "/workspaces/{workspace_id}/social-accounts/demo/{platform}",
    dependencies=[Depends(workspace("channel.manage"))],
)
def connect_demo(workspace_id: Id, platform: Platform, request: Request):
    check(settings.social_mode == "mock", 403, "DEMO_DISABLED", "Kết nối mẫu chỉ dùng trong chế độ demo")
    social.check_oauth_available(platform)
    item, = social.exchange_code(platform, "mock", None)
    with transaction() as db:
        membership(db, workspace_id, request.state.user["user_id"], "channel.manage")
        return ok(save_connected_account(db, workspace_id, request, item))


@router.post(
    "/workspaces/{workspace_id}/social-accounts/oauth/complete-selection",
    dependencies=[Depends(workspace("channel.manage"))],
)
def complete_selection(workspace_id: Id, data: SelectionInput, request: Request):
    with transaction() as db:
        row = db.one(
            "SELECT * FROM oauth_connections WHERE connection_hash=%s AND workspace_id=%s AND user_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE",
            (hash_token(data.connection_token), workspace_id, request.state.user["user_id"]),
        )
        check(row, 422, "INVALID_CONNECTION", "Kết nối tạm không hợp lệ hoặc hết hạn")
        membership(db, workspace_id, request.state.user["user_id"], "channel.manage")
        available = json.loads(decrypt(row["accounts_enc"]))
        results = []
        for external_id in dict.fromkeys(data.external_account_ids):
            item = next((a for a in available if a["external_account_id"] == external_id), None)
            check(item, 422, "INVALID_ACCOUNT", "Tài khoản không thuộc kết quả OAuth")
            social.check_oauth_available(item["platform"])
            demo = item["external_account_id"] == f"mock-{item['platform']}"
            check(
                demo == (settings.social_mode == "mock"),
                409,
                "CHANNEL_MODE_MISMATCH",
                "Chế độ kết nối đã thay đổi. Vui lòng bắt đầu lại",
            )
            saved = save_connected_account(db, workspace_id, request, item)
            results.append(saved)
        db.execute("DELETE FROM oauth_connections WHERE connection_hash=%s", (row["connection_hash"],))
    return ok(results)


@router.post(
    "/workspaces/{workspace_id}/social-accounts/oauth/{platform}",
    dependencies=[Depends(workspace("channel.manage"))],
)
def start_oauth(workspace_id: Id, platform: Platform, request: Request, browser: bool = False):
    social.check_oauth_available(platform)
    raw, verifier = token(), token()
    if browser:
        raw = "ui." + raw
    url = social.authorize_url(platform, raw, verifier)
    with transaction() as db:
        db.insert(
            "oauth_states",
            {
                "state_hash": hash_token(raw),
                "workspace_id": workspace_id,
                "user_id": request.state.user["user_id"],
                "platform_code": platform,
                "verifier_enc": encrypt(verifier),
                "expires_at": now() + timedelta(minutes=10),
            },
        )
    return ok({"authorization_url": url, **({"callback_origin": settings.app_url} if browser else {})})


@router.get("/oauth/{platform}/callback")
def callback(
    platform: Platform,
    state: str = Query(min_length=1, max_length=100),
    code: str | None = Query(default=None, min_length=1, max_length=2048),
    error: str | None = Query(default=None, max_length=100),
):
    if not state.startswith("ui."):
        return finish_oauth(platform, state, code, error)
    try:
        result = finish_oauth(platform, state, code, error)
    except ApiError as exc:
        result = {"error": exc.message}
    except social.ProviderError:
        result = {"error": "Nền tảng từ chối hoặc chưa phản hồi. Vui lòng thử kết nối lại."}
    payload = json.dumps({"state": state, **result}).replace("<", "\\u003c")
    return HTMLResponse(
        "<!doctype html><html lang='vi'><meta charset='utf-8'><title>Kết nối kênh</title>"
        "<script>sessionStorage.setItem('orbitspace-oauth-result', JSON.stringify("
        + payload
        + ")); location.replace('/');</script><p>Đang quay lại workspace…</p></html>",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


def finish_oauth(platform, state, code, error):
    social.check_oauth_available(platform)
    check(error or code, 422, "INVALID_OAUTH_CALLBACK", "Callback thiếu mã ủy quyền")
    with transaction() as db:
        row = db.one(
            "SELECT * FROM oauth_states WHERE state_hash=%s AND platform_code=%s AND consumed_at IS NULL AND expires_at>UTC_TIMESTAMP() FOR UPDATE",
            (hash_token(state), platform),
        )
        check(row, 422, "INVALID_OAUTH_STATE", "OAuth state hết hạn hoặc đã dùng")
        membership(db, row["workspace_id"], row["user_id"], "channel.manage")
        db.execute(
            "UPDATE oauth_states SET consumed_at=UTC_TIMESTAMP() WHERE state_hash=%s", (row["state_hash"],)
        )
    if platform == "tiktok":
        check(
            error not in ("invalid_scope", "scope_not_authorized"),
            403,
            "TIKTOK_PERMISSIONS_MISSING",
            "TikTok từ chối quyền truy cập được yêu cầu",
        )
        check(not error, 400, "OAUTH_DENIED", "Yêu cầu cấp quyền TikTok bị từ chối hoặc hủy")
    else:
        check(not error, 400, "OAUTH_DENIED", "Yêu cầu cấp quyền OAuth bị từ chối hoặc hủy")
    try:
        accounts = social.exchange_code(platform, code, decrypt(row["verifier_enc"]))
    except social.ProviderError as exc:
        check(
            platform != "tiktok" or exc.code != "PROVIDER_SCOPE_MISSING",
            403,
            "TIKTOK_PERMISSIONS_MISSING",
            "TikTok chưa cấp quyền truy cập được yêu cầu",
        )
        raise
    raw = token()
    with transaction() as db:
        db.insert(
            "oauth_connections",
            {
                "connection_hash": hash_token(raw),
                "workspace_id": row["workspace_id"],
                "user_id": row["user_id"],
                "accounts_enc": encrypt(json.dumps(accounts)),
                "expires_at": now() + timedelta(minutes=10),
            },
        )
    return ok(
        {
            "connection_token": raw,
            "workspace_id": row["workspace_id"],
            "accounts": [
                {
                    "external_account_id": a["external_account_id"],
                    "account_name": a["account_name"],
                    "platform": a["platform"],
                    "linked_page_external_id": a.get("linked_page_external_id"),
                }
                for a in accounts
            ],
        }
    )


@router.post(
    "/workspaces/{workspace_id}/social-accounts/{account_id}/disconnect",
    dependencies=[Depends(workspace("channel.manage"))],
)
def disconnect(workspace_id: Id, account_id: Id, request: Request):
    with transaction() as db:
        posts = db.all(
            "SELECT DISTINCT p.post_id FROM posts p JOIN post_variants v ON v.post_id=p.post_id WHERE v.workspace_id=%s AND v.social_account_id=%s ORDER BY p.post_id",
            (workspace_id, account_id),
        )
        posts = [
            db.one("SELECT * FROM posts WHERE post_id=%s AND workspace_id=%s FOR UPDATE", (p["post_id"], workspace_id))
            for p in posts
        ]
        membership(db, workspace_id, request.state.user["user_id"], "channel.manage")
        channel = account(db, workspace_id, account_id, True)
        if channel["status"] == "disconnected":
            return ok({"status": "disconnected"})
        check(
            not db.one(
                "SELECT 1 FROM publish_jobs j JOIN post_variants v ON v.variant_id=j.variant_id WHERE v.workspace_id=%s AND v.social_account_id=%s AND j.status='running' LIMIT 1 FOR UPDATE",
                (workspace_id, account_id),
            ),
            409,
            "PUBLISH_STARTED",
            "Đang gửi bài, thử lại sau",
        )
        affected_posts = {
            row["post_id"]
            for row in db.all(
                "SELECT post_id FROM post_variants WHERE workspace_id=%s AND social_account_id=%s "
                "AND status IN ('draft','scheduled','publishing') FOR UPDATE",
                (workspace_id, account_id),
            )
        }
        db.execute("DELETE FROM social_account_tokens WHERE social_account_id=%s", (account_id,))
        db.execute(
            "UPDATE social_accounts SET status='disconnected',status_message=NULL,disconnected_at=UTC_TIMESTAMP() WHERE social_account_id=%s",
            (account_id,),
        )
        db.execute(
            "UPDATE schedules s JOIN post_variants v ON v.variant_id=s.variant_id SET s.status='cancelled',s.cancelled_at=UTC_TIMESTAMP() WHERE v.social_account_id=%s AND s.status IN ('pending','queued')",
            (account_id,),
        )
        db.execute(
            "UPDATE publish_jobs j JOIN post_variants v ON v.variant_id=j.variant_id SET j.status='failed',j.error_code='CHANNEL_DISCONNECTED',j.finished_at=UTC_TIMESTAMP() WHERE v.social_account_id=%s AND j.status='queued'",
            (account_id,),
        )
        db.execute(
            "UPDATE post_variants SET status='cancelled' WHERE social_account_id=%s AND status IN ('draft','scheduled','publishing')",
            (account_id,),
        )
        for post in posts:
            if not post or post["post_id"] not in affected_posts:
                continue
            states = [
                v["status"]
                for v in db.all("SELECT status FROM post_variants WHERE post_id=%s FOR UPDATE", (post["post_id"],))
            ]
            if all(s == "cancelled" for s in states):
                change_status(db, post, "cancelled", request.state.user["user_id"], "Ngắt kết nối kênh")
            elif "published" in states and not any(s in ("publishing", "scheduled") for s in states):
                change_status(db, post, "partially_failed", request.state.user["user_id"])
            notify(
                db,
                workspace_id,
                post["created_by"],
                "channel_disconnected",
                "Kênh ngắt kết nối; lịch chưa đăng đã hủy",
                "post",
                post["post_id"],
            )
        audit(db, request, "channel.disconnect", "social_account", account_id)
    return ok({"status": "disconnected"})


@router.post(
    "/workspaces/{workspace_id}/social-accounts/{account_id}/sync/{kind}",
    status_code=202,
    dependencies=[Depends(workspace("channel.manage"))],
)
def request_sync(workspace_id: Id, account_id: Id, kind: Literal["metrics", "inbox"], request: Request):
    with transaction() as db:
        row = account(db, workspace_id, account_id, True)
        check(row["status"] == "connected", 409, "CHANNEL_UNAVAILABLE", "Kênh chưa kết nối")
        auth = credentials(db, account_id)
        check(
            auth["expires_at"] is None or auth["expires_at"] > now(),
            409,
            "CHANNEL_UNAVAILABLE",
            "Kênh hết hạn. Vui lòng kết nối lại",
        )
        check(
            kind != "inbox" or row["code"] == "facebook",
            422,
            "CHANNEL_SYNC_UNSUPPORTED",
            "Nền tảng này chưa hỗ trợ đồng bộ hộp thư",
        )
        pending = db.one(
            """SELECT status FROM channel_sync_logs WHERE social_account_id=%s AND kind=%s
            AND status IN ('pending','syncing') ORDER BY sync_id DESC LIMIT 1""",
            (account_id, kind),
        )
        if pending:
            return ok({"status": pending["status"], "kind": kind})
        column = "last_metrics_sync_at" if kind == "metrics" else "last_inbox_sync_at"
        db.insert(
            "channel_sync_logs",
            {
                "social_account_id": account_id,
                "kind": kind,
                "status": "pending",
                "started_at": now(),
            },
        )
        db.execute(f"UPDATE social_accounts SET {column}=NULL WHERE social_account_id=%s", (account_id,))
        audit(db, request, "channel.sync_request", "social_account", account_id, new={"kind": kind})
    return ok({"status": "pending", "kind": kind})
