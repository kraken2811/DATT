"""Resilient LLM client with timeout, bounded exponential retries, and fallback support."""

import logging
import time
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel

from src.agent.config import agent_config

logger = logging.getLogger("datt.agent.llm")


class LLMUnavailableException(Exception):
    """Raised when primary and fallback LLM providers are unavailable."""

    def __init__(self, message: str = "LLM service unavailable", reason: str = "provider_error"):
        super().__init__(message)
        self.reason = reason


class ResilientChatModel:
    """Wrapper providing timeouts, exponential backoff retries, and graceful fallback."""

    def __init__(
        self,
        primary_model: Any,
        fallback_model: Any | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        backoff_base_sec: float = 0.5,
    ):
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.timeout_seconds = timeout_seconds or agent_config.timeout_seconds
        self.max_retries = max_retries if max_retries is not None else agent_config.max_retries
        self.backoff_base_sec = backoff_base_sec
        self.tools = []

    def bind_tools(self, tools: list[Any]) -> "ResilientChatModel":
        """Bind tools to both primary and fallback models."""
        self.tools = tools
        if hasattr(self.primary_model, "bind_tools"):
            self.primary_model = self.primary_model.bind_tools(tools)
        if self.fallback_model and hasattr(self.fallback_model, "bind_tools"):
            self.fallback_model = self.fallback_model.bind_tools(tools)
        return self

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()
        return "auth" in msg or "401" in msg or "invalid api key" in msg or "permission" in msg or "unauthorized" in msg or "auth" in exc_type

    @staticmethod
    def _is_retriable_error(exc: Exception) -> bool:
        if ResilientChatModel._is_auth_error(exc):
            return False
        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()
        retriable_keywords = [
            "timeout", "rate", "429", "500", "502", "503", "504",
            "connection", "unavailable", "overloaded", "retry", "econnreset"
        ]
        return any(k in msg or k in exc_type for k in retriable_keywords)

    def _invoke_with_retry(self, model: Any, messages: list[BaseMessage]) -> AIMessage:
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                # If model supports request_timeout kwarg
                if hasattr(model, "request_timeout"):
                    return model.invoke(messages, timeout=self.timeout_seconds)
                return model.invoke(messages)
            except Exception as exc:
                last_exception = exc
                if self._is_auth_error(exc):
                    logger.error("Authentication error encountered; will not retry: %s", exc)
                    raise

                if attempt < self.max_retries and self._is_retriable_error(exc):
                    delay = self.backoff_base_sec * (2 ** attempt)
                    logger.warning(
                        "LLM call failed (attempt %d/%d): %s. Retrying in %.2fs...",
                        attempt + 1, self.max_retries, exc, delay
                    )
                    time.sleep(delay)
                else:
                    break

        raise last_exception or LLMUnavailableException("Max retries exceeded")

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        """Invoke LLM with primary model, bounded retries, and optional fallback."""
        try:
            return self._invoke_with_retry(self.primary_model, messages)
        except Exception as primary_exc:
            logger.warning("Primary LLM provider failed: %s", primary_exc)

            if self.fallback_model is not None:
                logger.info("Switching to configured fallback LLM provider...")
                try:
                    return self._invoke_with_retry(self.fallback_model, messages)
                except Exception as fallback_exc:
                    logger.error("Fallback LLM provider also failed: %s", fallback_exc)
                    raise LLMUnavailableException(
                        f"Both primary and fallback LLMs failed: primary ({primary_exc}), fallback ({fallback_exc})",
                        reason="all_providers_failed"
                    ) from fallback_exc

            # No fallback configured
            raise LLMUnavailableException(
                f"Primary LLM failed and no fallback available: {primary_exc}",
                reason="primary_failed_no_fallback"
            ) from primary_exc


def create_raw_model(provider: str, model_name: str, temperature: float) -> Any:
    """Instantiate raw provider chat model."""
    prov = (provider or "mock").lower()
    if prov == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=agent_config.openai_api_key,
            request_timeout=agent_config.timeout_seconds,
        )
    elif prov == "google_genai":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=agent_config.gemini_api_key,
            request_timeout=agent_config.timeout_seconds,
        )
    else:
        from src.agent.nodes import MockChatModel
        return MockChatModel()


def get_configured_llm() -> ResilientChatModel:
    """Build the resilient LLM chain with configured primary and optional fallback."""
    primary = create_raw_model(
        provider=agent_config.llm_provider,
        model_name=agent_config.model_name,
        temperature=agent_config.temperature,
    )

    fallback = None
    if agent_config.fallback_provider and agent_config.fallback_model:
        fallback = create_raw_model(
            provider=agent_config.fallback_provider,
            model_name=agent_config.fallback_model,
            temperature=agent_config.temperature,
        )

    return ResilientChatModel(
        primary_model=primary,
        fallback_model=fallback,
        timeout_seconds=agent_config.timeout_seconds,
        max_retries=agent_config.max_retries,
    )
