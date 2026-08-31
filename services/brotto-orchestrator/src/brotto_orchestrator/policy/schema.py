"""Policy schema + merge.

`Policy` is the floor (server-side config file). `UserPolicy` is what the
extension sends per task. `merge(floor, user)` returns the effective
policy: secure wins over normal; blacklist is unioned. Effective policy is
always a `Policy`.

# ponytail: whitelist + block_blacklisted were removed in the enterprise
# redesign — blacklist match is always a hard block in secure mode, and
# "allow only these sites" is impractical to maintain (admins can't
# enumerate every safe site). The schema reads pydantic-defaults for the
# dropped fields, so old policy files on disk still parse without error.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


Mode = Literal["normal", "secure"]


class Policy(BaseModel):
    """A policy document. Used for both the floor and the effective policy."""

    mode: Mode = "normal"
    blacklist: list[str] = Field(default_factory=list)
    first_time_seen_prompt: bool = True
    # ponytail: curated list of irreversible action patterns (action name
    # OR substring of action_args) that always require approval in secure
    # mode. Complements the regex-based CRITICAL_PATTERNS by giving admins
    # a declarative list they can edit per-floor. Default covers the common
    # destructive / external-impact cases a bank IT admin would care about.
    sensitive_actions: list[str] = Field(
        default_factory=lambda: [
            "submit_form", "delete_record", "payment", "transfer",
            "change_password", "revoke_access", "publish", "deploy",
            "send_email", "external_post", "approve", "reject",
        ]
    )


# ponytail: UserPolicy is currently identical to Policy — kept as a
# separate type so the extension payload can evolve independently of the
# server's floor schema (e.g. extension-only toggles).
class UserPolicy(Policy):
    pass


def merge(floor: Policy | None, user: Policy | None) -> Policy:
    """Floor ∪ user. Secure mode is sticky upward; blacklist is unioned;
    first_time_seen_prompt is OR."""
    if floor is None and user is None:
        return Policy()
    f = floor or Policy()
    u = user or Policy()
    return Policy(
        mode="secure" if f.mode == "secure" or u.mode == "secure" else "normal",
        blacklist=sorted(set(f.blacklist) | set(u.blacklist)),
        first_time_seen_prompt=f.first_time_seen_prompt or u.first_time_seen_prompt,
    )
