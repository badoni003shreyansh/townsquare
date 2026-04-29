"""Google Calendar connector — searches under the user's own access token."""

from __future__ import annotations

import httpx

from townsquare.connectors.base import Item

CAL_API = "https://www.googleapis.com/calendar/v3"


class CalendarConnector:
    source_id = "calendar"
    required_scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    supports_update = False

    async def search(self, query: str, access_token: str, limit: int = 10) -> list[Item]:
        params = {
            "q": query,
            "maxResults": limit,
            "singleEvents": "true",
            "orderBy": "startTime",
            "timeMin": _now_iso(),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{CAL_API}/calendars/primary/events",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code in (401, 403):
                return []
            r.raise_for_status()
            payload = r.json()

        items: list[Item] = []
        for ev in payload.get("items", []):
            start = ev.get("start", {}) or {}
            attendees = [a.get("email") for a in ev.get("attendees", []) or []]
            items.append(
                Item(
                    id=ev.get("id", ""),
                    title=ev.get("summary", "(untitled event)"),
                    snippet=(ev.get("description") or "")[:500],
                    url=ev.get("htmlLink"),
                    occurred_at=start.get("dateTime") or start.get("date"),
                    metadata={
                        "attendees": attendees,
                        "location": ev.get("location"),
                        "organizer": (ev.get("organizer") or {}).get("email"),
                    },
                    source="calendar",
                )
            )
        return items

    async def fetch(self, item_id: str, access_token: str) -> Item | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{CAL_API}/calendars/primary/events/{item_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code in (401, 403, 404):
                return None
            r.raise_for_status()
            ev = r.json()
        start = ev.get("start", {}) or {}
        return Item(
            id=item_id,
            title=ev.get("summary", "(untitled event)"),
            snippet=ev.get("description", "") or "",
            url=ev.get("htmlLink"),
            occurred_at=start.get("dateTime") or start.get("date"),
            metadata={
                "attendees": [a.get("email") for a in ev.get("attendees", []) or []],
                "location": ev.get("location"),
            },
            source="calendar",
        )


def _now_iso() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
