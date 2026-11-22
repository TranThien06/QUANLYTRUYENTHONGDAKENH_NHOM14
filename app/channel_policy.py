from app.config import settings
from app.errors import check

PUBLISH_SCOPES = {
    "facebook": "pages_manage_posts",
    "instagram": "instagram_content_publish",
    "tiktok": "video.publish",
}


def publishing_error(account):
    if not account or account["status"] != "connected":
        return "CHANNEL_UNAVAILABLE", "Kênh chưa kết nối hoặc đã hết hạn"
    platform = account["code"]
    mock = settings.social_mode == "mock"
    if (account["external_account_id"] == f"mock-{platform}") != mock:
        return "CHANNEL_MODE_MISMATCH", "Kênh thuộc chế độ kết nối khác"
    if not mock and PUBLISH_SCOPES[platform] not in (account["scopes"] or "").split(","):
        return "CHANNEL_PUBLISH_PERMISSION_MISSING", "Kênh chưa có quyền đăng bài. Vui lòng cấp quyền lại"
    return None


def publishable_account(db, workspace_id, account_id):
    account = db.one(
        """SELECT a.*,p.code,p.max_caption_length,t.scopes FROM social_accounts a
        JOIN platforms p ON p.platform_id=a.platform_id
        JOIN social_account_tokens t ON t.social_account_id=a.social_account_id
        WHERE a.social_account_id=%s AND a.workspace_id=%s AND (t.expires_at IS NULL OR t.expires_at>UTC_TIMESTAMP())""",
        (account_id, workspace_id),
    )
    error = publishing_error(account)
    if error:
        check(False, 409, *error)
    return account
