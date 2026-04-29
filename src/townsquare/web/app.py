"""FastAPI app factory."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from townsquare import __version__
from townsquare.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="townsquare",
        description="The self-hostable open-source company OS",
        version=__version__,
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="townsquare_session",
        same_site="lax",
        https_only=settings.runtime_env == "prod",
    )

    # Routers — imported lazily to avoid hard dep on optional Google libs
    # at import time when scaffolding without credentials.
    from townsquare.web.routes import auth as auth_routes
    from townsquare.web.routes import connections as conn_routes
    from townsquare.web.routes import connections_oauth as conn_oauth_routes
    from townsquare.web.routes import dashboard as dash_routes
    from townsquare.web.routes import wiki as wiki_routes

    app.include_router(dash_routes.router)
    app.include_router(auth_routes.router)
    app.include_router(conn_routes.router)
    app.include_router(conn_oauth_routes.router)
    app.include_router(wiki_routes.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
