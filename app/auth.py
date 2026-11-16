"""Demo sign-in tokens: an HMAC-signed role, user and expiry.

DEMO ONLY. The demo sign-in has no password, so anyone who can reach POST /auth/demo-login can choose a role.
What the token adds over plain X-Role headers: identity is issued in one place, cannot be edited by the client
(the signature covers role and user), and expires. Production needs the government SSO instead of this sign-in.
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Optional

AUTH_ENV = "GOVFLOW_AUTH_SECRET"
INSECURE_ENV = "GOVFLOW_DEMO_INSECURE"      # "1" also accepts plain X-Role / X-User headers (old clients, scripts)
TOKEN_TTL = timedelta(hours=8)               # one working day


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def issue_token(role: str, user: str, secret: str, now: datetime) -> tuple[str, datetime]:
    """A signed token for role and user, valid for TOKEN_TTL from `now`. Returns (token, expires_at)."""
    expires = now + TOKEN_TTL
    body = _b64(json.dumps({"role": role, "user": user, "exp": int(expires.timestamp())}, sort_keys=True).encode())
    return f"{body}.{_sign(body, secret)}", expires


def read_token(token: str, secret: str, now: datetime) -> Optional[tuple[str, str]]:
    """(role, user) from a token this server signed and that has not expired; None for anything else."""
    body, _, signature = token.strip().partition(".")
    if not body or not signature or not hmac.compare_digest(signature, _sign(body, secret)):
        return None
    try:
        claims = json.loads(_unb64(body))
        role, user, exp = str(claims["role"]), str(claims["user"]), int(claims["exp"])
    except (ValueError, KeyError, TypeError):
        return None
    return (role, user) if now.timestamp() < exp else None
