"""Dashboard / ask routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from townsquare.agent.runner import AgentConfig, CentralAgent
from townsquare.connectors.registry import default_registry
from townsquare.db import get_session_factory
from townsquare.db.models import QueryLog, User
from townsquare.federation.router import FederatedRouter
from townsquare.federation.selector import Selector
from townsquare.web.deps import (
    get_cached_settings,
    get_current_user,
    get_current_user_optional,
    get_db,
    get_token_crypto,
)
from townsquare.web.templating import render

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    settings = get_cached_settings()
    if user is None:
        return render(
            request,
            "login.html",
            workspace_domain=settings.workspace_domain,
            user=None,
        )

    user_count = db.execute(select(User).where(User.is_active.is_(True))).scalars().all()
    recent = (
        db.execute(
            select(QueryLog)
            .where(QueryLog.user_email == user.email)
            .order_by(desc(QueryLog.created_at))
            .limit(5)
        )
        .scalars()
        .all()
    )

    return render(
        request,
        "dashboard.html",
        user=user,
        workspace_domain=settings.workspace_domain,
        user_count=len(user_count),
        recent_queries=recent,
    )


@router.post("/ask", response_class=HTMLResponse)
async def ask(
    request: Request,
    question: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_cached_settings()
    crypto = get_token_crypto()

    session_factory = get_session_factory()
    router = FederatedRouter(
        session_factory=session_factory,
        token_crypto=crypto,
        connector_registry=default_registry(),
    )
    selector = Selector(session_factory=session_factory)

    agent = CentralAgent(
        config=AgentConfig(model=settings.anthropic_model),
        router=router,
        selector=selector,
        session_factory=session_factory,
        anthropic_api_key=settings.anthropic_api_key,
        workspace_domain=settings.workspace_domain,
    )

    result = await agent.ask(question=question, asking_user=user.email)

    # Log the query.
    qlog = QueryLog(
        user_email=user.email,
        query_text=question,
        selected_users=[],
        selected_sources=[],
        answer=result.answer,
        latency_ms=result.latency_ms,
        tokens_used=result.tokens_used,
        cost_usd=result.cost_usd,
    )
    db.add(qlog)

    return render(
        request,
        "answer.html",
        user=user,
        workspace_domain=settings.workspace_domain,
        answer=result.answer,
        citations=result.citations,
        target_count=result.target_count,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
    )
