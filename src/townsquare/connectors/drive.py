"""Google Drive connector — searches under the user's own access token."""

from __future__ import annotations

import httpx

from townsquare.connectors.base import Item

DRIVE_API = "https://www.googleapis.com/drive/v3"


class DriveConnector:
    source_id = "drive"
    required_scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    supports_update = False

    async def search(self, query: str, access_token: str, limit: int = 10) -> list[Item]:
        # Drive's `q` parameter uses a strict syntax (e.g.,
        # "fullText contains 'foo'"). Wrap the natural query string
        # so users can type free text.
        escaped = query.replace("'", "\\'")
        q = f"fullText contains '{escaped}' and trashed = false"
        params = {
            "q": q,
            "pageSize": limit,
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink,owners(emailAddress))",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{DRIVE_API}/files",
                params=params,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if r.status_code in (401, 403):
                return []
            r.raise_for_status()
            payload = r.json()

        items: list[Item] = []
        for f in payload.get("files", []):
            items.append(
                Item(
                    id=f["id"],
                    title=f.get("name", "(untitled)"),
                    snippet=f.get("mimeType", ""),
                    url=f.get("webViewLink"),
                    occurred_at=f.get("modifiedTime"),
                    metadata={
                        "mime_type": f.get("mimeType"),
                        "owners": [o.get("emailAddress") for o in f.get("owners") or []],
                    },
                    source="drive",
                )
            )
        return items

    async def fetch(self, item_id: str, access_token: str) -> Item | None:
        """Fetch file metadata + plain-text export for Google Workspace docs."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            meta = await client.get(
                f"{DRIVE_API}/files/{item_id}",
                params={"fields": "id,name,mimeType,modifiedTime,webViewLink,owners(emailAddress)"},
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if meta.status_code in (401, 403):
                return None
            meta.raise_for_status()
            f = meta.json()

            text = ""
            mime = f.get("mimeType", "")
            if mime in (
                "application/vnd.google-apps.document",
                "application/vnd.google-apps.spreadsheet",
                "application/vnd.google-apps.presentation",
            ):
                export_mime = (
                    "text/plain"
                    if mime != "application/vnd.google-apps.spreadsheet"
                    else "text/csv"
                )
                exp = await client.get(
                    f"{DRIVE_API}/files/{item_id}/export",
                    params={"mimeType": export_mime},
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if exp.status_code == 200:
                    text = exp.text[:8000]

            return Item(
                id=item_id,
                title=f.get("name", "(untitled)"),
                snippet=text or f.get("mimeType", ""),
                url=f.get("webViewLink"),
                occurred_at=f.get("modifiedTime"),
                metadata={
                    "mime_type": mime,
                    "owners": [o.get("emailAddress") for o in f.get("owners") or []],
                },
                source="drive",
            )
