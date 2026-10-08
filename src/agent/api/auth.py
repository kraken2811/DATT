"""Authentication and authorization utilities for DATT AI Agent endpoints.

Protects against identity spoofing: Never trusts arbitrary client-supplied
user IDs (such as X-User-Id or payload.user_id) without validation.
"""

import hashlib
import hmac
import logging
import os
from typing import Tuple

from fastapi import HTTPException, Request

logger = logging.getLogger("datt.agent.auth")

# Optional environment secrets for proxy or token verification
TRUSTED_PROXY_SECRET = os.getenv("DATT_TRUSTED_PROXY_SECRET")
AUTH_SECRET = os.getenv("DATT_AGENT_AUTH_SECRET") or os.getenv("DATT_SECRET_KEY") or "datt_secure_internal_secret_key"


def create_auth_token(user_id: str, secret: str | None = None) -> str:
    """Generate a cryptographically signed HMAC Bearer token for an authenticated user."""
    eff_secret = (secret or AUTH_SECRET).encode("utf-8")
    clean_user = user_id.strip()
    sig = hmac.new(eff_secret, clean_user.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{clean_user}:{sig}"


def resolve_authenticated_user(
    request: Request,
    client_claimed_user: str | None = None,
    client_claimed_session: str | None = None,
) -> Tuple[str, bool]:
    """Resolve and verify user identity from request context.

    Security Rules:
    1. If a reverse proxy secret header is sent:
       - Must match DATT_TRUSTED_PROXY_SECRET (403 on mismatch).
       - Must include a non-empty X-User-Id header (400 if missing).
    2. If an Authorization header is provided:
       - Must use Bearer scheme (401 on invalid scheme).
       - Must contain a valid user:signature HMAC token (401 on malformed or forged signature).
       - Never silently falls through to unauthenticated mode.
    3. If running unauthenticated/local dev:
       - Privileged accounts ('admin', 'root', 'system') are strictly forbidden without credentials (403).
       - If DATT_STRICT_AUTH=1, unauthenticated access is forbidden (401).
       - Client session tokens (X-Session-Id, X-Client-Id, session_id) are cryptographically bound
         with the client IP so two clients on the same IP / NAT router cannot access each other's data.

    Returns:
        tuple[verified_user_id, is_authenticated]
    """
    # 1. Reverse Proxy header validation
    proxy_secret = request.headers.get("X-Proxy-Secret")
    if proxy_secret:
        if not TRUSTED_PROXY_SECRET or not hmac.compare_digest(proxy_secret, TRUSTED_PROXY_SECRET):
            raise HTTPException(status_code=403, detail="Forbidden: Invalid reverse proxy secret.")
        proxy_user = request.headers.get("X-User-Id")
        if not proxy_user or not proxy_user.strip():
            raise HTTPException(status_code=400, detail="Bad Request: X-User-Id header missing from trusted proxy request.")
        return proxy_user.strip(), True

    # 2. Bearer Token validation (Strict, never falls through)
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header:
        if not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Unsupported authorization scheme. Bearer token required.",
            )
        token = auth_header[len("Bearer "):].strip()
        if not token or ":" not in token:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Malformed Bearer token format (expected 'user:signature').",
            )
        user_part, sig_part = token.rsplit(":", 1)
        expected_sig = hmac.new(
            AUTH_SECRET.encode("utf-8"),
            user_part.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig_part, expected_sig):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Invalid token signature.",
            )
        return user_part.strip(), True

    # 3. Direct Client fallback with spoofing protection
    raw_user = (client_claimed_user or request.headers.get("X-User-Id") or "").strip()
    client_ip = request.client.host if request.client else "local"

    # Block privileged user spoofing by unauthenticated clients
    privileged_names = {"admin", "root", "system", "superuser", "datt_admin"}
    if raw_user.lower() in privileged_names:
        raise HTTPException(
            status_code=403,
            detail="Forbidden: Cannot claim privileged identity without authentication credentials.",
        )

    if os.getenv("DATT_STRICT_AUTH") == "1":
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Valid authentication token is required.",
        )

    # Resolve client session token (prevents same-IP/NAT cross-client collision)
    session_token = (
        request.headers.get("X-Session-Id")
        or request.headers.get("X-Client-Id")
        or request.query_params.get("session_id")
        or client_claimed_session
    )
    if session_token and session_token.strip():
        token_digest = hashlib.sha256(f"{client_ip}:{session_token.strip()}".encode("utf-8")).hexdigest()[:12]
        scoped_user = f"unauth_{raw_user or 'guest'}_{token_digest}"
        return scoped_user, False

    # Default fallback for anonymous guest session using IP fingerprint
    ip_digest = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:8]
    scoped_user = f"unauth_{raw_user or 'guest'}_{ip_digest}"
    return scoped_user, False
