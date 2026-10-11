"""In-process agent execution: timeout and result validation."""

from __future__ import annotations

import threading

import pytest

from src.agent.base import BaseAgent
from src.core.schemas import AgentResult
from src.validator.forecasting.sandbox import AgentTimeoutError, execute_agent

_FINAL_BP = [{"step": 0, "type": "final", "probability": 0.5, "text": "final"}]


class _OkAgent(BaseAgent):
    def predict(self, ctx):
        return AgentResult(prediction=0.5, reasoning="ok", beliefPath=_FINAL_BP)


class _HangingAgent(BaseAgent):
    def __init__(self) -> None:
        self.release = threading.Event()

    def predict(self, ctx):
        self.release.wait(10)
        return AgentResult(prediction=0.5, reasoning="late", beliefPath=_FINAL_BP)


class _WrongTypeAgent(BaseAgent):
    def predict(self, ctx):
        return {"prediction": 0.5}


class _RaisingAgent(BaseAgent):
    def predict(self, ctx):
        raise ValueError("boom")


def test_returns_result_with_and_without_timeout() -> None:
    assert execute_agent(_OkAgent(), ctx=None).prediction == 0.5
    assert execute_agent(_OkAgent(), ctx=None, timeout_seconds=5).reasoning == "ok"


def test_timeout_raises() -> None:
    agent = _HangingAgent()
    try:
        with pytest.raises(AgentTimeoutError):
            execute_agent(agent, ctx=None, timeout_seconds=0.1)
    finally:
        agent.release.set()


def test_non_agent_result_rejected() -> None:
    with pytest.raises(TypeError, match="expected AgentResult"):
        execute_agent(_WrongTypeAgent(), ctx=None, timeout_seconds=5)


def test_agent_exception_propagates() -> None:
    with pytest.raises(ValueError, match="boom"):
        execute_agent(_RaisingAgent(), ctx=None, timeout_seconds=5)
