"""
Endpoint authentication.

The /route and /sn/webhook endpoints accept a shared secret in the
X-Router-Token header. In production the token is required (enforced at
startup by config.assert_production_ready). In development, if no token is
configured, the check is skipped so you can curl freely.

Comparison is constant-time to avoid leaking the secret through timing.
"""

import hmac

from fastapi import Header, HTTPException, status

from ticket_router.config import get_settings


def verify_token(x_router_token: str | None = Header(default=None)) -> None:
    settings = get_settings()
    expected = settings.webhook_token

    # No token configured (development convenience): allow.
    if not expected:
        return

    if not x_router_token or not hmac.compare_digest(x_router_token, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing X-Router-Token",
        )
