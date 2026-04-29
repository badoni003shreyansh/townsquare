"""Anthropic tool definitions + handlers for townsquare's central agent."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from townsquare.db.models import WikiPage
from townsquare.federation.router import FederatedRouter
from townsquare.federation.selector import Selector

TOOL_DEFINITIONS = [
    {
        "name": "ask_company",
        "description": (
            "Federate a sub-question across the company. Searches every employee's "
            "Gmail, Drive, and Calendar (whichever they have connected), respecting "
            "per-user permissions at the source. Returns a list of items each tagged "
            "with the contributing user_email and source. Use this whenever you need "
            "information that lives in users' personal data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query passed to each connector.",
                },
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["gmail", "drive", "calendar"]},
                    "description": "Restrict to specific sources. Omit to search all.",
                },
                "users": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Restrict to specific user emails. Omit for whole company.",
                },
                "per_target_limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Max items per (user, source) target.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_wiki",
        "description": "Read a shared org wiki page by its slug.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string", "description": "Page slug (lowercase, hyphenated)."},
            },
            "required": ["slug"],
        },
    },
    {
        "name": "write_wiki",
        "description": (
            "Create or update a shared wiki page. Use only when explicitly asked. "
            "Append-friendly: the agent should prefer additive edits over rewriting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "title": {"type": "string"},
                "body_markdown": {"type": "string"},
            },
            "required": ["slug", "title", "body_markdown"],
        },
    },
]


async def handle_ask_company(
    args: dict[str, Any],
    router: FederatedRouter,
    selector: Selector,
    asking_user: str,
) -> dict[str, Any]:
    query = args.get("query", "")
    sources = args.get("sources")
    users = args.get("users")
    per_target_limit = args.get("per_target_limit", 5)

    targets = await selector.select(
        query=query,
        asking_user=asking_user,
        explicit_users=users,
        explicit_sources=sources,
    )
    fanout = await router.fanout(query=query, targets=targets, per_target_limit=per_target_limit)

    items_payload = [
        {
            "user_email": item.user_email,
            "source": item.source,
            "title": item.title,
            "snippet": item.snippet,
            "url": item.url,
            "occurred_at": item.occurred_at,
        }
        for item in fanout.items
    ]
    citations = [
        {
            "user_email": item.user_email,
            "source": item.source,
            "title": item.title,
            "url": item.url,
        }
        for item in fanout.items
    ]
    return {
        "items": items_payload,
        "citations": citations,
        "target_count": len(fanout.targets),
        "errors": fanout.errors,
    }


def handle_read_wiki(
    args: dict[str, Any], session_factory: Callable[[], Session]
) -> dict[str, Any]:
    slug = args.get("slug", "").strip().lower()
    if not slug:
        return {"error": "slug is required"}
    with session_factory() as session:
        page = session.execute(select(WikiPage).where(WikiPage.slug == slug)).scalar_one_or_none()
        if page is None:
            return {"found": False}
        return {
            "found": True,
            "slug": page.slug,
            "title": page.title,
            "body_markdown": page.body_markdown,
            "version": page.version,
            "last_edited_at": page.last_edited_at.isoformat() if page.last_edited_at else None,
            "last_edited_by": page.last_edited_by,
        }


def handle_write_wiki(
    args: dict[str, Any], session_factory: Callable[[], Session], actor_email: str
) -> dict[str, Any]:
    slug = args.get("slug", "").strip().lower()
    title = args.get("title", "").strip()
    body = args.get("body_markdown", "")
    if not (slug and title):
        return {"error": "slug and title are required"}

    with session_factory() as session:
        page = session.get(WikiPage, slug)
        now = datetime.utcnow()
        if page is None:
            page = WikiPage(
                slug=slug,
                title=title,
                body_markdown=body,
                created_by=actor_email,
                last_edited_by=actor_email,
                last_edited_at=now,
                version=1,
            )
            session.add(page)
            session.commit()
            return {"ok": True, "created": True, "slug": slug, "version": 1}
        page.title = title
        page.body_markdown = body
        page.last_edited_by = actor_email
        page.last_edited_at = now
        page.version += 1
        session.commit()
        return {"ok": True, "created": False, "slug": slug, "version": page.version}
