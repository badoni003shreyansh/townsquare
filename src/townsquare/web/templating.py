"""Jinja templating helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from townsquare import __version__

TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def render(request: Request, template_name: str, **context: Any) -> HTMLResponse:
    """Render a Jinja template with version + the request injected."""
    return templates.TemplateResponse(
        request,
        template_name,
        {"version": __version__, **context},
    )
