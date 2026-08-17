from __future__ import annotations

import os

# ponytail: plain shared secret, add JWT when auth is a real requirement
_SECRET = os.getenv("AGENT_SECRET", "dev-secret")


def validate_token(token: str) -> bool:
    if os.getenv("AGENT_AUTH_DISABLED", "true").lower() == "true":
        return True
    return token == _SECRET
