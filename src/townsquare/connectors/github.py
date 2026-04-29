"""GitHub connector — searches under the user's own personal access token (PAT).

Per-user PAT preserves the same per-user privacy property as the Google
connectors: the GitHub Search API returns only repositories and content
the token's owner can see. Org members see org-private repos; outside
collaborators see only what they're granted.

We use the GitHub REST search endpoints (no GraphQL dep), since they
work with a vanilla bearer token and PATs equally well.

Scopes the user grants on the PAT:
  - repo (or read:repo for fine-grained tokens) — code/issue search
    against private repos. Public-only access works without `repo`.
  - read:user — to confirm token validity and capture handle
"""

from __future__ import annotations

import httpx

from townsquare.connectors.base import Item

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


class GitHubConnector:
    source_id = "github"
    required_scopes = ["repo", "read:user"]
    supports_update = False

    async def search(self, query: str, access_token: str, limit: int = 10) -> list[Item]:
        """Search across issues, PRs, and code in repos this token can see.

        v0.1: searches issues + PRs (one request, fast). Code search is a
        separate endpoint with its own rate limits — added in v0.2.
        """
        params = {"q": query, "per_page": limit, "sort": "updated", "order": "desc"}
        headers = {**GITHUB_HEADERS, "Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{GITHUB_API}/search/issues",
                params=params,
                headers=headers,
            )
            if r.status_code in (401, 403):
                return []
            r.raise_for_status()
            data = r.json()

        items: list[Item] = []
        for it in data.get("items", []):
            repo_full = _repo_from_url(it.get("repository_url", ""))
            kind = "PR" if it.get("pull_request") else "issue"
            items.append(
                Item(
                    id=str(it.get("id", "")),
                    title=f"[{kind} #{it.get('number')}] {it.get('title', '')}",
                    snippet=(it.get("body") or "")[:1000],
                    url=it.get("html_url"),
                    occurred_at=it.get("updated_at"),
                    metadata={
                        "repo": repo_full,
                        "kind": kind,
                        "state": it.get("state"),
                        "author": (it.get("user") or {}).get("login"),
                        "labels": [lbl.get("name") for lbl in it.get("labels") or []],
                    },
                    source="github",
                )
            )
        return items

    async def fetch(self, item_id: str, access_token: str) -> Item | None:
        # GitHub items are addressed by URL more naturally than numeric id;
        # for now, expose minimal fetch via the search id is enough for v0.1.
        # Most agent flows want titles + snippets, not full bodies.
        return None


def _repo_from_url(repository_url: str) -> str | None:
    """Convert e.g. 'https://api.github.com/repos/acme/widgets' to 'acme/widgets'."""
    if not repository_url:
        return None
    marker = "/repos/"
    idx = repository_url.find(marker)
    if idx == -1:
        return None
    return repository_url[idx + len(marker) :]
