"""Wiki routes — list / view / new / edit."""

from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from townsquare.db.models import User, WikiPage
from townsquare.web.deps import get_cached_settings, get_current_user, get_db
from townsquare.web.templating import render

router = APIRouter()

SLUG_RE = re.compile(r"^[a-z0-9-]+$")


@router.get("/wiki", response_class=HTMLResponse)
async def wiki_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pages = db.execute(select(WikiPage).order_by(desc(WikiPage.last_edited_at))).scalars().all()
    return render(
        request,
        "wiki_list.html",
        user=user,
        workspace_domain=get_cached_settings().workspace_domain,
        pages=pages,
    )


@router.get("/wiki/new", response_class=HTMLResponse)
async def wiki_new(request: Request, user: User = Depends(get_current_user)):
    return render(
        request,
        "wiki_edit.html",
        user=user,
        workspace_domain=get_cached_settings().workspace_domain,
        page=None,
    )


@router.post("/wiki/new")
async def wiki_create(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    body: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "slug must be lowercase letters, numbers, and hyphens only")
    existing = db.get(WikiPage, slug)
    if existing is not None:
        raise HTTPException(409, f"page '{slug}' already exists")
    page = WikiPage(
        slug=slug,
        title=title.strip(),
        body_markdown=body,
        created_by=user.email,
        last_edited_by=user.email,
        last_edited_at=datetime.utcnow(),
        version=1,
    )
    db.add(page)
    return RedirectResponse(f"/wiki/{slug}", status_code=303)


@router.get("/wiki/{slug}", response_class=HTMLResponse)
async def wiki_view(
    request: Request,
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page = db.get(WikiPage, slug)
    if page is None:
        raise HTTPException(404, "page not found")
    return render(
        request,
        "wiki_view.html",
        user=user,
        workspace_domain=get_cached_settings().workspace_domain,
        page=page,
    )


@router.get("/wiki/{slug}/edit", response_class=HTMLResponse)
async def wiki_edit_page(
    request: Request,
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page = db.get(WikiPage, slug)
    if page is None:
        raise HTTPException(404, "page not found")
    return render(
        request,
        "wiki_edit.html",
        user=user,
        workspace_domain=get_cached_settings().workspace_domain,
        page=page,
    )


@router.post("/wiki/{slug}/edit")
async def wiki_update(
    request: Request,
    slug: str,
    title: str = Form(...),
    body: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    page = db.get(WikiPage, slug)
    if page is None:
        raise HTTPException(404, "page not found")
    page.title = title.strip()
    page.body_markdown = body
    page.last_edited_by = user.email
    page.last_edited_at = datetime.utcnow()
    page.version += 1
    return RedirectResponse(f"/wiki/{slug}", status_code=303)
