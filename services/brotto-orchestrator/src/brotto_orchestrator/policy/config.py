"""Load a floor `Policy` from disk.

JSON-only. Path: $BROTTO_POLICY_FILE, then ./policy.json (relative to cwd).
Missing file is not an error — returns None (no floor). Malformed file
raises (operators need to know).

# ponytail: JSON-only because adding PyYAML is heavier than the value
# the format adds for a 10-line config. Upgrade: pip install pyyaml and
# swap the `json.load` call for `yaml.safe_load` — the schema is
# identical.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .schema import Policy

_ENV_VAR = "BROTTO_POLICY_FILE"
_DEFAULT_PATH = "policy.json"


def load_policy(path: str | os.PathLike[str] | None = None) -> Policy | None:
    """Load the floor policy. Returns None when no file is configured."""
    if path is None:
        path = os.environ.get(_ENV_VAR, _DEFAULT_PATH)
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() in (".yaml", ".yml"):
        raise NotImplementedError(
            f"YAML policy file {p} is not supported. Convert to JSON or "
            f"install PyYAML and adapt load_policy()."
        )
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return Policy.model_validate(data)
