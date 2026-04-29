"""Connector registry — single source of truth for which sources are wired."""

from __future__ import annotations

from townsquare.connectors.base import Connector
from townsquare.connectors.calendar import CalendarConnector
from townsquare.connectors.drive import DriveConnector
from townsquare.connectors.gmail import GmailConnector


def default_registry() -> dict[str, Connector]:
    return {
        "gmail": GmailConnector(),
        "drive": DriveConnector(),
        "calendar": CalendarConnector(),
    }
