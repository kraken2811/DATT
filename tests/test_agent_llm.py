"""Unit tests for resilient LLM client: timeout, retry, fallback, and failure behaviors."""

import pytest
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage, HumanMessage

from src.agent.llm import LLMUnavailableException, ResilientChatModel


class FailingModel:
    def __init__(self, failure_type: str, succeed_after: int = 999):
        self.failure_type = failure_type
        self.succeed_after = succeed_after
        self.calls = 0

    def invoke(self, messages, **kwargs):
        self.calls += 1
        if self.calls > self.succeed_after:
            return AIMessage(content="Success after retry")

        if self.failure_type == "timeout":
            raise TimeoutError("Request timed out after 30.0s")
        elif self.failure_type == "rate_limit":
            raise RuntimeError("Rate limit exceeded: 429 Too Many Requests")
        elif self.failure_type == "unavailable":
            raise ConnectionError("503 Service Unavailable: Provider down")
        elif self.failure_type == "auth":
            raise PermissionError("401 Unauthorized: Invalid API key")
        else:
            raise RuntimeError(f"Error: {self.failure_type}")


def test_primary_ok():
    """Verify primary model succeeds cleanly on normal execution."""
    primary = MagicMock()
    primary.invoke.return_value = AIMessage(content="Primary succeeded")

    model = ResilientChatModel(primary_model=primary, timeout_seconds=5.0, max_retries=2)
    resp = model.invoke([HumanMessage(content="Hello")])

    assert resp.content == "Primary succeeded"
    assert primary.invoke.call_count == 1


def test_primary_timeout_with_retry_success():
    """Verify primary model retries on timeout and succeeds."""
    primary = FailingModel(failure_type="timeout", succeed_after=2)
    model = ResilientChatModel(primary_model=primary, max_retries=3, backoff_base_sec=0.01)

    resp = model.invoke([HumanMessage(content="Hello")])
    assert resp.content == "Success after retry"
    assert primary.calls == 3  # Failed twice, succeeded on 3rd


def test_primary_rate_limited_with_retry_success():
    """Verify primary model handles 429 rate limit with exponential backoff and succeeds."""
    primary = FailingModel(failure_type="rate_limit", succeed_after=1)
    model = ResilientChatModel(primary_model=primary, max_retries=2, backoff_base_sec=0.01)

    resp = model.invoke([HumanMessage(content="Hello")])
    assert resp.content == "Success after retry"
    assert primary.calls == 2


def test_primary_unavailable_with_fallback_ok():
    """Verify fallback model is triggered when primary is unavailable (503)."""
    primary = FailingModel(failure_type="unavailable", succeed_after=999)
    fallback = MagicMock()
    fallback.invoke.return_value = AIMessage(content="Fallback response")

    model = ResilientChatModel(
        primary_model=primary,
        fallback_model=fallback,
        max_retries=1,
        backoff_base_sec=0.01,
    )
    resp = model.invoke([HumanMessage(content="Hello")])

    assert resp.content == "Fallback response"
    assert fallback.invoke.call_count == 1


def test_primary_fail_no_fallback():
    """Verify structured LLMUnavailableException is raised when primary fails and no fallback configured."""
    primary = FailingModel(failure_type="unavailable", succeed_after=999)
    model = ResilientChatModel(
        primary_model=primary,
        fallback_model=None,
        max_retries=1,
        backoff_base_sec=0.01,
    )

    with pytest.raises(LLMUnavailableException) as exc_info:
        model.invoke([HumanMessage(content="Hello")])

    assert exc_info.value.reason == "primary_failed_no_fallback"


def test_max_retries_exceeded():
    """Verify max retries is bounded and terminates without infinite loop."""
    primary = FailingModel(failure_type="timeout", succeed_after=999)
    max_retries = 2
    model = ResilientChatModel(
        primary_model=primary,
        fallback_model=None,
        max_retries=max_retries,
        backoff_base_sec=0.01,
    )

    with pytest.raises(LLMUnavailableException):
        model.invoke([HumanMessage(content="Hello")])

    assert primary.calls == max_retries + 1  # 1 initial + 2 retries = 3 calls total


def test_authentication_error_not_retried():
    """Verify 401 authentication errors are not wastefully retried."""
    primary = FailingModel(failure_type="auth", succeed_after=999)
    model = ResilientChatModel(
        primary_model=primary,
        fallback_model=None,
        max_retries=3,
        backoff_base_sec=0.01,
    )

    with pytest.raises(LLMUnavailableException):
        model.invoke([HumanMessage(content="Hello")])

    assert primary.calls == 1  # Exactly 1 call, zero retries on auth failure
