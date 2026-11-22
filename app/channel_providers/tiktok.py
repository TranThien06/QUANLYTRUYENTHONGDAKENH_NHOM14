from app import social
from app.errors import check


def exchange(code, redirect):
    result = social.call(
        "https://open.tiktokapis.com/v2/oauth/token/",
        method="POST",
        data={
            **social.tiktok_client(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect,
        },
    )
    check(
        all(
            isinstance(result.get(key), str) and result[key]
            for key in ("access_token", "refresh_token", "open_id")
        )
        and isinstance(result.get("scope"), str)
        and type(result.get("expires_in")) is int
        and result["expires_in"] > 0,
        502,
        "TIKTOK_INVALID_TOKEN_RESPONSE",
        "TikTok trả về dữ liệu token không hợp lệ",
    )
    missing = set(social.tiktok_scopes()) - {scope.strip() for scope in result["scope"].split(",")}
    check(
        not missing,
        403,
        "TIKTOK_PERMISSIONS_MISSING",
        "TikTok chưa cấp quyền: " + ", ".join(sorted(missing)),
    )
    profile = social.tiktok("user/info/?fields=open_id,display_name,avatar_url", result["access_token"])
    data = profile.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    check(
        isinstance(user, dict)
        and user.get("open_id") == result["open_id"]
        and isinstance(user.get("display_name"), str)
        and user["display_name"],
        502,
        "TIKTOK_INVALID_PROFILE",
        "TikTok trả về thông tin tài khoản không hợp lệ",
    )
    return [
        {
            **result,
            "external_account_id": user["open_id"],
            "account_name": user["display_name"],
            "avatar_url": user.get("avatar_url"),
            "account_type": "creator",
            "platform": "tiktok",
        }
    ]


def profile(identifier, access_token):
    result = social.tiktok("user/info/?fields=open_id,display_name,avatar_url", access_token)
    user = (result.get("data") or {}).get("user") or {}
    if user.get("open_id") != identifier:
        raise social.ProviderError("CHANNEL_IDENTITY_MISMATCH")
    return {"name": user.get("display_name"), "avatar_url": user.get("avatar_url")}
