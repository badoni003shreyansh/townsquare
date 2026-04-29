"""Central agent runner — Anthropic Claude with tool use over townsquare's
federation router and shared brain.

Architecture: this is *not* a per-user-targeted agent loop. The agent
gets a small, capability-shaped tool surface:

  - ``ask_company`` — the headline tool. Federates a sub-query across
    the whole company through the FederatedRouter. The agent uses this
    when it needs information that lives in users' personal sources.
  - ``read_wiki`` / ``write_wiki`` — the shared org brain.
  - ``read_crm`` — lightweight CRM lookup.

The agent never sees individual users' tokens; the router does the
fanout under each user's tokens internally. Privacy is preserved.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import Anthropic

from townsquare.agent.tools import (
    TOOL_DEFINITIONS,
    handle_ask_company,
    handle_read_wiki,
    handle_write_wiki,
)
from townsquare.federation.router import FederatedRouter
from townsquare.federation.selector import Selector

DEFAULT_SYSTEM_PROMPT = """You are townsquare, a company OS agent.

You help employees of {workspace_domain} find information across their colleagues' \
Gmail, Drive, and Calendar — with privacy preserved at the source. You also \
maintain a shared org wiki.

You have a small set of tools:

- ask_company: federates a sub-question across the whole company (every user's \
  Gmail/Drive/Calendar). Use this for questions about who's working on what, \
  recent project status, customer history, meeting summaries.
- read_wiki: read a shared wiki page by slug.
- write_wiki: create or update a wiki page (use only when explicitly asked).

Rules:
- ALWAYS cite which user contributed which fact. Format: "(via <user_email> · <source>)".
- If you don't have enough context, ask the company before guessing.
- Never invent data. If your tools return nothing, say so honestly.
- Keep answers concise. The user is busy.
"""


@dataclass
class AgentConfig:
    model: str = "claude-sonnet-4-6"
    max_steps: int = 6
    max_tokens: int = 4096


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    target_count: int = 0
    latency_ms: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0


class CentralAgent:
    """Wraps Anthropic Claude with townsquare's tool surface."""

    def __init__(
        self,
        config: AgentConfig,
        router: FederatedRouter,
        selector: Selector,
        session_factory: Callable[[], Any],
        anthropic_api_key: str,
        workspace_domain: str,
    ) -> None:
        self.config = config
        self._router = router
        self._selector = selector
        self._session_factory = session_factory
        self._client = Anthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self._workspace_domain = workspace_domain

    async def ask(self, question: str, asking_user: str) -> AgentResult:
        if self._client is None:
            return AgentResult(
                answer=(
                    "Anthropic API key is not configured. Set ANTHROPIC_API_KEY in your "
                    ".env to enable the agent. (You can still try connectors directly.)"
                ),
                target_count=0,
                latency_ms=0,
            )

        start = time.monotonic()
        system = DEFAULT_SYSTEM_PROMPT.format(workspace_domain=self._workspace_domain)
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]

        all_citations: list[dict[str, Any]] = []
        total_targets = 0
        total_input_tokens = 0
        total_output_tokens = 0
        final_text: str = ""

        for _step in range(self.config.max_steps):
            response = self._client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system,
                tools=TOOL_DEFINITIONS,
                messages=messages,
            )
            usage = response.usage
            total_input_tokens += usage.input_tokens
            total_output_tokens += usage.output_tokens

            # Collect any text content for the eventual answer.
            text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]

            if not tool_uses:
                final_text = "\n".join(text_blocks).strip() or "(no answer produced)"
                break

            # Append assistant message + run all requested tools.
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tu in tool_uses:
                name = tu.name
                args = tu.input or {}
                try:
                    if name == "ask_company":
                        result = await handle_ask_company(
                            args=args,
                            router=self._router,
                            selector=self._selector,
                            asking_user=asking_user,
                        )
                        # Track citations + targets across all ask_company calls.
                        for cit in result.get("citations", []):
                            all_citations.append(cit)
                        total_targets += result.get("target_count", 0)
                    elif name == "read_wiki":
                        result = handle_read_wiki(args=args, session_factory=self._session_factory)
                    elif name == "write_wiki":
                        result = handle_write_wiki(
                            args=args,
                            session_factory=self._session_factory,
                            actor_email=asking_user,
                        )
                    else:
                        result = {"error": f"unknown tool '{name}'"}
                except Exception as e:
                    result = {"error": f"tool failed: {e}"}

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": json.dumps(result, default=str),
                    }
                )

            messages.append({"role": "user", "content": tool_results})
        else:
            final_text = "(stopped: max_steps reached)"

        latency_ms = (time.monotonic() - start) * 1000

        # Cost — Sonnet rough card: $3 / MTok input, $15 / MTok output.
        cost_usd = (total_input_tokens * 3 + total_output_tokens * 15) / 1_000_000

        return AgentResult(
            answer=final_text,
            citations=all_citations,
            target_count=total_targets,
            latency_ms=latency_ms,
            tokens_used=total_input_tokens + total_output_tokens,
            cost_usd=cost_usd,
        )
