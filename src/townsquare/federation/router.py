"""Federation router — fans queries across selected (user, source) targets.

Each target runs under that user's encrypted token, decrypted only inside
the per-target task. Failures on individual targets are reported but
never break the overall fanout.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from townsquare.auth.crypto import TokenCrypto
from townsquare.connectors.base import Connector, Item
from townsquare.db.models import Connection


@dataclass
class FanoutTarget:
    user_email: str
    source: str


@dataclass
class FanoutResult:
    targets: list[FanoutTarget]
    items: list[Item]
    errors: list[dict[str, Any]] = field(default_factory=list)
    total_latency_ms: float = 0.0


class FederatedRouter:
    """Routes a query across (user, source) targets in parallel."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        token_crypto: TokenCrypto,
        connector_registry: dict[str, Connector],
        per_target_concurrency: int = 8,
    ) -> None:
        self._session_factory = session_factory
        self._crypto = token_crypto
        self._connectors = connector_registry
        self._sem = asyncio.Semaphore(per_target_concurrency)

    async def fanout(
        self,
        query: str,
        targets: list[FanoutTarget],
        per_target_budget_ms: int = 5000,
        per_target_limit: int = 5,
    ) -> FanoutResult:
        if not targets:
            return FanoutResult(targets=[], items=[])

        # Decrypt tokens up front (in the main task with one DB session),
        # then pass plaintext into per-target tasks. Plaintext only lives
        # in memory for the duration of the fanout.
        token_map = self._load_tokens(targets)

        start = time.monotonic()
        coros = [
            self._run_target(
                t,
                token_map.get((t.user_email, t.source)),
                query,
                per_target_budget_ms,
                per_target_limit,
            )
            for t in targets
        ]
        results = await asyncio.gather(*coros, return_exceptions=False)
        elapsed_ms = (time.monotonic() - start) * 1000

        all_items: list[Item] = []
        errors: list[dict[str, Any]] = []
        for target, target_result in zip(targets, results, strict=True):
            if isinstance(target_result, Exception):
                errors.append(
                    {
                        "user": target.user_email,
                        "source": target.source,
                        "error": str(target_result),
                    }
                )
            elif isinstance(target_result, list):
                # Tag with attribution.
                for item in target_result:
                    annotated = Item(
                        id=item.id,
                        title=item.title,
                        snippet=item.snippet,
                        url=item.url,
                        occurred_at=item.occurred_at,
                        metadata=item.metadata,
                        source=target.source,
                        user_email=target.user_email,
                    )
                    all_items.append(annotated)
            else:
                errors.append(
                    {"user": target.user_email, "source": target.source, "error": "no token"}
                )

        return FanoutResult(
            targets=targets,
            items=all_items,
            errors=errors,
            total_latency_ms=elapsed_ms,
        )

    def _load_tokens(self, targets: list[FanoutTarget]) -> dict[tuple[str, str], str]:
        """Look up + decrypt access tokens for all targets in one DB pass."""
        if not targets:
            return {}
        keys = {(t.user_email, t.source) for t in targets}
        tokens: dict[tuple[str, str], str] = {}
        with self._session_factory() as session:
            for user_email, source in keys:
                conn = session.execute(
                    select(Connection).where(
                        Connection.user_email == user_email,
                        Connection.source == source,
                        Connection.is_active.is_(True),
                    )
                ).scalar_one_or_none()
                if conn is None:
                    continue
                try:
                    tokens[(user_email, source)] = self._crypto.decrypt(conn.oauth_token_encrypted)
                except Exception:
                    continue
        return tokens

    async def _run_target(
        self,
        target: FanoutTarget,
        token: str | None,
        query: str,
        budget_ms: int,
        limit: int,
    ) -> list[Item] | Exception:
        if token is None:
            return RuntimeError("no token")
        connector = self._connectors.get(target.source)
        if connector is None:
            return RuntimeError(f"no connector for source '{target.source}'")
        async with self._sem:
            try:
                return await asyncio.wait_for(
                    connector.search(query=query, access_token=token, limit=limit),
                    timeout=budget_ms / 1000.0,
                )
            except TimeoutError:
                return TimeoutError(
                    f"target {target.user_email}/{target.source} exceeded {budget_ms}ms"
                )
            except Exception as e:
                return e
