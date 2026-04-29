"""Slack connector — searches under the user's own xoxp user-token.

We deliberately use **user-tokens** (xoxp), not bot-tokens (xoxb), so that
each employee's Slack visibility is preserved at the source: Bob's
sidecar can only see channels Bob is in, DMs Bob is part of, etc.

This is meaningfully different from how most enterprise Slack
integrations work (which install one bot, see all the channels the bot
is invited to, and then filter at query time). townsquare's federation
model rejects that pattern.

OAuth scopes the user must grant:
  - search:read     — required for Slack's search API
  - users:read      — display-name lookups
  - users:read.email — to map Slack user → townsquare email
"""

from __future__ import annotations

from typing import Any

import httpx

from townsquare.connectors.base import Item

SLACK_API = "https://slack.com/api"


class SlackConnector:
    source_id = "slack"
    required_scopes = ["search:read", "users:read", "users:read.email"]
    supports_update = False

    async def search(self, query: str, access_token: str, limit: int = 10) -> list[Item]:
        """Search messages and files using the user's own search permissions."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{SLACK_API}/search.messages",
                params={"query": query, "count": limit, "sort": "timestamp"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code in (401, 403):
                return []
            r.raise_for_status()
            data = r.json()

        if not data.get("ok"):
            # invalid_auth, missing_scope, etc. Return empty rather than raising.
            return []

        matches = (data.get("messages") or {}).get("matches") or []
        items: list[Item] = []
        for m in matches:
            channel = (m.get("channel") or {}) or {}
            user = m.get("username") or m.get("user")
            text = m.get("text") or ""
            permalink = m.get("permalink")
            ts = m.get("ts")
            items.append(
                Item(
                    id=f"{channel.get('id', '?')}::{ts}",
                    title=f"#{channel.get('name', 'dm')}",
                    snippet=text[:1000],
                    url=permalink,
                    occurred_at=_ts_to_iso(ts),
                    metadata={
                        "channel_id": channel.get("id"),
                        "channel_name": channel.get("name"),
                        "user": user,
                        "ts": ts,
                    },
                    source="slack",
                )
            )
        return items

    async def fetch(self, item_id: str, access_token: str) -> Item | None:
        """Fetch full message context (the message + a few replies)."""
        if "::" not in item_id:
            return None
        channel_id, ts = item_id.split("::", 1)

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{SLACK_API}/conversations.replies",
                params={"channel": channel_id, "ts": ts, "limit": 5},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code in (401, 403):
                return None
            r.raise_for_status()
            data = r.json()
        if not data.get("ok"):
            return None

        messages: list[dict[str, Any]] = data.get("messages") or []
        if not messages:
            return None
        head = messages[0]
        body_lines = [m.get("text", "") for m in messages]
        body = "\n---\n".join(body_lines)[:4000]

        return Item(
            id=item_id,
            title=f"thread in {channel_id}",
            snippet=body,
            url=None,
            occurred_at=_ts_to_iso(head.get("ts")),
            metadata={"reply_count": len(messages) - 1, "channel_id": channel_id},
            source="slack",
        )


def _ts_to_iso(slack_ts: str | None) -> str | None:
    if not slack_ts:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(slack_ts), tz=timezone.utc).isoformat()
    except Exception:
        return None
