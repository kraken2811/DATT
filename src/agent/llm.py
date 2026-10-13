"""Resilient LLM client with timeout, bounded exponential retries, and fallback support."""

import logging
import os
import time
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from src.agent.config import agent_config

logger = logging.getLogger("datt.agent.llm")


class LLMUnavailableException(Exception):
    """Raised when primary and fallback LLM providers are unavailable."""

    def __init__(self, message: str = "LLM service unavailable", reason: str = "provider_error"):
        super().__init__(message)
        self.reason = reason


class ResilientChatModel:
    """Wrapper providing timeouts, exponential backoff retries, and multi-level graceful fallback."""

    def __init__(
        self,
        primary_model: Any,
        fallback_model: Any | None = None,
        primary_provider: str = "google_genai",
        fallback_provider: str | None = None,
        primary_model_name: str = "gemini-3.8-flash",
        fallback_model_name: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
        backoff_base_sec: float = 0.5,
        cooldown_seconds: float | None = None,
        shared_state: dict[str, Any] | None = None,
        fallback_2_model: Any | None = None,
        fallback_2_provider: str | None = None,
        fallback_2_model_name: str | None = None,
    ):
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.fallback_2_model = fallback_2_model
        self._raw_primary_model = primary_model
        self._raw_fallback_model = fallback_model
        self._raw_fallback_2_model = fallback_2_model
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.fallback_2_provider = fallback_2_provider
        self.primary_model_name = primary_model_name
        self.fallback_model_name = fallback_model_name
        self.fallback_2_model_name = fallback_2_model_name
        self.timeout_seconds = timeout_seconds or agent_config.timeout_seconds
        self.max_retries = max_retries if max_retries is not None else agent_config.max_retries
        self.backoff_base_sec = backoff_base_sec
        self.cooldown_seconds = cooldown_seconds if cooldown_seconds is not None else agent_config.circuit_breaker_cooldown_sec
        self.tools: list[Any] = []
        self._shared_state = shared_state if shared_state is not None else {
            "cooldown_until": 0.0,
            "cooldown_until_fb1": 0.0,
            "cooldown_until_fb2": 0.0,
            "cooldown_reason": None,
            "failover_count": 0,
            "last_provider": None,
            "last_model": None,
            "last_level": 0,
        }

    def bind_tools(self, tools: list[Any]) -> "ResilientChatModel":
        """Bind tools across primary and all fallback models without nesting bindings."""
        if tools:
            bound_primary = (
                self._raw_primary_model.bind_tools(tools)
                if hasattr(self._raw_primary_model, "bind_tools")
                else self._raw_primary_model
            )
            bound_fb1 = (
                self._raw_fallback_model.bind_tools(tools)
                if (self._raw_fallback_model is not None and hasattr(self._raw_fallback_model, "bind_tools"))
                else self._raw_fallback_model
            )
            bound_fb2 = (
                self._raw_fallback_2_model.bind_tools(tools)
                if (self._raw_fallback_2_model is not None and hasattr(self._raw_fallback_2_model, "bind_tools"))
                else self._raw_fallback_2_model
            )
        else:
            bound_primary = self._raw_primary_model
            bound_fb1 = self._raw_fallback_model
            bound_fb2 = self._raw_fallback_2_model

        clone = ResilientChatModel(
            primary_model=bound_primary,
            fallback_model=bound_fb1,
            fallback_2_model=bound_fb2,
            primary_provider=self.primary_provider,
            fallback_provider=self.fallback_provider,
            fallback_2_provider=self.fallback_2_provider,
            primary_model_name=self.primary_model_name,
            fallback_model_name=self.fallback_model_name,
            fallback_2_model_name=self.fallback_2_model_name,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            backoff_base_sec=self.backoff_base_sec,
            cooldown_seconds=self.cooldown_seconds,
            shared_state=self._shared_state,
        )
        clone.tools = tools
        clone._raw_primary_model = self._raw_primary_model
        clone._raw_fallback_model = self._raw_fallback_model
        clone._raw_fallback_2_model = self._raw_fallback_2_model
        return clone

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()
        auth_keywords = [
            "invalid api key", "invalid_api_key", "unauthorized", "401",
            "api key not valid", "permission_denied", "forbidden"
        ]
        # Ensure quota 429 is never misclassified as auth
        if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
            return False
        return any(k in msg or k in exc_type for k in auth_keywords)

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()
        quota_keywords = [
            "resource_exhausted", "quota exceeded", "quota_exceeded",
            "429", "rate_limit_exceeded", "rate limit", "too many requests"
        ]
        return any(k in msg or k in exc_type for k in quota_keywords)

    @staticmethod
    def _is_retriable_error(exc: Exception) -> bool:
        if ResilientChatModel._is_auth_error(exc) or ResilientChatModel._is_quota_error(exc):
            return False
        msg = str(exc).lower()
        exc_type = type(exc).__name__.lower()
        retriable_keywords = [
            "timeout", "timed out", "500", "502", "503", "504",
            "connection", "unavailable", "overloaded", "econnreset",
            "remote disconnected", "reset by peer"
        ]
        return any(k in msg or k in exc_type for k in retriable_keywords)

    def _invoke_with_retry(self, model: Any, messages: list[BaseMessage], provider: str = "") -> AIMessage:
        last_exception = None
        for attempt in range(self.max_retries + 1):
            try:
                if hasattr(model, "request_timeout"):
                    return model.invoke(messages, timeout=self.timeout_seconds)
                return model.invoke(messages)
            except Exception as exc:
                last_exception = exc
                if self._is_auth_error(exc) or self._is_quota_error(exc):
                    # Fail fast immediately without retrying or long sleep
                    raise exc

                if attempt < self.max_retries and self._is_retriable_error(exc):
                    delay = min(self.backoff_base_sec * (2 ** attempt), 2.0)
                    logger.warning(
                        "[%s] Call failed (attempt %d/%d): %s. Retrying in %.2fs...",
                        provider, attempt + 1, self.max_retries, exc, delay
                    )
                    time.sleep(delay)
                else:
                    break

        raise last_exception or LLMUnavailableException("Max retries exceeded")

    def _record_metadata(
        self,
        resp: AIMessage,
        provider: str | None,
        model: str | None,
        latency: float,
        failover: bool,
        reason: str | None = None,
        level: int = 0,
    ) -> None:
        self._shared_state["last_provider"] = provider
        self._shared_state["last_model"] = model
        self._shared_state["last_level"] = level
        if isinstance(resp, AIMessage):
            resp.additional_kwargs["llm_provider"] = provider
            resp.additional_kwargs["llm_model"] = model
            resp.additional_kwargs["llm_latency_sec"] = round(latency, 3)
            resp.additional_kwargs["failover_occurred"] = failover
            resp.additional_kwargs["failover_level"] = level
            if reason:
                resp.additional_kwargs["failover_reason"] = reason

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        """Invoke LLM with multi-tier circuit-breaker cooldown, bounded retries, and cascading failover."""
        now = time.time()
        primary_in_cooldown = now < self._shared_state.get("cooldown_until", 0.0)
        primary_exc: Exception | None = None

        # -------------------------------------------------------------
        # TIER 1: PRIMARY LLM (Gemini)
        # -------------------------------------------------------------
        if not primary_in_cooldown:
            start_time = time.time()
            try:
                resp = self._invoke_with_retry(self.primary_model, messages, provider=self.primary_provider)
                duration = time.time() - start_time
                self._shared_state["cooldown_until"] = 0.0
                self._shared_state["cooldown_reason"] = None
                self._record_metadata(
                    resp,
                    provider=self.primary_provider,
                    model=self.primary_model_name,
                    latency=duration,
                    failover=False,
                    level=0,
                )
                return resp
            except Exception as exc:
                duration = time.time() - start_time
                primary_exc = exc
                logger.warning(
                    "Primary LLM (%s/%s) failed after %.2fs: %s (%s)",
                    self.primary_provider,
                    self.primary_model_name,
                    duration,
                    exc,
                    type(exc).__name__,
                )

                # Authentication error must be reported fail-fast without masking
                if self._is_auth_error(exc):
                    logger.error("Primary LLM authentication/configuration error: %s. Not masking.", exc)
                    raise LLMUnavailableException(
                        f"Primary LLM authentication/configuration error: {exc}. Check API key configuration.",
                        reason="primary_auth_error",
                    ) from exc

                # Engage primary circuit-breaker on 429 quota exhaustion
                if self._is_quota_error(exc):
                    self._shared_state["cooldown_until"] = time.time() + self.cooldown_seconds
                    self._shared_state["cooldown_reason"] = "quota_exhausted_429"
                    logger.info(
                        "Circuit-breaker engaged: Primary LLM placed in cooldown for %.1fs (reason: quota_exhausted_429)",
                        self.cooldown_seconds,
                    )
        else:
            reason = self._shared_state.get("cooldown_reason") or "cooldown_active"
            remaining = round(self._shared_state["cooldown_until"] - now, 1)
            logger.info(
                "Primary LLM (%s/%s) in cooldown for %.1fs (reason: %s); proceeding to fallback",
                self.primary_provider,
                self.primary_model_name,
                remaining,
                reason,
            )
            primary_exc = LLMUnavailableException(f"Primary in cooldown ({reason})")

        # -------------------------------------------------------------
        # TIER 2: FALLBACK LEVEL 1 (Groq GPT-OSS 120B)
        # -------------------------------------------------------------
        fb1_exc: Exception | None = None
        fb1_in_cooldown = now < self._shared_state.get("cooldown_until_fb1", 0.0)

        if self.fallback_model is not None and not fb1_in_cooldown:
            self._shared_state["failover_count"] += 1
            fb1_reason = self._shared_state.get("cooldown_reason") or ("primary_in_cooldown" if primary_in_cooldown else "primary_failed")
            logger.info(
                "Cascading failover -> Tier 2 (Level 1: %s/%s). Reason: %s",
                self.fallback_provider,
                self.fallback_model_name,
                fb1_reason,
            )
            fb1_start = time.time()
            try:
                resp = self._invoke_with_retry(
                    self.fallback_model, messages, provider=self.fallback_provider or "fallback_1"
                )
                fb1_duration = time.time() - fb1_start
                self._shared_state["cooldown_until_fb1"] = 0.0
                self._record_metadata(
                    resp,
                    provider=self.fallback_provider,
                    model=self.fallback_model_name,
                    latency=fb1_duration,
                    failover=True,
                    reason=fb1_reason,
                    level=1,
                )
                return resp
            except Exception as exc:
                fb1_duration = time.time() - fb1_start
                fb1_exc = exc
                logger.warning(
                    "Fallback Level 1 (%s/%s) failed after %.2fs: %s (%s)",
                    self.fallback_provider,
                    self.fallback_model_name,
                    fb1_duration,
                    exc,
                    type(exc).__name__,
                )
                if self._is_quota_error(exc):
                    self._shared_state["cooldown_until_fb1"] = time.time() + self.cooldown_seconds
                    logger.info("Circuit-breaker engaged for Fallback Level 1 (rate limit 429)")
        else:
            fb1_exc = LLMUnavailableException("Fallback Level 1 unavailable or in cooldown")

        # -------------------------------------------------------------
        # TIER 3: FALLBACK LEVEL 2 (Groq Qwen 3.8 27B)
        # -------------------------------------------------------------
        fb2_exc: Exception | None = None
        fb2_in_cooldown = now < self._shared_state.get("cooldown_until_fb2", 0.0)

        if self.fallback_2_model is not None and not fb2_in_cooldown:
            self._shared_state["failover_count"] += 1
            fb2_reason = "level_1_fallback_failed"
            logger.info(
                "Cascading failover -> Tier 3 (Level 2: %s/%s). Reason: %s",
                self.fallback_2_provider,
                self.fallback_2_model_name,
                fb2_reason,
            )
            fb2_start = time.time()
            try:
                resp = self._invoke_with_retry(
                    self.fallback_2_model, messages, provider=self.fallback_2_provider or "fallback_2"
                )
                fb2_duration = time.time() - fb2_start
                self._shared_state["cooldown_until_fb2"] = 0.0
                self._record_metadata(
                    resp,
                    provider=self.fallback_2_provider,
                    model=self.fallback_2_model_name,
                    latency=fb2_duration,
                    failover=True,
                    reason=fb2_reason,
                    level=2,
                )
                return resp
            except Exception as exc:
                fb2_duration = time.time() - fb2_start
                fb2_exc = exc
                logger.error(
                    "Fallback Level 2 (%s/%s) failed after %.2fs: %s (%s)",
                    self.fallback_2_provider,
                    self.fallback_2_model_name,
                    fb2_duration,
                    exc,
                    type(exc).__name__,
                )
                if self._is_quota_error(exc):
                    self._shared_state["cooldown_until_fb2"] = time.time() + self.cooldown_seconds
        else:
            fb2_exc = LLMUnavailableException("Fallback Level 2 unavailable or in cooldown")

        # All providers failed
        raise LLMUnavailableException(
            f"All configured LLM providers failed: Primary ({primary_exc}), "
            f"Fallback 1 ({fb1_exc}), Fallback 2 ({fb2_exc})",
            reason="all_providers_failed",
        )

    def get_status(self) -> dict[str, Any]:
        """Inspect non-sensitive runtime circuit breaker and failover metrics across all tiers."""
        now = time.time()
        p_cd = now < self._shared_state.get("cooldown_until", 0.0)
        fb1_cd = now < self._shared_state.get("cooldown_until_fb1", 0.0)
        fb2_cd = now < self._shared_state.get("cooldown_until_fb2", 0.0)
        rem = max(0.0, round(self._shared_state.get("cooldown_until", 0.0) - now, 1))

        return {
            "primary_provider": self.primary_provider,
            "primary_model": self.primary_model_name,
            "fallback_provider": self.fallback_provider,
            "fallback_model": self.fallback_model_name,
            "fallback_1_provider": self.fallback_provider,
            "fallback_1_model": self.fallback_model_name,
            "fallback_2_provider": self.fallback_2_provider,
            "fallback_2_model": self.fallback_2_model_name,
            "in_cooldown": p_cd,
            "primary_in_cooldown": p_cd,
            "fallback_1_in_cooldown": fb1_cd,
            "fallback_2_in_cooldown": fb2_cd,
            "cooldown_remaining_sec": rem,
            "cooldown_reason": self._shared_state.get("cooldown_reason"),
            "last_used_provider": self._shared_state.get("last_provider"),
            "last_used_model": self._shared_state.get("last_model"),
            "last_used_level": self._shared_state.get("last_level", 0),
            "failover_count": self._shared_state.get("failover_count", 0),
        }


def get_active_provider_info() -> dict[str, Any]:
    """Inspect configured and active runtime LLM provider information without revealing credentials."""
    cfg_provider = (agent_config.llm_provider or "google_genai").lower()
    has_gemini = bool(agent_config.gemini_api_key and agent_config.gemini_api_key.strip())
    has_openai = bool(agent_config.openai_api_key and agent_config.openai_api_key.strip())
    has_groq = bool(agent_config.groq_api_key and agent_config.groq_api_key.strip())

    if cfg_provider == "google_genai":
        actual = "google_genai" if has_gemini else "unavailable (missing GEMINI_API_KEY)"
    elif cfg_provider == "groq":
        actual = "groq" if has_groq else "unavailable (missing GROQ_API_KEY)"
    elif cfg_provider == "openai":
        actual = "openai" if has_openai else "unavailable (missing OPENAI_API_KEY)"
    elif cfg_provider == "mock":
        actual = "mock (test-only fixture)"
    else:
        actual = "unsupported"

    return {
        "configured_provider": cfg_provider,
        "actual_runtime": actual,
        "is_mock": actual.startswith("mock"),
        "model_name": agent_config.model_name,
        "temperature": agent_config.temperature,
        "fallback_provider": agent_config.fallback_1_provider,
        "fallback_model": agent_config.fallback_1_model,
        "fallback_1_provider": agent_config.fallback_1_provider,
        "fallback_1_model": agent_config.fallback_1_model,
        "fallback_2_provider": agent_config.fallback_2_provider,
        "fallback_2_model": agent_config.fallback_2_model,
        "has_gemini_key": has_gemini,
        "has_openai_key": has_openai,
        "has_groq_key": has_groq,
    }


def create_raw_model(provider: str, model_name: str, temperature: float) -> Any:
    """Instantiate a configured chat model. Mock is only permitted in test environments."""
    prov = (provider or "").strip().lower()

    if prov == "groq":
        key = agent_config.groq_api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise LLMUnavailableException(
                "GROQ_API_KEY is required when LLM provider is 'groq'",
                reason="missing_credentials",
            )
        from langchain_groq import ChatGroq
        return ChatGroq(
            model=model_name or "openai/gpt-oss-120b",
            temperature=temperature,
            api_key=key,
            request_timeout=agent_config.timeout_seconds,
            max_retries=3,
        )

    if prov == "google_genai":
        key = agent_config.gemini_api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not key:
            raise LLMUnavailableException(
                "GEMINI_API_KEY or GOOGLE_API_KEY is required when DATT_AGENT_LLM_PROVIDER=google_genai",
                reason="missing_credentials",
            )
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=temperature,
            google_api_key=key,
            request_timeout=agent_config.timeout_seconds,
        )

    if prov == "openai":
        key = agent_config.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            raise LLMUnavailableException(
                "OPENAI_API_KEY is required when DATT_AGENT_LLM_PROVIDER=openai",
                reason="missing_credentials",
            )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=key,
            request_timeout=agent_config.timeout_seconds,
        )

    if prov == "mock":
        is_test = bool(
            os.getenv("PYTEST_CURRENT_TEST")
            or os.getenv("DATT_ALLOW_TEST_MOCK") == "1"
            or os.getenv("CI") == "true"
        )
        if not is_test:
            raise LLMUnavailableException(
                "MockChatModel is disabled in production runtime. Configure 'google_genai' with a valid GEMINI_API_KEY.",
                reason="mock_disallowed_in_production",
            )
        from src.agent.nodes import MockChatModel
        return MockChatModel()

    raise ValueError(
        f"Unsupported LLM provider: {provider!r}. Use 'google_genai', 'groq', or 'openai'."
    )


_shared_resilient_llm: ResilientChatModel | None = None


def get_configured_llm(force_refresh: bool = False) -> ResilientChatModel:
    """Build or retrieve the shared resilient LLM chain with primary and optional fallback."""
    global _shared_resilient_llm
    if _shared_resilient_llm is not None and not force_refresh:
        return _shared_resilient_llm

    primary = create_raw_model(
        provider=agent_config.llm_provider,
        model_name=agent_config.model_name,
        temperature=agent_config.temperature,
    )

    fb1 = None
    if agent_config.fallback_1_provider and agent_config.fallback_1_model:
        try:
            fb1 = create_raw_model(
                provider=agent_config.fallback_1_provider,
                model_name=agent_config.fallback_1_model,
                temperature=agent_config.temperature,
            )
        except Exception as exc:
            logger.warning("Failed to initialize Fallback Level 1 LLM (%s): %s", agent_config.fallback_1_provider, exc)
            fb1 = None

    fb2 = None
    if agent_config.fallback_2_provider and agent_config.fallback_2_model:
        try:
            fb2 = create_raw_model(
                provider=agent_config.fallback_2_provider,
                model_name=agent_config.fallback_2_model,
                temperature=agent_config.temperature,
            )
        except Exception as exc:
            logger.warning("Failed to initialize Fallback Level 2 LLM (%s): %s", agent_config.fallback_2_provider, exc)
            fb2 = None

    _shared_resilient_llm = ResilientChatModel(
        primary_model=primary,
        fallback_model=fb1,
        fallback_2_model=fb2,
        primary_provider=agent_config.llm_provider,
        fallback_provider=agent_config.fallback_1_provider if fb1 else None,
        fallback_2_provider=agent_config.fallback_2_provider if fb2 else None,
        primary_model_name=agent_config.model_name,
        fallback_model_name=agent_config.fallback_1_model if fb1 else None,
        fallback_2_model_name=agent_config.fallback_2_model if fb2 else None,
        timeout_seconds=agent_config.timeout_seconds,
        max_retries=agent_config.max_retries,
        cooldown_seconds=agent_config.circuit_breaker_cooldown_sec,
    )
    return _shared_resilient_llm
