"""Gate decision + first-time-seen behaviour."""

from __future__ import annotations

from brotto_orchestrator.policy.gate import (
    GateDecision,
    check_domain_policy,
    check_first_time_seen,
)
from brotto_orchestrator.policy.schema import Policy


# ── check_domain_policy ──────────────────────────────────────────────────────


def test_normal_mode_always_n_a():
    p = Policy(mode="normal", blacklist=["evil.com"])
    assert check_domain_policy("https://evil.com/x", p) == GateDecision.N_A


def test_secure_no_lists_allows():
    p = Policy(mode="secure")
    assert check_domain_policy("https://example.com/x", p) == GateDecision.ALLOW


def test_secure_blacklist_match_always_blocks():
    """Enterprise redesign: blacklist match → BLOCK always in secure mode,
    no user override. No more block_blacklisted flag."""
    p = Policy(mode="secure", blacklist=["evil.com"])
    assert check_domain_policy("https://evil.com/x", p) == GateDecision.BLOCK


def test_secure_blacklist_match_subdomain():
    p = Policy(mode="secure", blacklist=["evil.com"])
    assert check_domain_policy("https://sub.evil.com/x", p) == GateDecision.BLOCK


def test_secure_blacklist_subdomain_specific():
    """Subdomain-specific blacklist matches the exact hostname even when
    eTLD+1 is a different registered domain."""
    p = Policy(mode="secure", blacklist=["bad.bank.com"])
    assert check_domain_policy("https://bad.bank.com/x", p) == GateDecision.BLOCK


def test_secure_blacklist_apex_doesnt_match_subdomain():
    """Adding `evil.com` doesn't block `sub.evil.com` only via eTLD+1 —
    but the hostname check catches it too. So it IS blocked."""
    p = Policy(mode="secure", blacklist=["evil.com"])
    assert check_domain_policy("https://sub.evil.com/x", p) == GateDecision.BLOCK


def test_secure_non_blacklisted_allows():
    """Without whitelist, non-blacklisted domains are simply allowed.
    The 'require_approval' for non-whitelisted domains was removed in the
    redesign — first-time-seen on the *current* domain handles that case
    elsewhere in the harness."""
    p = Policy(mode="secure", blacklist=["evil.com"])
    assert check_domain_policy("https://random.com/x", p) == GateDecision.ALLOW


def test_unparseable_url_returns_n_a():
    p = Policy(mode="secure", blacklist=["evil.com"])
    assert check_domain_policy("not a url at all", p) == GateDecision.N_A


def test_ip_address_returns_n_a():
    p = Policy(mode="secure", blacklist=["1.2.3.4"])
    assert check_domain_policy("http://1.2.3.4/foo", p) == GateDecision.N_A


def test_blacklist_url_form_normalized():
    """Pasting `https://evil.com/` into the UI matches `evil.com` hostname."""
    p = Policy(mode="secure", blacklist=["https://evil.com/"])
    assert check_domain_policy("https://evil.com/x", p) == GateDecision.BLOCK


def test_blacklist_userinfo_path_query_stripped():
    """Patterns with userinfo/path/query/port still match the hostname."""
    p = Policy(mode="secure", blacklist=["user@evil.com:8080/path?q=1"])
    assert check_domain_policy("https://evil.com/x", p) == GateDecision.BLOCK


def test_blacklist_no_approve_path_exists():
    """The GateDecision enum no longer has APPROVE — the design removed
    the override route entirely. This is a regression test against
    accidentally re-adding it."""
    assert not hasattr(GateDecision, "APPROVE")
    assert GateDecision.BLOCK.value == "block"
    assert GateDecision.ALLOW.value == "allow"
    assert GateDecision.N_A.value == "n/a"


# ── check_first_time_seen ────────────────────────────────────────────────────


def test_first_time_seen_normal_mode_always_false():
    p = Policy(mode="normal", first_time_seen_prompt=True)
    seen: set = set()
    assert check_first_time_seen(("bank.com", "click"), seen, p) is False


def test_first_time_seen_secure_returns_true_when_unseen():
    p = Policy(mode="secure", first_time_seen_prompt=True)
    seen: set = set()
    assert check_first_time_seen(("bank.com", "click"), seen, p) is True


def test_first_time_seen_secure_returns_false_after_seen():
    p = Policy(mode="secure", first_time_seen_prompt=True)
    seen = {("bank.com", "click")}
    assert check_first_time_seen(("bank.com", "click"), seen, p) is False


def test_first_time_seen_disabled_returns_false():
    p = Policy(mode="secure", first_time_seen_prompt=False)
    seen: set = set()
    assert check_first_time_seen(("bank.com", "click"), seen, p) is False


def test_first_time_seen_different_action_still_first_time():
    p = Policy(mode="secure", first_time_seen_prompt=True)
    seen = {("bank.com", "click")}
    assert check_first_time_seen(("bank.com", "type_text"), seen, p) is True


def test_first_time_seen_different_domain_still_first_time():
    p = Policy(mode="secure", first_time_seen_prompt=True)
    seen = {("bank.com", "click")}
    assert check_first_time_seen(("other.com", "click"), seen, p) is True
