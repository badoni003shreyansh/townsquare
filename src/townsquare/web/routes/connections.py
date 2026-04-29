"""Connections page — shows which sources each user has connected."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from townsquare.db.models import Connection, User
from townsquare.web.deps import get_cached_settings, get_current_user, get_db
from townsquare.web.templating import render

router = APIRouter()


SOURCE_CATALOG = [
    {
        "id": "gmail",
        "name": "Gmail",
        "description": "Search your Gmail. Granted at sign-in.",
        "connect_url": None,
    },
    {
        "id": "drive",
        "name": "Google Drive",
        "description": "Search your Google Drive (Docs, Sheets, Slides). Granted at sign-in.",
        "connect_url": None,
    },
    {
        "id": "calendar",
        "name": "Google Calendar",
        "description": "Search your Google Calendar events. Granted at sign-in.",
        "connect_url": None,
    },
    {"id": "slack", "name": "Slack", "description": "Per-user Slack search.", "connect_url": None},
    {
        "id": "notion",
        "name": "Notion",
        "description": "Per-user Notion search.",
        "connect_url": None,
    },
    {
        "id": "github",
        "name": "GitHub",
        "description": "Per-user GitHub search.",
        "connect_url": None,
    },
]


@router.get("/connections", response_class=HTMLResponse)
async def connections(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(Connection).where(Connection.user_email == user.email)).scalars().all()
    by_source = {c.source: c for c in rows}

    return render(
        request,
        "connections.html",
        user=user,
        workspace_domain=get_cached_settings().workspace_domain,
        all_sources=SOURCE_CATALOG,
        connections=by_source,
    )
