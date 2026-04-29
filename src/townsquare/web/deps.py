"""FastAPI dependency-injection helpers."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from townsquare.auth.crypto import TokenCrypto
from townsquare.auth.google_sso import GoogleWorkspaceSSO
from townsquare.db import get_session_factory
from townsquare.db.models import User
from townsquare.settings import Settings
from townsquare.settings import get_settings as _get_settings


@lru_cache
def get_cached_settings() -> Settings:
    return _get_settings()


@lru_cache
def get_token_crypto() -> TokenCrypto:
    return TokenCrypto(get_cached_settings().fernet_key)


@lru_cache
def get_sso() -> GoogleWorkspaceSSO:
    s = get_cached_settings()
    return GoogleWorkspaceSSO(
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        workspace_domain=s.workspace_domain,
        scopes=s.google_oauth_scopes,
    )


def get_db() -> Iterator[Session]:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    email = request.session.get("user_email")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="not authenticated",
            headers={"Location": "/login"},
        )
    user = db.get(User, email)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="user not found or inactive",
        )
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    email = request.session.get("user_email")
    if not email:
        return None
    user = db.get(User, email)
    if user is None or not user.is_active:
        return None
    return user
