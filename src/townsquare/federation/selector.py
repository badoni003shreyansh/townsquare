"""Selector — decides which (user, source) targets to fan a query to.

v0.1: select all active users in the configured domain × every source
each user has connected. Naive but works for small companies (<100
employees) and safe (every authorised query reaches every authorised
source). v0.2 will refine with calendar/channel/sharing-graph heuristics.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from townsquare.db.models import Connection, User
from townsquare.federation.router import FanoutTarget


class Selector:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    async def select(
        self,
        query: str,
        asking_user: str,
        explicit_users: list[str] | None = None,
        explicit_sources: list[str] | None = None,
    ) -> list[FanoutTarget]:
        targets: list[FanoutTarget] = []
        with self._session_factory() as session:
            user_filter = [User.is_active.is_(True)]
            if explicit_users:
                user_filter.append(User.email.in_(explicit_users))
            users = session.execute(select(User).where(*user_filter)).scalars().all()

            user_emails = [u.email for u in users]
            if not user_emails:
                return []

            conn_filter = [
                Connection.is_active.is_(True),
                Connection.user_email.in_(user_emails),
            ]
            if explicit_sources:
                conn_filter.append(Connection.source.in_(explicit_sources))

            conns = session.execute(select(Connection).where(*conn_filter)).scalars().all()
            for c in conns:
                targets.append(FanoutTarget(user_email=c.user_email, source=c.source))

        return targets
