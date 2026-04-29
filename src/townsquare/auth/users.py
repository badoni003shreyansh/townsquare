"""User auto-provisioning + per-user OAuth-token storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from townsquare.auth.crypto import TokenCrypto
from townsquare.auth.google_sso import GoogleUserClaims
from townsquare.db.models import Connection, User


def upsert_user_from_claims(session: Session, claims: GoogleUserClaims) -> User:
    """Find or create a User row from verified Google claims.

    Updates `last_seen_at` and `name` on every login.
    """
    user = session.get(User, claims.email)
    now = datetime.utcnow()
    if user is None:
        user = User(
            email=claims.email,
            domain=claims.domain,
            name=claims.name,
            role="member",
            is_active=True,
            created_at=now,
            last_seen_at=now,
        )
        session.add(user)
    else:
        user.last_seen_at = now
        if claims.name and not user.name:
            user.name = claims.name
        user.is_active = True
    session.flush()
    return user


def store_google_connections(
    session: Session,
    crypto: TokenCrypto,
    user_email: str,
    token_dict: dict[str, Any],
    granted_scopes: list[str],
) -> list[Connection]:
    """Store the OAuth tokens granted at SSO time for each Google source.

    Because Workspace SSO grants Gmail/Drive/Calendar scopes in one
    consent screen, a single Authlib token blob covers all three. We
    create one Connection row per source so the federation router can
    look them up by source.
    """
    access_token = token_dict.get("access_token")
    refresh_token = token_dict.get("refresh_token")
    if not access_token:
        raise ValueError("OAuth token blob is missing access_token")

    encrypted_access = crypto.encrypt(access_token)
    encrypted_refresh = crypto.encrypt(refresh_token) if refresh_token else None

    sources_to_create = []
    for source, scope in (
        ("gmail", "https://www.googleapis.com/auth/gmail.readonly"),
        ("drive", "https://www.googleapis.com/auth/drive.readonly"),
        ("calendar", "https://www.googleapis.com/auth/calendar.readonly"),
    ):
        if scope in granted_scopes:
            sources_to_create.append(source)

    now = datetime.utcnow()
    created: list[Connection] = []
    for source in sources_to_create:
        existing = session.execute(
            select(Connection).where(
                Connection.user_email == user_email,
                Connection.source == source,
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.oauth_token_encrypted = encrypted_access
            existing.refresh_token_encrypted = encrypted_refresh
            existing.granted_scopes = list(granted_scopes)
            existing.last_refreshed_at = now
            existing.is_active = True
            created.append(existing)
        else:
            conn = Connection(
                user_email=user_email,
                source=source,
                oauth_token_encrypted=encrypted_access,
                refresh_token_encrypted=encrypted_refresh,
                granted_scopes=list(granted_scopes),
                connected_at=now,
                last_refreshed_at=now,
                is_active=True,
            )
            session.add(conn)
            created.append(conn)

    session.flush()
    return created


def get_user_token(
    session: Session, crypto: TokenCrypto, user_email: str, source: str
) -> str | None:
    """Decrypt and return the access token for a user/source pair."""
    conn = session.execute(
        select(Connection).where(
            Connection.user_email == user_email,
            Connection.source == source,
            Connection.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if conn is None:
        return None
    return crypto.decrypt(conn.oauth_token_encrypted)


def upsert_connection(
    session: Session,
    crypto: TokenCrypto,
    user_email: str,
    source: str,
    access_token: str,
    refresh_token: str | None = None,
    granted_scopes: list[str] | None = None,
) -> Connection:
    """Generic per-source connection upsert (Slack, GitHub, Notion, etc.).

    Use this from non-Google connector OAuth/PAT flows. Google connections
    are created in batch by ``store_google_connections`` because the
    Workspace SSO grants Gmail/Drive/Calendar in one consent.
    """
    if not access_token:
        raise ValueError(f"{source}: access_token is required")

    encrypted_access = crypto.encrypt(access_token)
    encrypted_refresh = crypto.encrypt(refresh_token) if refresh_token else None
    now = datetime.utcnow()

    existing = session.execute(
        select(Connection).where(
            Connection.user_email == user_email,
            Connection.source == source,
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.oauth_token_encrypted = encrypted_access
        existing.refresh_token_encrypted = encrypted_refresh
        if granted_scopes is not None:
            existing.granted_scopes = list(granted_scopes)
        existing.last_refreshed_at = now
        existing.is_active = True
        session.flush()
        return existing

    conn = Connection(
        user_email=user_email,
        source=source,
        oauth_token_encrypted=encrypted_access,
        refresh_token_encrypted=encrypted_refresh,
        granted_scopes=list(granted_scopes or []),
        connected_at=now,
        last_refreshed_at=now,
        is_active=True,
    )
    session.add(conn)
    session.flush()
    return conn


def deactivate_connection(session: Session, user_email: str, source: str) -> bool:
    """Mark a single user's connection inactive. Returns True if a row changed."""
    conn = session.execute(
        select(Connection).where(
            Connection.user_email == user_email,
            Connection.source == source,
        )
    ).scalar_one_or_none()
    if conn is None:
        return False
    conn.is_active = False
    session.flush()
    return True
