from app.channel_providers import meta
from app.errors import check
from app.social import FACEBOOK_SCOPES

PUBLISH_TASKS = {"CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT", "PROFILE_PLUS_FULL_CONTROL"}


def exchange(code, redirect):
    token, granted = meta.grant(code, redirect)
    check(
        "pages_show_list" in granted,
        403,
        "FACEBOOK_PERMISSIONS_MISSING",
        "Meta chưa cấp quyền liệt kê Trang Facebook",
    )
    accounts = []
    for page in meta.pages(token, "id,name,access_token,picture,tasks"):
        if not (page.get("id") and page.get("name") and page.get("access_token")):
            continue
        scopes = granted.intersection(FACEBOOK_SCOPES)
        if not PUBLISH_TASKS.intersection(page.get("tasks") or ()):
            scopes.discard("pages_manage_posts")
        accounts.append(
            {
                "external_account_id": page["id"],
                "account_name": page["name"],
                "avatar_url": picture(page),
                "account_type": "page",
                "platform": "facebook",
                "access_token": page["access_token"],
                "scope": ",".join(sorted(scopes)),
            }
        )
    check(accounts, 422, "NO_FACEBOOK_PAGES", "Không tìm thấy Page được cấp quyền kết nối")
    return accounts


def picture(page):
    return (page.get("picture") or {}).get("data", {}).get("url")


def profile(identifier, access_token):
    page = meta.profile(identifier, access_token, "id,name,picture")
    return {"name": page.get("name"), "avatar_url": picture(page)}
