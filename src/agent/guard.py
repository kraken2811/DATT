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


def _sample_chunks(chunks: list[str], max_samples: int = 3) -> list[str]:
    """Sample chunks to represent beginning, middle, and end without exceeding max_samples.

    Guarantees coverage of the first chunk, the last chunk, and evenly distributed middle chunks
    to prevent injections placed at the end or middle from escaping scanning.
    """
    if len(chunks) <= max_samples:
        return chunks
    if max_samples <= 1:
        return [chunks[0]]
    if max_samples == 2:
        return [chunks[0], chunks[-1]]

    first = chunks[0]
    last = chunks[-1]
    num_middle = max_samples - 2
    step = (len(chunks) - 1) / (num_middle + 1)
    middle_indices = [int(round((i + 1) * step)) for i in range(num_middle)]

    sampled = [first]
    for idx in middle_indices:
        if 0 < idx < len(chunks) - 1 and chunks[idx] not in sampled:
            sampled.append(chunks[idx])
    if last not in sampled:
        sampled.append(last)
    return sampled


def check_prompt_safety(
    text: str,
    threshold: float | None = None,
    client: Any | None = None,
    fail_open: bool | None = None,
) -> dict[str, Any]:
    """Evaluate text prompt for prompt injection and jailbreak risks using Groq Prompt Guard.

    Returns:
        dict containing:
            safe (bool): True if prompt is safe to execute, False if high-risk injection detected.
            score (float): Maximum injection probability score across scanned chunks [0.0 - 1.0].
            is_injection (bool): True if score >= threshold.
            chunks_scanned (int): Number of text segments evaluated.
            latency_sec (float): Processing duration in seconds.
            error (str | None): Error detail if service call encountered an issue.
            model (str): Name of prompt guard model used.
    """
    start_time = time.time()
    thresh = threshold if threshold is not None else agent_config.prompt_guard_threshold
    model_name = agent_config.prompt_guard_model
    effective_fail_open = fail_open if fail_open is not None else agent_config.prompt_guard_fail_open

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
            logger.warning("Prompt Guard client initialization failed (%s); fail_open=%s", exc, effective_fail_open)
            return {
                "safe": bool(effective_fail_open),
                "is_safe": bool(effective_fail_open),
                "score": 0.0 if effective_fail_open else 1.0,
                "max_score": 0.0 if effective_fail_open else 1.0,
                "is_injection": not effective_fail_open,
                "chunks_scanned": 0,
                "flagged_chunks": 0 if effective_fail_open else 1,
                "latency_sec": round(time.time() - start_time, 3),
                "error": f"client_init_error: {exc}",
                "reason": "client_init_fail_open" if effective_fail_open else "client_init_fail_closed",
                "model": model_name,
                "status": "fail_open" if effective_fail_open else "fail_closed",
            }

    max_score = 0.0
    scanned_count = 0
    flagged_count = 0

    try:
        # Sample chunks across beginning, middle, and end within max chunk budget
        sampled_chunks = _sample_chunks(chunks, max_samples=agent_config.prompt_guard_max_chunks)
        for chunk in sampled_chunks:
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
            if score >= thresh:
                flagged_count += 1

            # Fast-exit if already beyond threshold
            if max_score >= thresh:
                break

    except Exception as exc:
        duration = round(time.time() - start_time, 3)
        logger.warning(
            "Prompt Guard service error after %.2fs (%s: %s); fail_open=%s",
            duration,
            type(exc).__name__,
            exc,
            effective_fail_open,
        )
        return {
            "safe": bool(effective_fail_open),
            "is_safe": bool(effective_fail_open),
            "score": 0.0 if effective_fail_open else 1.0,
            "max_score": 0.0 if effective_fail_open else 1.0,
            "is_injection": not effective_fail_open,
            "chunks_scanned": scanned_count,
            "flagged_chunks": 0 if effective_fail_open else 1,
            "latency_sec": duration,
            "error": f"service_error: {type(exc).__name__}",
            "reason": "scan_error_fail_open" if effective_fail_open else "scan_error_fail_closed",
            "model": model_name,
            "status": "fail_open" if effective_fail_open else "fail_closed",
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
