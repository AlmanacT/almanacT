"""Agent execution.

Agents run in-process: `predict` executes in a worker thread of the validator
process. There is NO isolation — agent code shares the validator's memory,
filesystem, network, and loaded hotkey. Only run agents you trust.

Two guards remain:

- a wall-clock timeout (`sandbox_timeout_seconds`). A timed-out agent's thread
  cannot be killed; it is abandoned as a daemon thread and its result ignored.
- the returned `AgentResult` is round-tripped through JSON validation so size
  caps and belief-path rules apply exactly as they do for submitted payloads.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from src.agent.base import BaseAgent
from src.agent.context import ForecastingContext
from src.core.schemas import AgentResult


class AgentTimeoutError(RuntimeError):
    """The agent did not return within the configured timeout."""


def execute_agent(
    agent: BaseAgent,
    ctx: ForecastingContext,
    timeout_seconds: Optional[float] = None,
) -> AgentResult:
    """Run an agent's prediction logic and return its validated result.

    Args:
        agent: The agent instance to execute.
        ctx: The `ForecastingContext` handed to `agent.predict`.
        timeout_seconds: Wall-clock limit. `None` runs inline with no limit.

    Returns:
        The agent's `AgentResult`. Exceptions raised by the agent propagate.
    """
    if timeout_seconds is None:
        return _validated(agent.predict(ctx))

    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            outcome["result"] = agent.predict(ctx)
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller thread
            outcome["error"] = exc

    thread = threading.Thread(target=_target, name="almanac-agent", daemon=True)
    thread.start()
    thread.join(timeout_seconds)
    if thread.is_alive():
        raise AgentTimeoutError(f"agent did not finish within {timeout_seconds}s")
    if "error" in outcome:
        raise outcome["error"]
    return _validated(outcome.get("result"))


def _validated(result: Any) -> AgentResult:
    if not isinstance(result, AgentResult):
        raise TypeError(f"agent returned {type(result).__name__}, expected AgentResult")
    return AgentResult.model_validate_json(result.model_dump_json())
