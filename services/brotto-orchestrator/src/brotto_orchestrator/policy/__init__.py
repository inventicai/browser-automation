"""Policy: domain whitelist/blacklist + secure mode gate.

Loaded by the orchestrator at startup (floor) and from the extension on
each task (user_policy). Merged into a single effective policy that the
harness consults at three checkpoints.

No new deps; stdlib only. See module docstrings for upgrade paths.
"""

from .config import load_policy
from .domains import MULTI_PART_SUFFIXES, domain_matches, etld1
from .gate import GateDecision, check_domain_policy, check_first_time_seen
from .schema import Policy, UserPolicy, merge

__all__ = [
    "GateDecision",
    "MULTI_PART_SUFFIXES",
    "Policy",
    "UserPolicy",
    "check_domain_policy",
    "check_first_time_seen",
    "domain_matches",
    "etld1",
    "load_policy",
    "merge",
]
