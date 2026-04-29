"""Slack + GitHub connector tests with mocked HTTP."""

from __future__ import annotations

import pytest

from townsquare.connectors.github import GitHubConnector, _repo_from_url
from townsquare.connectors.slack import SlackConnector, _ts_to_iso


def test_slack_connector_advertises_user_scopes():
    c = SlackConnector()
    # Critical: must be user-token scopes (search:read), not bot-token scopes.
    assert "search:read" in c.required_scopes
    assert c.supports_update is False


def test_github_connector_advertises_pat_scopes():
    c = GitHubConnector()
    assert "repo" in c.required_scopes
    assert c.supports_update is False


def test_github_repo_extraction():
    assert _repo_from_url("https://api.github.com/repos/acme/widgets") == "acme/widgets"
    assert _repo_from_url("") is None
    assert _repo_from_url("https://example.com/foo") is None


def test_slack_ts_to_iso_handles_floats_and_nones():
    assert _ts_to_iso(None) is None
    assert _ts_to_iso("not-a-number") is None
    iso = _ts_to_iso("1714000000.000100")
    assert iso is not None and iso.startswith("2024-")


@pytest.mark.asyncio
async def test_slack_search_returns_empty_on_unauthenticated(monkeypatch):
    """If Slack returns ok=false, the connector returns [] (never raises)."""
    import httpx

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": False, "error": "invalid_auth"}

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    items = await SlackConnector().search("anything", "xoxp-fake")
    assert items == []


@pytest.mark.asyncio
async def test_github_search_returns_items_from_payload(monkeypatch):
    import httpx

    payload = {
        "items": [
            {
                "id": 12345,
                "number": 42,
                "title": "Auth refactor",
                "body": "Replace passport with authlib",
                "html_url": "https://github.com/acme/widgets/issues/42",
                "updated_at": "2026-04-29T10:00:00Z",
                "state": "open",
                "user": {"login": "alice"},
                "labels": [{"name": "auth"}, {"name": "v0.1"}],
                "repository_url": "https://api.github.com/repos/acme/widgets",
                "pull_request": None,
            }
        ]
    }

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    items = await GitHubConnector().search("auth", "ghp_fake")
    assert len(items) == 1
    item = items[0]
    assert "[issue #42] Auth refactor" in item.title
    assert item.metadata["repo"] == "acme/widgets"
    assert item.metadata["kind"] == "issue"
    assert item.metadata["author"] == "alice"
    assert "auth" in item.metadata["labels"]
