from app import social
from app.errors import check


def grant(code, redirect):
    endpoint = f"{social.graph_base()}/oauth/access_token"
    client = social.meta_client()
    result = social.call(endpoint, params={**client, "code": code, "redirect_uri": redirect})
    user_token = result.get("access_token")
    check(user_token, 502, "META_TOKEN_MISSING", "Meta chưa trả token người dùng")
    result = social.call(
        endpoint, params={**client, "grant_type": "fb_exchange_token", "fb_exchange_token": user_token}
    )
    user_token = result.get("access_token")
    check(user_token, 502, "META_TOKEN_MISSING", "Meta chưa trả token người dùng dài hạn")
    scopes = {
        entry["permission"]
        for entry in social.graph_list("me/permissions", user_token, {})
        if entry.get("permission") and entry.get("status") == "granted"
    }
    return user_token, scopes


def pages(user_token, fields):
    return social.graph_list("me/accounts", user_token, {"fields": fields, "limit": 100})


def profile(identifier, access_token, fields):
    result = social.graph(identifier, access_token, {"fields": fields})
    if result.get("id") != identifier:
        raise social.ProviderError("CHANNEL_IDENTITY_MISMATCH")
    return result
