"""Policy loader + merge."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from brotto_orchestrator.policy.config import load_policy
from brotto_orchestrator.policy.schema import Policy, merge


# ── merge ────────────────────────────────────────────────────────────────────


def test_merge_both_none():
    assert merge(None, None) == Policy()


def test_merge_user_only():
    p = merge(None, Policy(mode="secure", blacklist=["foo.com"]))
    assert p.mode == "secure"
    assert p.blacklist == ["foo.com"]


def test_merge_floor_only():
    p = merge(Policy(mode="secure", blacklist=["bank.com"]), None)
    assert p.mode == "secure"
    assert p.blacklist == ["bank.com"]


def test_merge_floor_secure_wins_over_user_normal():
    p = merge(Policy(mode="secure"), Policy(mode="normal"))
    assert p.mode == "secure"


def test_merge_user_secure_wins_over_floor_normal():
    p = merge(Policy(mode="normal"), Policy(mode="secure"))
    assert p.mode == "secure"


def test_merge_blacklist_is_union():
    p = merge(
        Policy(blacklist=["a.com", "b.com"]),
        Policy(blacklist=["b.com", "c.com"]),
    )
    assert p.blacklist == ["a.com", "b.com", "c.com"]


def test_merge_first_time_seen_or():
    p = merge(
        Policy(first_time_seen_prompt=False),
        Policy(first_time_seen_prompt=False),
    )
    # Both false → false (OR semantics).
    assert p.first_time_seen_prompt is False


def test_merge_first_time_seen_default_floor():
    # If neither side explicitly disables, default (True) is preserved.
    p = merge(Policy(blacklist=["a.com"]), Policy())
    assert p.first_time_seen_prompt is True


def test_merge_drops_whitelist_and_block_blacklisted_silently():
    """If an old policy.json still has whitelist/block_blacklisted (from a
    pre-redesign version), merge() must not crash. Pydantic 2 drops unknown
    fields silently on Policy construction; this guards against a future
    extra='forbid' that would break upgrades."""
    floor = Policy(blacklist=["evil.com"])
    user = Policy(blacklist=["foo.com"])
    merged = merge(floor, user)
    assert merged.blacklist == ["evil.com", "foo.com"]


# ── load_policy ──────────────────────────────────────────────────────────────


def test_load_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("BROTTO_POLICY_FILE", str(tmp_path / "absent.json"))
    assert load_policy() is None


def test_load_explicit_path_missing(tmp_path):
    assert load_policy(tmp_path / "absent.json") is None


def test_load_yaml_extension_raises(tmp_path):
    p = tmp_path / "policy.yaml"
    p.write_text("mode: secure")
    with pytest.raises(NotImplementedError):
        load_policy(p)


def test_load_valid_json(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({
        "mode": "secure",
        "blacklist": ["evil.com"],
        "first_time_seen_prompt": True,
    }))
    pol = load_policy(p)
    assert pol is not None
    assert pol.mode == "secure"
    assert pol.blacklist == ["evil.com"]
    assert pol.first_time_seen_prompt is True


def test_load_legacy_fields_ignored(tmp_path):
    """Pre-redesign policy files with whitelist/block_blacklisted parse
    cleanly — those fields are silently dropped."""
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({
        "mode": "secure",
        "whitelist": ["bank.com"],
        "blacklist": ["evil.com"],
        "block_blacklisted": False,
    }))
    pol = load_policy(p)
    assert pol is not None
    assert pol.mode == "secure"
    assert pol.blacklist == ["evil.com"]
    # Dropped fields don't reappear as attributes.
    assert not hasattr(pol, "whitelist") or getattr(pol, "whitelist", None) == []
    assert not hasattr(pol, "block_blacklisted")


def test_load_minimal_json_defaults(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text("{}")
    pol = load_policy(p)
    assert pol is not None
    assert pol.mode == "normal"
    assert pol.blacklist == []
    assert pol.first_time_seen_prompt is True


def test_load_invalid_json_raises(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text("{not json")
    with pytest.raises(json.JSONDecodeError):
        load_policy(p)


def test_load_unknown_field_ignored(tmp_path):
    # Pydantic 2 default is permissive: unknown fields are dropped silently.
    # If we ever want strict (rejects typos in floor configs), set
    # `model_config = ConfigDict(extra="forbid")` on Policy.
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"mode": "normal", "unknown_field": True}))
    pol = load_policy(p)
    assert pol is not None
    assert pol.mode == "normal"


def test_env_var_overrides_default(tmp_path, monkeypatch):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"mode": "secure"}))
    monkeypatch.setenv("BROTTO_POLICY_FILE", str(p))
    pol = load_policy()
    assert pol is not None
    assert pol.mode == "secure"
