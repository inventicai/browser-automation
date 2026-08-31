"""Unit tests for the enterprise-redesign policy changes.

Pure-function tests, no I/O, no event loops, no LLM mocks. Each test
runs in <50ms. Integration coverage is in
`scripts/smoke_secure_mode.py` (run separately, slower).

Covers:
- `_HUMAN_PAUSE_BUCKETS` set membership
- `_log_timings()` math: wall_agent = wall - human_pause
- `_make_user_denied_result()` / `_make_policy_blocked_result()` shapes
- GateDecision enum regression (no APPROVE member)
- `Policy` schema dropped whitelist/block_blacklisted cleanly
- `AgentDeps` no longer has `approved_domains`
"""

from __future__ import annotations


# ── Schema regression ───────────────────────────────────────────────────────


def test_policy_schema_no_whitelist_field():
    """Whitelist was removed in the enterprise redesign. Pydantic's default
    is permissive (drops unknown fields) so old policy.json files still
    load — but the type itself must not declare `whitelist`."""
    from brotto_orchestrator.policy.schema import Policy
    assert "whitelist" not in Policy.model_fields


def test_policy_schema_no_block_blacklisted_field():
    from brotto_orchestrator.policy.schema import Policy
    assert "block_blacklisted" not in Policy.model_fields


def test_policy_schema_retains_blacklist_and_first_time_seen():
    from brotto_orchestrator.policy.schema import Policy
    assert "blacklist" in Policy.model_fields
    assert "first_time_seen_prompt" in Policy.model_fields
    assert "mode" in Policy.model_fields


def test_policy_defaults():
    from brotto_orchestrator.policy.schema import Policy
    p = Policy()
    assert p.mode == "normal"
    assert p.blacklist == []
    assert p.first_time_seen_prompt is True


def test_policy_user_policy_inherits():
    from brotto_orchestrator.policy.schema import Policy, UserPolicy
    # UserPolicy must remain a (sub)type of Policy so user_policy payloads
    # from the extension parse through the same shape.
    assert issubclass(UserPolicy, Policy)


# ── GateDecision regression ──────────────────────────────────────────────────


def test_gate_decision_has_no_approve():
    """APPROVE was removed — blacklist matches always block in secure mode,
    and the old whitelist-approve path is gone. Regression guard against
    accidentally re-adding it."""
    from brotto_orchestrator.policy.gate import GateDecision
    assert not hasattr(GateDecision, "APPROVE")
    # And the surviving members are the only ones.
    assert {m.name for m in GateDecision} == {"ALLOW", "BLOCK", "N_A"}


# ── Timing math ─────────────────────────────────────────────────────────────


def test_human_pause_buckets_match_known_set():
    """Regression guard against silently adding a new human-pause site
    without including it in the wall-exclusion set."""
    from brotto_orchestrator.agent.harness import _HUMAN_PAUSE_BUCKETS, TIMING_BUCKETS
    # Every human-pause bucket must be declared in TIMING_BUCKETS (else
    # timers[...] += ... would KeyError at runtime).
    assert _HUMAN_PAUSE_BUCKETS.issubset(set(TIMING_BUCKETS))
    # And the set is non-empty — if you add a new prompt site, add it here.
    assert _HUMAN_PAUSE_BUCKETS == frozenset({"login_pause", "approval_pause"})


def test_log_timings_math():
    """Pure-function test of `_log_timings()`: wall_agent = wall - human_pause."""
    from brotto_orchestrator.agent.harness import (
        _HUMAN_PAUSE_BUCKETS, TIMING_BUCKETS, AgentHarness,
    )

    timings = {b: 0.0 for b in TIMING_BUCKETS}
    timings["observe"] = 0.5
    timings["model_plan"] = 1.5
    timings["execute"] = 0.5
    timings["login_pause"] = 1.2
    timings["approval_pause"] = 0.5
    wall = 4.2

    out = AgentHarness._log_timings("u", timings, steps=2, wall=wall)

    expected_human = sum(timings[b] for b in _HUMAN_PAUSE_BUCKETS)
    assert out["human_pause_s"] == round(expected_human, 3)
    assert out["wall_s"] == round(wall, 3)
    assert out["wall_agent_s"] == round(wall - expected_human, 3)
    # Invariant: wall_agent + human_pause ≈ wall.
    assert abs(out["wall_s"] - (out["wall_agent_s"] + out["human_pause_s"])) < 0.01


def test_log_timings_no_human_pause():
    """When no approvals happened, wall_agent == wall (all the time was
    agent work)."""
    from brotto_orchestrator.agent.harness import TIMING_BUCKETS, AgentHarness

    timings = {b: 0.0 for b in TIMING_BUCKETS}
    timings["observe"] = 0.3
    timings["model_plan"] = 1.0
    timings["execute"] = 0.2
    wall = 1.5

    out = AgentHarness._log_timings("u", timings, steps=1, wall=wall)

    assert out["human_pause_s"] == 0.0
    assert out["wall_agent_s"] == round(wall, 3)


def test_log_timings_human_pause_exceeds_wall_clamped_to_zero():
    """If the buckets somehow sum to more than wall (shouldn't happen but
    defensive), wall_agent is clamped at 0 — never negative."""
    from brotto_orchestrator.agent.harness import TIMING_BUCKETS, AgentHarness

    timings = {b: 0.0 for b in TIMING_BUCKETS}
    timings["login_pause"] = 5.0  # ridiculous
    wall = 1.0  # but wall is short

    out = AgentHarness._log_timings("u", timings, steps=1, wall=wall)

    assert out["wall_agent_s"] == 0.0  # max(0, wall - human_pause)
    assert out["human_pause_s"] == 5.0


# ── Abort-result helpers ────────────────────────────────────────────────────


def test_make_user_denied_result_shape():
    """The helper used by all 3 deny paths (critical, first-time-seen,
    domain-policy) — kept uniform so callers can't drift."""
    from brotto_orchestrator.agent.harness import _make_user_denied_result
    r = _make_user_denied_result(step=3, domain="evil.com", kind="critical action click")
    assert r.status == "failed"
    assert r.failure_reason == "user_denied"
    assert "evil.com" in r.summary
    assert "critical action click" in r.summary
    assert r.steps_taken == 4  # step + 1


def test_make_policy_blocked_result_shape():
    from brotto_orchestrator.agent.harness import _make_policy_blocked_result
    r = _make_policy_blocked_result(step=2, domain="bad.com")
    assert r.status == "failed"
    assert r.failure_reason == "policy_blocked"
    assert "bad.com" in r.summary
    assert r.steps_taken == 3


def test_user_denied_result_no_domain():
    """Critical-action denials don't have a domain; the summary should
    still be human-readable without one."""
    from brotto_orchestrator.agent.harness import _make_user_denied_result
    r = _make_user_denied_result(step=0, domain=None, kind="critical action")
    # Domain-suffix is only added when domain is non-None.
    assert r.summary == "User denied critical action approval"
    assert "critical action" in r.summary


# ── AgentDeps regression ────────────────────────────────────────────────────


def test_agent_deps_no_approved_domains():
    """approved_domains was only there to skip re-prompts on whitelisted
    domains. With deny-aborts-task semantics, that cache is gone — every
    approval is a deliberate user choice per task."""
    from brotto_orchestrator.agent.context import AgentDeps
    assert "approved_domains" not in AgentDeps.__dataclass_fields__


def test_agent_deeps_has_seen_first_time():
    """seen_first_time survives — it's the cache that prevents
    first-time-seen from re-firing on every step."""
    from brotto_orchestrator.agent.context import AgentDeps
    assert "seen_first_time" in AgentDeps.__dataclass_fields__


def test_agent_deps_has_policy_field():
    from brotto_orchestrator.agent.context import AgentDeps
    assert "policy" in AgentDeps.__dataclass_fields__


# ── Reason templates ────────────────────────────────────────────────────────


def test_first_time_seen_reason_format():
    """The reasoning string is what shows up in the sidepanel card.
    Format it once here; any break is caught immediately."""
    from brotto_orchestrator.agent.harness import _REASON_FIRST_TIME
    msg = _REASON_FIRST_TIME.format(domain="bank.com", action="click")
    assert "bank.com" in msg
    assert "click" in msg
    assert "?" in msg  # asks the user


# ── Merge sanity (a couple more cases for the redesigned schema) ───────────


def test_merge_secure_sticky_with_empty_blacklist():
    """Even with empty lists, secure mode from either side wins."""
    from brotto_orchestrator.policy.schema import Policy, merge
    assert merge(Policy(mode="secure"), Policy(mode="normal")).mode == "secure"
    assert merge(Policy(mode="normal"), Policy(mode="secure")).mode == "secure"
    assert merge(Policy(mode="normal"), Policy()).mode == "normal"


def test_merge_blacklist_dedup_and_sort():
    """Union semantics + deterministic order so the audit log is stable."""
    from brotto_orchestrator.policy.schema import Policy, merge
    merged = merge(
        Policy(blacklist=["b.com", "a.com"]),
        Policy(blacklist=["a.com", "c.com"]),
    )
    assert merged.blacklist == ["a.com", "b.com", "c.com"]


def test_merge_first_time_seen_disabled_on_either_side():
    """first_time_seen_prompt is OR — either side enabling it wins.
    This is the OPPOSITE of mode (which is sticky upward)."""
    from brotto_orchestrator.policy.schema import Policy, merge
    # User disables, floor enabled → user disable wins? NO — OR.
    assert merge(Policy(first_time_seen_prompt=True),
                 Policy(first_time_seen_prompt=False)).first_time_seen_prompt is True
    assert merge(Policy(first_time_seen_prompt=False),
                 Policy(first_time_seen_prompt=True)).first_time_seen_prompt is True
    assert merge(Policy(first_time_seen_prompt=False),
                 Policy(first_time_seen_prompt=False)).first_time_seen_prompt is False


# ── Bug A regression: first-time-seen guard ────────────────────────────────


class _FakeRunLog:
    """Minimal stand-in for RunLogger — records log_policy calls."""
    def __init__(self):
        self.calls: list[dict] = []

    def log_policy(self, *, step, kind, domain=None, action=None,
                   decision=None, user_decision=None) -> None:
        self.calls.append({
            "step": step, "kind": kind, "domain": domain,
            "action": action, "decision": decision,
            "user_decision": user_decision,
        })


def test_first_time_seen_guard_blocks_on_blacklisted_url():
    """Defense-in-depth: when current_url is on the blacklist, the
    first-time-seen helper must short-circuit instead of letting the
    prompt fire."""
    from brotto_orchestrator.agent.context import AgentDeps
    from brotto_orchestrator.agent.harness import _guard_first_time_seen_blacklist
    from brotto_orchestrator.policy import Policy

    deps = AgentDeps(
        user_id="u", task="x", cdp=None, ws_send=None,
        policy=Policy(mode="secure", blacklist=["evil.com"]),
    )
    log = _FakeRunLog()

    blocked = _guard_first_time_seen_blacklist(
        deps, current_url="https://evil.com/x", run_log=log,
        step=3, action="click",
    )

    assert blocked is True
    assert deps.result is not None
    assert deps.result.failure_reason == "policy_blocked"
    assert deps.result.summary == "Blocked by policy: evil.com"
    # The audit row gets written for the compliance trail.
    assert len(log.calls) == 1
    assert log.calls[0]["kind"] == "domain_blocked"
    assert log.calls[0]["domain"] == "evil.com"
    assert log.calls[0]["decision"] == "block"


def test_first_time_seen_guard_passes_on_clean_url():
    """When the URL is NOT on the blacklist, the guard returns False
    and lets the normal first-time-seen logic proceed."""
    from brotto_orchestrator.agent.context import AgentDeps
    from brotto_orchestrator.agent.harness import _guard_first_time_seen_blacklist
    from brotto_orchestrator.policy import Policy

    deps = AgentDeps(
        user_id="u", task="x", cdp=None, ws_send=None,
        policy=Policy(mode="secure", blacklist=["evil.com"]),
    )
    log = _FakeRunLog()

    blocked = _guard_first_time_seen_blacklist(
        deps, current_url="https://safe.com/x", run_log=log,
        step=0, action="click",
    )

    assert blocked is False
    assert deps.result is None
    assert log.calls == []


def test_first_time_seen_guard_skips_in_normal_mode():
    """If somehow called when mode is not secure (defensive), the guard
    must not set a result — it should pass through. The actual block
    is the gate's job, not this helper."""
    from brotto_orchestrator.agent.context import AgentDeps
    from brotto_orchestrator.agent.harness import _guard_first_time_seen_blacklist
    from brotto_orchestrator.policy import Policy

    deps = AgentDeps(
        user_id="u", task="x", cdp=None, ws_send=None,
        policy=Policy(mode="normal", blacklist=["evil.com"]),
    )
    log = _FakeRunLog()

    blocked = _guard_first_time_seen_blacklist(
        deps, current_url="https://evil.com/x", run_log=log,
        step=0, action="click",
    )

    # check_domain_policy returns N_A in normal mode → guard passes.
    assert blocked is False
    assert deps.result is None


# ── 2.1 stricter prompt ────────────────────────────────────────────────────


def test_secure_mode_preamble_present_when_secure():
    """When secure mode is on, the prompt must include the stricter
    preamble so the LLM knows it's operating under org policy."""
    from brotto_orchestrator.agent.context import AgentDeps
    from brotto_orchestrator.agent.harness import _turn_to_prompt
    from brotto_orchestrator.agent.prompt import SECURE_MODE_PREAMBLE_LEGACY
    from brotto_orchestrator.agent.prompt import secure_mode_preamble
    from brotto_orchestrator.policy import Policy

    deps = AgentDeps(
        user_id="u", task="x", cdp=None, ws_send=None,
        policy=Policy(mode="secure", blacklist=["evil.com", "banned.io"]),
    )
    turn = _prompt_with_deps(deps)
    # Substring: the "SECURE MODE ACTIVE" banner is always present.
    assert "## SECURE MODE ACTIVE" in turn
    # The preamble interpolates the policy's actual blacklist so the LLM
    # knows what's forbidden without having to discover it.
    assert secure_mode_preamble(deps.policy) in turn
    assert "evil.com" in turn
    assert "banned.io" in turn
    # And the standard SYSTEM_PROMPT bits still appear (we prepend, not replace).
    assert "## What is your next action(s)?" in turn


def test_secure_mode_preamble_absent_when_normal():
    from brotto_orchestrator.agent.context import AgentDeps
    from brotto_orchestrator.agent.prompt import SECURE_MODE_PREAMBLE_LEGACY
    from brotto_orchestrator.policy import Policy

    deps = AgentDeps(
        user_id="u", task="x", cdp=None, ws_send=None,
        policy=Policy(mode="normal"),
    )
    turn = _prompt_with_deps(deps)
    assert "## SECURE MODE ACTIVE" not in turn


def _prompt_with_deps(deps):
    """Build the prompt with the same shape the harness uses, so we can
    assert on the result. Mirrors `_turn_to_prompt` but accepts a deps
    so we can flip secure mode per test."""
    from brotto_orchestrator.agent.context import AgentTurn, AgentDeps
    from brotto_orchestrator.agent.harness import _turn_to_prompt

    # Build a minimal AgentTurn — values irrelevant to the preamble check.
    turn = AgentTurn(
        task="x", step_number=0, scratchpad_notes="", scratchpad_entries=[],
        current_url="https://example.com", current_page_title="t",
        ax_tree="", ax_diff="", step_summaries=[],
    )
    # `_turn_to_prompt(turn)` doesn't take deps today — the secure preamble
    # wiring needs to read from somewhere. The harness will pass deps
    # through; for the unit test we monkey-patch the helper to consult
    # the deps global below.
    from brotto_orchestrator.agent import harness as h
    h._TEST_DEPS = deps
    try:
        return _turn_to_prompt(turn)
    finally:
        h._TEST_DEPS = None


# ── 2.2 sensitive-action schema + guardrail ────────────────────────────────


def test_policy_schema_has_sensitive_actions_field():
    """New field: curated list of irreversible action patterns that
    always require approval in secure mode."""
    from brotto_orchestrator.policy.schema import Policy
    assert "sensitive_actions" in Policy.model_fields


def test_policy_sensitive_actions_default_nonempty():
    from brotto_orchestrator.policy.schema import Policy
    p = Policy()
    assert isinstance(p.sensitive_actions, list)
    assert len(p.sensitive_actions) >= 3  # at least a sane default


def test_check_sensitive_action_matches_name_in_normal_mode_false():
    """Guardrail is a no-op in normal mode — even if the action name
    is in the sensitive list, secure mode is off so no approval fires."""
    from brotto_orchestrator.agent.guardrails import check_sensitive_action
    from brotto_orchestrator.policy import Policy
    p = Policy(mode="normal", sensitive_actions=["payment", "delete_record"])
    assert check_sensitive_action("payment", {"ref": "x"}, p) is False


def test_check_sensitive_action_matches_name_in_secure_mode():
    from brotto_orchestrator.agent.guardrails import check_sensitive_action
    from brotto_orchestrator.policy import Policy
    p = Policy(mode="secure", sensitive_actions=["payment", "delete_record"])
    assert check_sensitive_action("payment", {"ref": "x"}, p) is True
    assert check_sensitive_action("delete_record", {"ref": "y"}, p) is True


def test_check_sensitive_action_non_matching_action():
    from brotto_orchestrator.agent.guardrails import check_sensitive_action
    from brotto_orchestrator.policy import Policy
    p = Policy(mode="secure", sensitive_actions=["payment"])
    assert check_sensitive_action("click", {"ref": "x"}, p) is False


def test_check_sensitive_action_matches_args_keyword():
    """Some sensitive patterns show up in action_args, not the action name
    (e.g. a click with `description="delete_record"`)."""
    from brotto_orchestrator.agent.guardrails import check_sensitive_action
    from brotto_orchestrator.policy import Policy
    p = Policy(mode="secure", sensitive_actions=["payment", "delete_record"])
    # Substring match — admin's `delete_record` pattern hits the
    # `description="delete_record ..."` arg.
    assert check_sensitive_action(
        "click",
        {"ref": "btn1", "description": "delete_record permanently"},
        p,
    ) is True
    # And the absence case — a benign description doesn't trigger.
    assert check_sensitive_action(
        "click",
        {"ref": "btn1", "description": "open menu"},
        p,
    ) is False


def test_check_sensitive_action_empty_list_returns_false():
    from brotto_orchestrator.agent.guardrails import check_sensitive_action
    from brotto_orchestrator.policy import Policy
    p = Policy(mode="secure", sensitive_actions=[])
    assert check_sensitive_action("payment", {}, p) is False


# ── 2.3 visited_domains on AgentDeps ───────────────────────────────────────


def test_agent_deps_has_visited_domains():
    from brotto_orchestrator.agent.context import AgentDeps
    assert "visited_domains" in AgentDeps.__dataclass_fields__


# ── regression: terminal actions must not trigger approval prompts ─────────


def test_first_time_seen_skips_terminal_actions():
    """Regression for the bug where the agent emitting cannot_complete
    in secure mode prompted the user to approve the failure."""
    from brotto_orchestrator.agent.harness import (
        _NEVER_APPROVE, _TERMINAL_ACTIONS, _INTERNAL_ACTIONS, _QUESTION_ACTIONS,
    )
    # Every terminal / internal / question action is in the deny set.
    for a in _TERMINAL_ACTIONS | _INTERNAL_ACTIONS | _QUESTION_ACTIONS:
        assert a in _NEVER_APPROVE, f"{a} not in _NEVER_APPROVE"
    # And conversely, every UI-action IS NOT in _NEVER_APPROVE — otherwise
    # a real action would be silently skipped.
    for a in ("navigate", "click", "type_text", "scroll", "read_page_text"):
        assert a not in _NEVER_APPROVE, f"{a} wrongly in _NEVER_APPROVE"


def test_check_sensitive_action_skips_internal_actions():
    """The sensitive-action regex shouldn't match on a scratchpad write
    whose notes happen to mention 'payment'."""
    from brotto_orchestrator.agent.guardrails import check_sensitive_action
    from brotto_orchestrator.policy import Policy
    p = Policy(mode="secure", sensitive_actions=["payment"])
    assert check_sensitive_action(
        "append_scratchpad",
        {"line": "Note: looks like a payment flow"},
        p,
    ) is False
    # And the action name itself is matched (the bug case: action called
    # 'payment' regardless of args).
    assert check_sensitive_action("payment", {}, p) is True


# ── click cross-domain approval (Change 3) ──────────────────────────────────


def _mk_deps(mode="secure"):
    """Minimal AgentDeps for testing the pure cross-domain helper. The
    helper only reads `policy.mode` and `visited_domains`, so we leave
    everything else default."""
    from brotto_orchestrator.agent.context import AgentDeps
    from brotto_orchestrator.policy import Policy
    return AgentDeps(
        user_id="u", task="x", cdp=None, ws_send=None,
        policy=Policy(mode=mode),
    )


def test_should_prompt_cross_domain_click_normal_mode_no_prompt():
    """Cross-domain clicks in normal mode never prompt — that's the
    whole point of the change (secure-only gating)."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps(mode="normal")
    needs, target = _should_prompt_cross_domain_click(
        "https://google.com/", "https://mail.google.com/", deps,
    )
    assert needs is False
    assert target is None


def test_should_prompt_cross_domain_click_same_etld_no_prompt():
    """google.com → www.google.com are the same eTLD+1, no prompt."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps()
    needs, target = _should_prompt_cross_domain_click(
        "https://google.com/", "https://www.google.com/search?q=x", deps,
    )
    assert needs is False


def test_should_prompt_cross_domain_click_new_domain_prompts():
    """google.com → apple.com (different eTLD+1), apple not yet visited → prompt.
    Note: mail.google.com and google.com share google.com as eTLD+1, so
    that pair does NOT cross — same registered domain."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps()
    needs, target = _should_prompt_cross_domain_click(
        "https://google.com/search", "https://apple.com/iphone", deps,
    )
    assert needs is True
    assert target == "apple.com"


def test_should_prompt_cross_domain_click_mail_google_same_etld_no_prompt():
    """Regression: mail.google.com is NOT a different eTLD+1 from
    google.com (subdomain of the same registered domain). Clicking
    from google.com search to mail.google.com inbox must NOT prompt."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps()
    needs, target = _should_prompt_cross_domain_click(
        "https://google.com/search", "https://mail.google.com/inbox", deps,
    )
    assert needs is False


def test_should_prompt_cross_domain_click_already_visited_no_prompt():
    """If we've already approved apple.com earlier in this task
    (via navigate or click), returning there doesn't re-prompt."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps()
    deps.visited_domains.add("apple.com")
    needs, target = _should_prompt_cross_domain_click(
        "https://google.com/search", "https://apple.com/iphone", deps,
    )
    assert needs is False


def test_should_prompt_cross_domain_click_no_pre_url_no_prompt():
    """Defensive: if we don't know where we started (step_url was
    never set), don't fabricate a prompt. Limit prompt fire to cases
    where we can actually compare."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps()
    needs, target = _should_prompt_cross_domain_click(
        None, "https://mail.google.com/", deps,
    )
    assert needs is False


def test_should_prompt_cross_domain_click_unparseable_urls_no_prompt():
    """Garbage URLs fall back to safe-default (no prompt) rather than
    raising or fabricating one. Better to under-prompt than crash the
    harness on a weird URL."""
    from brotto_orchestrator.agent.harness import _should_prompt_cross_domain_click
    deps = _mk_deps()
    needs, target = _should_prompt_cross_domain_click(
        "not a url", "also not a url", deps,
    )
    assert needs is False


def test_looks_like_blacklist_hit_helper():
    """Light heuristic used to decide whether cannot_complete in secure
    mode is a policy preflight."""
    from brotto_orchestrator.agent.harness import _looks_like_blacklist_hit
    # Substring match in either direction.
    assert _looks_like_blacklist_hit("mail.google.com", "Gmail (mail.google.com) is blocked")
    assert _looks_like_blacklist_hit("evil.com", "Bad domain: evil.com is forbidden")
    # URL artefacts in the pattern are stripped before matching.
    assert _looks_like_blacklist_hit("https://mail.google.com/", "Gmail (mail.google.com) is blocked")
    # Case-insensitive.
    assert _looks_like_blacklist_hit("mail.google.com", "MAIL.GOOGLE.COM is bad")
    # No match when neither contains the other.
    assert not _looks_like_blacklist_hit("evil.com", "Could not reach server")
    # Defensive: empty inputs.
    assert not _looks_like_blacklist_hit("", "evil.com mentioned")
    assert not _looks_like_blacklist_hit("evil.com", "")


# ── persistence: user policy survives restart ─────────────────────────────


def test_persist_save_and_load(tmp_path, monkeypatch):
    """Round-trip a user policy through the disk store."""
    monkeypatch.setenv("BROTTO_USER_POLICY_DIR", str(tmp_path))
    # Reset module-level path cache by re-importing fresh.
    import importlib
    from brotto_orchestrator.policy import persist
    importlib.reload(persist)
    persist.save("user-A", {"mode": "secure", "blacklist": ["evil.com"]})
    persist.save("user-B", {"mode": "normal", "blacklist": []})
    # load by key
    a = persist.load("user-A")
    assert a is not None
    assert a["mode"] == "secure"
    assert a["blacklist"] == ["evil.com"]
    # Bookkeeping fields are added by save_if_changed.
    assert "_saved_at" in a
    assert "_content_sha256" in a
    assert persist.load("user-B")["mode"] == "normal"
    assert persist.load("user-NONEXISTENT") is None
    # load_all returns both.
    all_loaded = persist.load_all()
    assert len(all_loaded) == 2


def test_persist_atomic_no_partial_on_corruption(tmp_path, monkeypatch):
    """A corrupt JSON file doesn't bring the loader down — it just
    skips that file. Operators can inspect manually post-mortem."""
    monkeypatch.setenv("BROTTO_USER_POLICY_DIR", str(tmp_path))
    import importlib
    from brotto_orchestrator.policy import persist
    importlib.reload(persist)
    persist.save("user-X", {"mode": "secure"})
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1
    files[0].write_text("{not json")
    assert persist.load_all() == {}
    assert persist.load("user-X") is None


def test_persist_save_if_changed_skips_no_op(tmp_path, monkeypatch):
    """The user's actual ask: re-saving identical content must NOT
    re-touch the file. Otherwise the sidepanel's 'Last verified' clock
    resets on every click and we do useless disk IO."""
    monkeypatch.setenv("BROTTO_USER_POLICY_DIR", str(tmp_path))
    import importlib
    import time
    from brotto_orchestrator.policy import persist
    importlib.reload(persist)

    payload = {"mode": "secure", "blacklist": ["foo.com"]}
    # First save writes.
    assert persist.save_if_changed("user-Y", payload) is True
    mtime_before = (tmp_path / persist._key_to_filename("user-Y")).stat().st_mtime_ns
    # Same content — no write.
    time.sleep(0.05)  # ensure mtime would change if a write happened
    assert persist.save_if_changed("user-Y", payload) is False
    mtime_after = (tmp_path / persist._key_to_filename("user-Y")).stat().st_mtime_ns
    assert mtime_before == mtime_after, "no-op save touched the file"
    # A real change writes.
    assert persist.save_if_changed(
        "user-Y", {"mode": "secure", "blacklist": ["foo.com", "bar.com"]},
    ) is True
    # Re-save the same content again — no write.
    assert persist.save_if_changed(
        "user-Y", {"mode": "secure", "blacklist": ["foo.com", "bar.com"]},
    ) is False
    # Different key with same payload — IS a write (separate file).
    assert persist.save_if_changed(
        "user-Z", {"mode": "secure", "blacklist": ["foo.com"]},
    ) is True


def test_persist_load_strips_bookkeeping(tmp_path, monkeypatch):
    """Reload returns the raw JSON including bookkeeping fields, but
    the hash comparison excludes them so a save with the same visible
    payload still skips."""
    monkeypatch.setenv("BROTTO_USER_POLICY_DIR", str(tmp_path))
    import importlib
    from brotto_orchestrator.policy import persist
    importlib.reload(persist)
    payload = {"mode": "secure", "blacklist": ["a.com"]}
    persist.save_if_changed("user-K", payload)
    # Hash with bookkeeping fields stripped.
    hash_first = persist._payload_hash(
        persist.load("user-K") and {k: v for k, v in persist.load("user-K").items() if not k.startswith("_")}
    )
    # Re-save same payload — must NOT write.
    assert persist.save_if_changed("user-K", payload) is False
    # Bookkeeping fields on disk (timestamp etc.) don't change the hash.
    loaded = persist.load("user-K")
    visible = {k: v for k, v in loaded.items() if not k.startswith("_")}
    assert persist._payload_hash(visible) == hash_first

