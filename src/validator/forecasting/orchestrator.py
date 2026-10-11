"""Validator Orchestrator — the main execution loop.

Receives an event, runs agents through the gateway, assembles traces, stores them.
This is the top-level coordination point for the entire prediction cycle.

Agents always run in-process. Two provider paths share the same trace shape:

- signed (a `LocalProxyState` is supplied — production): provider calls go
  through the validator-local signing proxy, which signs with the validator
  hotkey and bills the registered miner. The orchestrator drains the proxy's
  per-run log to assemble the trace.
- local (no proxy state — dev/tests): agents call providers through the
  orchestrator's own `ProviderGateway`. The call log is `self._gateway.call_log`.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from src.agent.base import BaseAgent
from src.agent.context import ForecastingContext
from src.core.config import AppConfig
from src.core.events import Event
from src.core.schemas import (
    EvidenceDigest,
    ExecutionContext,
    ProviderCall,
    SandboxEnvironment,
)
from src.gateway.gateway import ProviderGateway
from src.gateway.providers.base import BaseProvider
from src.storage.store import TraceStore
from src.validator.forecasting.polymarket_baseline import fetch_polymarket_baseline
from src.validator.forecasting.sandbox import execute_agent
from src.validator.forecasting.trace_assembler import assemble_trace

logger = logging.getLogger("forecasting.orchestrator")


class Orchestrator:
    def __init__(
        self,
        config: AppConfig,
        store: TraceStore,
        providers: list[BaseProvider],
        local_proxy_state: Optional["object"] = None,
        track: str = "MAIN",
    ):
        """Build the orchestrator.

        Args:
            config: Loaded `AppConfig`.
            store: Trace persistence backend.
            providers: Provider adapters used when no proxy state is given.
                With a proxy state these are unused — the proxy talks to the
                central gateway, which holds the real adapters.
            local_proxy_state: A `LocalProxyState` from
                `src.gateway.local_proxy`. When set, every provider call is
                signed and attributed via `register_run` / `pop_calls`.
            track: Track name used to register every run with the proxy.
                Mirrors Numinous's track-based allowlist concept; v1 hardcodes
                to "MAIN" but real subnet configs may dispatch on event class.
        """
        self._config = config
        self._store = store
        self._gateway = ProviderGateway()
        for p in providers:
            self._gateway.register_provider(p)
        self._local_proxy_state = local_proxy_state
        self._track = track

    @property
    def validator_id(self) -> UUID:
        return self._config.validator.validator_id

    def run_agent(
        self,
        event: Event,
        agent: BaseAgent,
        *,
        miner_hotkey: str | None = None,
    ) -> EvidenceDigest:
        """Execute a single agent on a single event and return the sealed trace.

        The agent is a black box — it returns AgentResult (probability + reasoning).
        The validator independently records all gateway calls and assembles
        the complete structured trace.
        """
        execution_id = uuid4()
        proxy = self._local_proxy_state
        timeout_seconds = float(self._config.validator.sandbox_timeout_seconds)

        # Baseline metadata for scoring: pull the latest market signal up-front
        # in a validator-controlled lookup, independent of agent behavior.
        market_baseline = self._collect_market_baseline(event)

        if proxy is not None:
            from src.gateway.local_proxy import ProxyRunGateway

            proxy.register_run(execution_id, self._track, miner_hotkey=miner_hotkey)
            gateway = ProxyRunGateway(proxy, execution_id)
        else:
            # Reset so a stale call log from a previous run does not bleed
            # into this trace.
            self._gateway.reset()
            gateway = self._gateway

        ts_start = datetime.now(timezone.utc)
        t0 = time.monotonic()

        ctx = ForecastingContext(event=event, gateway=gateway)
        try:
            agent_result = execute_agent(agent, ctx, timeout_seconds)
        except Exception:
            if proxy is not None:
                # Drain to free the proxy's per-run state.
                try:
                    proxy.pop_calls(execution_id)
                except Exception:  # noqa: BLE001
                    pass
            raise

        t1 = time.monotonic()
        ts_end = datetime.now(timezone.utc)
        duration_ms = int((t1 - t0) * 1000)
        duration_s = duration_ms / 1000.0

        logger.info(
            "Agent execution finished: execution_id=%s agent_id=%s agent_version=%s "
            "signed=%s duration_ms=%s",
            execution_id,
            agent.agent_id,
            agent.agent_version,
            proxy is not None,
            duration_ms,
        )
        print(
            f"[almanac] agent execution finished: signed={proxy is not None} "
            f"duration={duration_s:.2f}s ({duration_ms} ms) "
            f"agent={agent.agent_id!r} execution_id={execution_id}",
            flush=True,
        )

        sandbox_env = SandboxEnvironment.IN_PROCESS

        # v1: the validator-fetched market baseline lives in the (hash-sealed)
        # execution context as a single YES price, not in agent-writable metadata.
        market_price = (
            market_baseline.get("yes_price") if isinstance(market_baseline, dict) else None
        )

        exec_ctx = ExecutionContext(
            execution_id=execution_id,
            agent_id=agent.agent_id,
            agent_version=agent.agent_version,
            event_id=event.event_id,
            validator_id=self.validator_id,
            timestamp_start=ts_start,
            timestamp_end=ts_end,
            execution_duration_ms=duration_ms,
            sandbox_environment=sandbox_env,
            market_price_at_prediction=market_price,
        )

        if proxy is not None:
            provider_calls: list[ProviderCall] = proxy.pop_calls(execution_id)
        else:
            provider_calls = self._gateway.call_log
        agent_steps = ctx.reasoning_chain or None

        digest = assemble_trace(
            execution_context=exec_ctx,
            event=event,
            provider_calls=provider_calls,
            agent_result=agent_result,
            agent_reasoning_steps=agent_steps,
        )

        self._store.save_trace(digest)
        return digest

    def run_all_agents(
        self,
        event: Event,
        agents: list[BaseAgent],
        *,
        miner_hotkey: str | None = None,
    ) -> list[EvidenceDigest]:
        """Run multiple agents on the same event, returning all traces.

        `miner_hotkey` is forwarded to `run_agent` so the local proxy has a
        billing/attribution identity on the signed path. Dropping it here
        would make every provider call 400 there, since the signed identity
        comes solely from run registration.
        """
        return [
            self.run_agent(event, agent, miner_hotkey=miner_hotkey)
            for agent in agents
        ]

    def _collect_market_baseline(self, event: Event) -> dict[str, Any] | None:
        """Fetch latest YES/NO baseline prices from direct Polymarket lookup."""
        try:
            return fetch_polymarket_baseline(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "market baseline fetch failed for event=%s source_id=%s: %s",
                event.event_id,
                event.source_id,
                exc,
            )
            return None
