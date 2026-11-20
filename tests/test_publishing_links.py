import pytest

from app import social


@pytest.mark.parametrize("available", [True, False])
def test_facebook_keeps_post_id_when_reading_permalink(monkeypatch, available):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    permalink = "https://www.facebook.com/page/posts/456"
    calls = []

    def graph(path, token, params, method="GET", publishing=False):
        calls.append((method, path))
        if method == "POST":
            return {"id": "123_456"}
        assert params == {"fields": "permalink_url"}
        if not available:
            raise social.ProviderError("PROVIDER_REJECTED")
        return {"permalink_url": permalink}

    monkeypatch.setattr(social, "graph", graph)
    result = social.publish_remote(
        {"code": "facebook", "external_account_id": "123"},
        {"platform_options": {}},
        [],
        "caption",
        "token",
        {},
        None,
    )
    assert calls == [("POST", "123/feed"), ("GET", "123_456")]
    assert result == {"external_post_id": "123_456", "external_post_url": permalink if available else None}


@pytest.mark.parametrize("available", [True, False])
def test_instagram_uses_published_media_id_for_permalink(monkeypatch, available):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    monkeypatch.setattr(social, "signed_url", lambda item: "https://example.com/image.png")
    permalink = "https://www.instagram.com/p/published/"
    calls = []

    def graph(path, token, params, method="GET", publishing=False):
        calls.append((method, path, params))
        if path == "container":
            return {"status_code": "FINISHED"}
        if method == "POST":
            return {"id": "published-media"}
        if not available:
            raise social.ProviderError("PROVIDER_REJECTED")
        return {"permalink": permalink}

    monkeypatch.setattr(social, "graph", graph)
    result = social.publish_remote(
        {"code": "instagram", "external_account_id": "account"},
        {"platform_options": {}},
        [{"media_type": "image"}],
        "caption",
        "token",
        {"container_id": "container"},
        None,
    )
    assert calls == [
        ("GET", "container", {"fields": "status_code"}),
        ("POST", "account/media_publish", {"creation_id": "container"}),
        ("GET", "published-media", {"fields": "permalink"}),
    ]
    assert result == {
        "external_post_id": "published-media",
        "external_post_url": permalink if available else None,
    }


@pytest.mark.parametrize("available", [True, False])
def test_tiktok_reads_share_url_for_the_published_video(monkeypatch, available):
    monkeypatch.setattr(social.settings, "social_mode", "live")
    video_id = "7250000000000000001"
    share_url = f"https://www.tiktok.com/@page/video/{video_id}"

    def tiktok(path, token, payload):
        if path == "post/publish/status/fetch/":
            assert payload == {"publish_id": "pending-id"}
            return {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [int(video_id)]}}
        assert path == "video/query/?fields=id,share_url"
        assert payload == {"filters": {"video_ids": [video_id]}}
        if not available:
            raise social.ProviderError("PROVIDER_SCOPE_MISSING")
        return {
            "data": {
                "videos": [{"id": "other", "share_url": "wrong"}, {"id": video_id, "share_url": share_url}]
            }
        }

    monkeypatch.setattr(social, "tiktok", tiktok)
    result = social.publish_remote(
        {"code": "tiktok", "external_account_id": "account"},
        {"platform_options": {"privacy_level": "PUBLIC_TO_EVERYONE"}},
        [],
        "caption",
        "token",
        {"publish_id": "pending-id"},
        None,
    )
    assert result == {"external_post_id": video_id, "external_post_url": share_url if available else None}
