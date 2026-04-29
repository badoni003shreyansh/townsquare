"""Gmail connector — searches under the user's own access token.

Uses the Gmail REST API directly via httpx (lighter than
google-api-python-client; works with just a bearer token).
"""

from __future__ import annotations

import asyncio
import base64
import re
from typing import Any

import httpx

from townsquare.connectors.base import Item

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailConnector:
    source_id = "gmail"
    required_scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    supports_update = False

    async def search(self, query: str, access_token: str, limit: int = 10) -> list[Item]:
        """Search Gmail with the user's query syntax (matches Gmail web UI)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{GMAIL_API}/messages",
                params={"q": query, "maxResults": limit},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code in (401, 403):
                return []
            r.raise_for_status()
            payload = r.json()

            ids = [m["id"] for m in payload.get("messages", [])]
            if not ids:
                return []

            # Fetch each message's metadata in parallel.
            tasks = [self._fetch_metadata(client, mid, access_token) for mid in ids]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return [r for r in results if isinstance(r, Item)]

    async def fetch(self, item_id: str, access_token: str) -> Item | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            return await self._fetch_metadata(client, item_id, access_token, full=True)

    async def _fetch_metadata(
        self,
        client: httpx.AsyncClient,
        msg_id: str,
        access_token: str,
        full: bool = False,
    ) -> Item:
        params = {"format": "full" if full else "metadata"}
        if not full:
            params["metadataHeaders"] = ["From", "To", "Subject", "Date"]
        r = await client.get(
            f"{GMAIL_API}/messages/{msg_id}",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        r.raise_for_status()
        msg = r.json()

        headers = {h["name"]: h["value"] for h in (msg.get("payload") or {}).get("headers", [])}
        snippet = msg.get("snippet", "") or ""
        if full:
            body = self._extract_text_body(msg.get("payload", {}))
            if body:
                snippet = body[:2000]

        return Item(
            id=msg_id,
            title=headers.get("Subject", "(no subject)"),
            snippet=snippet,
            url=f"https://mail.google.com/mail/u/0/#inbox/{msg_id}",
            occurred_at=headers.get("Date"),
            metadata={
                "from": headers.get("From"),
                "to": headers.get("To"),
                "thread_id": msg.get("threadId"),
                "label_ids": msg.get("labelIds", []),
            },
            source="gmail",
        )

    @staticmethod
    def _extract_text_body(payload: dict[str, Any]) -> str:
        """Walk a Gmail message payload tree and return the first text/plain part."""

        def walk(part: dict[str, Any]) -> str | None:
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                data = (part.get("body") or {}).get("data")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data + "==").decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        return None
            for sub in part.get("parts", []) or []:
                found = walk(sub)
                if found:
                    return found
            return None

        body = walk(payload) or ""
        # collapse whitespace
        return re.sub(r"\n{3,}", "\n\n", body.strip())
