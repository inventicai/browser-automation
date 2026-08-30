"""Per-user policy persistence.

The in-memory `SessionRegistry` is wiped on every server restart, so a
user who saved their blacklist yesterday returns to a sidepanel showing
only the floor today. This module persists the LAST KNOWN user policy
per user_id (or per client IP) to a JSON file under
`logs/user_policies/<key>.json`. On startup, `SessionRegistry.hydrate`
re-populates the cache from disk so `GET /v1/policy` returns the user's
saved view immediately, even before they reconnect.

`ponytail: ponytail:` single-process JSON files keyed by user_id. A
multi-replica deployment would need a shared store (Postgres / Redis).
The filename is the user_id hash-truncated so we never write to a
predictable path (collision risk on adversarial input).

Format on disk:

    {
      "_saved_at": "2026-08-29T22:01:00Z",
      "_content_sha256": "abc123...",
      "mode": "secure",
      "blacklist": ["foo.com", "bar.com"]
    }

The two underscore-prefixed fields are bookkeeping: `_content_sha256`
powers change detection (skip no-op writes), `_saved_at` is the
human-readable timestamp the sidepanel surfaces in its verify-status
footer. They are stripped before hashing so a re-save with identical
content compares equal.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


_DIR = Path(os.getenv("BROTTO_USER_POLICY_DIR", "logs/user_policies"))


def _key_to_filename(key: str) -> str:
    """Map any caller-supplied key to a filesystem-safe filename.

    Strategy: sha256 of the key, truncated. Adversarial input can't
    escape the directory; legitimate keys (UUIDs, IPs) are recoverable
    only by their hash (which is fine — the key is logged alongside).
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return f"{digest}.json"


def _payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash of the user-visible payload (excludes bookkeeping
    fields so a no-op re-save compares equal)."""
    visible = {k: v for k, v in payload.items() if not k.startswith("_")}
    canonical = json.dumps(visible, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_if_changed(user_key: str, payload: dict[str, Any]) -> bool:
    """Persist the payload only when its content hash differs from the
    on-disk file. Returns True iff a write happened. This is the
    save-on-change primitive the sidepanel Save button calls — without
    it, every click (even no-op clicks) re-touches the file and bumps
    the mtime, defeating the sidepanel's "Last verified" freshness
    check.

    Atomic via tempfile + rename so a crash mid-write can't corrupt
    the existing file.
    """
    _DIR.mkdir(parents=True, exist_ok=True)
    path = _DIR / _key_to_filename(user_key)
    new_hash = _payload_hash(payload)

    existing = load(user_key)
    if existing is not None:
        existing_visible = {k: v for k, v in existing.items() if not k.startswith("_")}
        if _payload_hash(existing_visible) == new_hash:
            # No-op save — same content as on disk. Skip the write.
            return False

    enriched = dict(payload)
    enriched["_saved_at"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    enriched["_content_sha256"] = new_hash

    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_", dir=_DIR)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(enriched, f, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return True


def save(user_key: str, payload: dict[str, Any]) -> None:
    """Unconditional save (legacy callers; prefer save_if_changed)."""
    save_if_changed(user_key, payload)


def load(user_key: str) -> dict[str, Any] | None:
    """Return the persisted payload for this user, or None if absent /
    malformed. Malformed files are left in place — a human can inspect
    them post-mortem."""
    path = _DIR / _key_to_filename(user_key)
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_all() -> dict[str, dict[str, Any]]:
    """Bulk-load every persisted user policy, keyed by filename stem.

    Used at server startup to seed SessionRegistry. The original user
    key (IP or UUID) isn't recoverable from the hash; callers should
    treat the loaded keys as opaque identifiers. The wire protocol uses
    `caller` (request.client.host) which is matched by sidepanel's
    `user_id` query parameter.
    """
    if not _DIR.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in _DIR.glob("*.json"):
        try:
            with path.open() as f:
                out[path.stem] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def directory_path() -> Path:
    """Where policy files live. Surfaced for logging at startup."""
    return _DIR


# ponytail: filename guard for sanity tests / future path-based callers.
_SAFE_NAME = re.compile(r"^[a-f0-9]{32}\.json$")
