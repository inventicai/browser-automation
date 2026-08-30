"""Pure decision functions for the secure-mode gate.

In secure mode, the only policy enforcement is:
  - blacklist match → BLOCK (task terminates; no user override)

In normal mode, NONE of these ever prompt — byte-identical to pre-feat
harness code. That contract is what keeps the default behavior unchanged
when no floor policy is configured.

# ponytail: removed whitelist (impractical for admins to maintain;
# "approve the rest" is the wrong mental model for a bank). Removed
# block_blacklisted flag (blacklist match is always a hard block in
# secure mode — no user override path). See schema.py header for the
# full rationale.
"""

from __future__ import annotations

from enum import Enum

from .domains import domain_matches, etld1
from .schema import Policy


class GateDecision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    N_A = "n/a"


def check_domain_policy(url: str, policy: Policy) -> GateDecision:
    """Decide what to do with a URL given the policy.

    Precedence:
      1. URL can't be parsed → n/a (don't gate on garbage)
      2. blacklist pattern matches eTLD+1 or hostname → block
      3. Otherwise → allow

    Always returns n/a in normal mode.
    """
    if policy.mode != "secure":
        return GateDecision.N_A
    domain = etld1(url)
    if domain is None:
        return GateDecision.N_A
    hostname = _hostname_only(url)
    if policy.blacklist:
        for pat in policy.blacklist:
            if domain_matches(domain, pat) or (hostname and domain_matches(hostname, pat)):
                return GateDecision.BLOCK
    return GateDecision.ALLOW


def _hostname_only(url: str) -> str:
    """Pull the hostname out of a URL without depending on the URL being well-formed."""
    raw = url.split("://", 1)[-1].split("/", 1)[0]
    raw = raw.split("@")[-1].split(":")[0]
    host = raw.lower().strip(".")
    if host.startswith("www.") and host.count(".") >= 2:
        host = host[4:]
    return host


def check_first_time_seen(
    key: tuple[str, str],
    seen: set[tuple[str, str]],
    policy: Policy,
) -> bool:
    """True iff the (domain, action) pair has not been seen this session
    AND secure mode + first_time_seen_prompt are both enabled.

    Caller adds the key to `seen` after acting on the result (whether
    approved or denied) — re-asking on deny would loop, and on approve
    we don't want to re-prompt on every subsequent step.
    """
    if policy.mode != "secure" or not policy.first_time_seen_prompt:
        return False
    return key not in seen
