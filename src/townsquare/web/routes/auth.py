"""Auth routes — Google Workspace SSO login + callback + logout."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from townsquare.auth.crypto import TokenCrypto
from townsquare.auth.google_sso import (
    DomainRestrictionError,
    GoogleWorkspaceSSO,
    OAuthError,
)
from townsquare.auth.users import store_google_connections, upsert_user_from_claims
from townsquare.db.models import QueryLog
from townsquare.web.deps import get_db, get_sso, get_token_crypto

router = APIRouter(tags=["auth"])


@router.get("/login")
async def login_page(request: Request) -> RedirectResponse:
    """Redirect to /auth/google/login. Future: render a styled page."""
    return RedirectResponse("/auth/google/login")


@router.get("/auth/google/login")
async def google_login(request: Request, sso: GoogleWorkspaceSSO = Depends(get_sso)):
    """Begin the Google OAuth flow."""
    request.session["oauth_nonce"] = secrets.token_urlsafe(16)
    redirect_uri = str(request.url_for("google_callback"))
    return await sso.client.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    sso: GoogleWorkspaceSSO = Depends(get_sso),
    crypto: TokenCrypto = Depends(get_token_crypto),
    db: Session = Depends(get_db),
):
    """Handle the OAuth callback: verify ID token, enforce domain, provision user."""
    try:
        token = await sso.client.authorize_access_token(request)
    except OAuthError as e:
        raise HTTPException(status_code=400, detail=f"oauth error: {e.error}") from e

    id_token_payload = token.get("userinfo") or {}
    if not id_token_payload:
        # Defence-in-depth: fall back to userinfo endpoint
        access_token = token.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="no id_token or access_token returned")
        claims = await sso.fetch_userinfo(access_token)
    else:
        claims = sso.claims_from_id_token(id_token_payload)

    try:
        sso.verify_domain(claims)
    except DomainRestrictionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    user = upsert_user_from_claims(db, claims)

    # Store the per-source OAuth connections so federation can use them.
    granted = (token.get("scope") or "").split()
    store_google_connections(
        session=db,
        crypto=crypto,
        user_email=user.email,
        token_dict=dict(token),
        granted_scopes=granted,
    )

    request.session.clear()
    request.session["user_email"] = user.email
    request.session["user_name"] = user.name or user.email

    return RedirectResponse("/", status_code=303)


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# Type-only import to avoid circular at import time
def _noop_querylog_import() -> type[QueryLog]:
    return QueryLog
