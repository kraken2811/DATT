"""Prompt Guard security layer using meta-llama/llama-prompt-guard-2-22m.

Detects prompt injection and jailbreak attempts before untrusted user inputs
are processed by LangGraph or LLM backends.
"""

import logging
import os
import time
from typing import Any

from src.agent.config import agent_config

logger = logging.getLogger("datt.agent.guard")

# Maximum characters per chunk to respect Prompt Guard's 512 token context window
CHUNK_MAX_CHARS = 1200
CHUNK_OVERLAP = 100


def _chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Segment long inputs into overlapping chunks to prevent context truncation."""
    clean = text.strip()
    if not clean:
        return []
    if len(clean) <= max_chars:
        return [clean]

    chunks = []
    start = 0
    text_len = len(clean)
    while start < text_len:
        end = min(start + max_chars, text_len)
        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= text_len:
            break
        start += max_chars - overlap
    return chunks


def check_prompt_safety(
    text: str,
    threshold: float | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Evaluate text prompt for prompt injection and jailbreak risks using Groq Prompt Guard.

    Returns:
        dict containing:
            safe (bool): True if prompt is safe to execute, False if high-risk injection detected.
            score (float): Maximum injection probability score across scanned chunks [0.0 - 1.0].
            is_injection (bool): True if score >= threshold.
            chunks_scanned (int): Number of text segments evaluated.
            latency_sec (float): Processing duration in seconds.
            error (str | None): Error detail if service call encountered an issue (fail-open).
            model (str): Name of prompt guard model used.
    """
    start_time = time.time()
    thresh = threshold if threshold is not None else agent_config.prompt_guard_threshold
    model_name = agent_config.prompt_guard_model

    # Check if disabled by configuration
    if not agent_config.prompt_guard_enabled:
        return {
            "safe": True,
            "is_safe": True,
            "score": 0.0,
            "max_score": 0.0,
            "is_injection": False,
            "chunks_scanned": 0,
            "flagged_chunks": 0,
            "latency_sec": 0.0,
            "error": None,
            "reason": "safe",
            "model": model_name,
            "status": "disabled",
        }

    key = agent_config.groq_api_key or os.getenv("GROQ_API_KEY")
    if not key:
        logger.debug("Prompt Guard skipped: GROQ_API_KEY is not configured.")
        return {
            "safe": True,
            "is_safe": True,
            "score": 0.0,
            "max_score": 0.0,
            "is_injection": False,
            "chunks_scanned": 0,
            "flagged_chunks": 0,
            "latency_sec": 0.0,
            "error": "missing_groq_api_key",
            "reason": "safe",
            "model": model_name,
            "status": "skipped",
        }

    chunks = _chunk_text(text)
    if not chunks:
        return {
            "safe": True,
            "is_safe": True,
            "score": 0.0,
            "max_score": 0.0,
            "is_injection": False,
            "chunks_scanned": 0,
            "flagged_chunks": 0,
            "latency_sec": 0.0,
            "error": None,
            "reason": "safe",
            "model": model_name,
            "status": "empty_input",
        }

    # Initialize Groq client if not provided
    if client is None:
        try:
            from groq import Groq
            client = Groq(api_key=key, timeout=10.0)
        except Exception as exc:
            logger.warning("Prompt Guard client initialization failed (%s); failing open.", exc)
            return {
                "safe": True,
                "score": 0.0,
                "is_injection": False,
                "chunks_scanned": 0,
                "latency_sec": round(time.time() - start_time, 3),
                "error": f"client_init_error: {exc}",
                "model": model_name,
                "status": "fail_open",
            }

    max_score = 0.0
    scanned_count = 0

    try:
        # Scan each chunk (limit to at most 3 chunks for cost/latency bounding)
        for chunk in chunks[:3]:
            resp = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": chunk}],
                temperature=0.0,
            )
            scanned_count += 1
            content = resp.choices[0].message.content or "0.0"
            try:
                score = float(content.strip())
            except ValueError:
                logger.debug("Prompt Guard non-numeric response: %r", content)
                score = 0.0

            if score > max_score:
                max_score = score

            # Fast-exit if already beyond threshold
            if max_score >= thresh:
                break

    except Exception as exc:
        duration = round(time.time() - start_time, 3)
        logger.warning(
            "Prompt Guard service error after %.2fs (%s: %s); failing open for availability.",
            duration,
            type(exc).__name__,
            exc,
        )
        return {
            "safe": True,
            "is_safe": True,
            "score": 0.0,
            "max_score": 0.0,
            "is_injection": False,
            "chunks_scanned": scanned_count,
            "flagged_chunks": 0,
            "latency_sec": duration,
            "error": f"service_error: {type(exc).__name__}",
            "reason": "scan_error_fail_open",
            "model": model_name,
            "status": "fail_open",
        }

    duration = round(time.time() - start_time, 3)
    is_inj = max_score >= thresh

    if is_inj:
        logger.warning(
            "Prompt Guard detected injection attempt (score=%.4f >= thresh=%.2f, latency=%.2fs)",
            max_score,
            thresh,
            duration,
        )
    else:
        logger.debug(
            "Prompt Guard passed (score=%.4f < thresh=%.2f, chunks=%d, latency=%.2fs)",
            max_score,
            thresh,
            scanned_count,
            duration,
        )

    return {
        "safe": not is_inj,
        "is_safe": not is_inj,
        "score": round(max_score, 5),
        "max_score": round(max_score, 5),
        "is_injection": is_inj,
        "chunks_scanned": scanned_count,
        "flagged_chunks": 1 if is_inj else 0,
        "latency_sec": duration,
        "error": None,
        "reason": "prompt_injection_detected" if is_inj else "safe",
        "model": model_name,
        "status": "flagged" if is_inj else "clean",
    }
