from app.channel_providers import meta
from app.errors import check
from app.social import INSTAGRAM_SCOPES


def exchange(code, redirect):
    token, granted = meta.grant(code, redirect)
    missing = sorted(set(INSTAGRAM_SCOPES) - granted)
    check(not missing, 403, "INSTAGRAM_PERMISSIONS_MISSING", "Thiếu quyền Meta: " + ", ".join(missing))
    fields = "id,access_token,instagram_business_account{id,username,profile_picture_url}"
    accounts = []
    for page in meta.pages(token, fields):
        user = page.get("instagram_business_account") or {}
        if not (page.get("id") and page.get("access_token") and user.get("id") and user.get("username")):
            continue
        accounts.append(
            {
                "external_account_id": user["id"],
                "account_name": user["username"],
                "avatar_url": user.get("profile_picture_url"),
                "account_type": "business",
                "platform": "instagram",
                "access_token": page["access_token"],
                "linked_page_external_id": page["id"],
                "scope": ",".join(sorted(granted.intersection(INSTAGRAM_SCOPES))),
            }
        )
    check(
        accounts,
        422,
        "NO_ELIGIBLE_INSTAGRAM_ACCOUNTS",
        "Không tìm thấy Instagram Business hoặc Creator liên kết với Facebook Page được cấp quyền",
    )
    return accounts


def profile(identifier, access_token):
    user = meta.profile(identifier, access_token, "id,username,profile_picture_url")
    return {"name": user.get("username"), "avatar_url": user.get("profile_picture_url")}
