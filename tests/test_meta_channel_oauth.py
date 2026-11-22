from urllib.parse import parse_qs, urlsplit

import pytest

from app import social
from app.channel_policy import publishing_error
from app.channel_providers import meta
from app.errors import ApiError


def test_facebook_pilot_requires_live_configuration_and_uses_selected_scopes(monkeypatch):
    monkeypatch.setattr(social.settings, "social_oauth_platforms", {"facebook"})
    monkeypatch.setattr(social.settings, "social_oauth_require_live", True)
    monkeypatch.setattr(social.settings, "social_mode", "mock")
    assert not social.capabilities("facebook")["oauth_ready"]
    with pytest.raises(ApiError) as disabled:
        social.check_oauth_available("instagram")
    assert disabled.value.code == "OAUTH_PLATFORM_DISABLED"
    with pytest.raises(ApiError) as mock:
        social.check_oauth_available("facebook")
    assert mock.value.code == "OAUTH_LIVE_REQUIRED"

    monkeypatch.setattr(social.settings, "social_mode", "live")
    monkeypatch.setattr(social.settings, "app_url", "https://social.example.com")
    monkeypatch.delenv("META_APP_SECRET", raising=False)
    assert not social.capabilities("facebook")["oauth_ready"]
    monkeypatch.setenv("META_APP_ID", "123")
    monkeypatch.setenv("META_APP_SECRET", "server-only")
    monkeypatch.setenv("META_API_VERSION", "v27.0")
    monkeypatch.setenv("FACEBOOK_OAUTH_SCOPES", "pages_read_engagement")
    assert social.capabilities("facebook")["oauth_ready"]
    url = urlsplit(social.authorize_url("facebook", "state", "verifier"))
    params = parse_qs(url.query)
    assert url.hostname == "www.facebook.com"
    assert params["redirect_uri"] == ["https://social.example.com/api/v1/oauth/facebook/callback"]
    assert params["scope"] == ["pages_show_list,pages_read_engagement"]
    assert "server-only" not in url.geturl()


def test_facebook_page_publish_permission_requires_page_task(monkeypatch):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    monkeypatch.setattr(meta, "grant", lambda code, redirect: ("user-token", set(social.FACEBOOK_SCOPES)))

    def pages(token, fields):
        assert token == "user-token" and "tasks" in fields
        return [
            {"id": "1", "name": "Managed", "access_token": "page-one", "tasks": ["CREATE_CONTENT"]},
            {"id": "2", "name": "Read only", "access_token": "page-two", "tasks": ["ANALYZE"]},
            {"id": "3", "name": "Inaccessible"},
        ]

    monkeypatch.setattr(meta, "pages", pages)
    first, second = social.exchange_code("facebook", "code", "unused")
    assert first["external_account_id"] == "1"
    assert "pages_manage_posts" in first["scope"].split(",")
    assert second["external_account_id"] == "2"
    assert "pages_manage_posts" not in second["scope"].split(",")


def test_instagram_requires_granted_scopes_before_listing_pages(monkeypatch):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    monkeypatch.setattr(meta, "grant", lambda code, redirect: ("user-token", {"instagram_basic"}))
    with pytest.raises(ApiError) as exc:
        social.exchange_code("instagram", "code", "unused")
    assert exc.value.status == 403
    assert exc.value.code == "INSTAGRAM_PERMISSIONS_MISSING"


def test_meta_account_check_rejects_mismatched_provider_identity(monkeypatch):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    monkeypatch.setattr(social, "graph", lambda *args: {"id": "other"})
    with pytest.raises(social.ProviderError, match="CHANNEL_IDENTITY_MISMATCH"):
        social.channel_profile({"code": "facebook", "external_account_id": "1"}, "page-token")


def test_live_content_rejects_demo_channels_and_missing_publish_scopes(monkeypatch):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    channel = {
        "status": "connected",
        "code": "facebook",
        "external_account_id": "mock-facebook",
        "scopes": "",
    }
    assert publishing_error(channel)[0] == "CHANNEL_MODE_MISMATCH"
    channel["external_account_id"] = "real-page-id"
    assert publishing_error(channel)[0] == "CHANNEL_PUBLISH_PERMISSION_MISSING"
    channel["scopes"] = "pages_show_list,pages_manage_posts"
    assert publishing_error(channel) is None
