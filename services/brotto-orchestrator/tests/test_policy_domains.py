"""eTLD+1 extraction + pattern matching."""

from __future__ import annotations

from brotto_orchestrator.policy.domains import domain_matches, etld1


# ── etld1 ────────────────────────────────────────────────────────────────────


def test_etld1_simple_com():
    assert etld1("https://app.bank.com/path") == "bank.com"


def test_etld1_www_stripped():
    assert etld1("https://www.bank.com/login") == "bank.com"


def test_etld1_root_apex():
    assert etld1("https://bank.com") == "bank.com"


def test_etld1_deep_subdomain():
    assert etld1("https://a.b.c.bank.com/x") == "bank.com"


def test_etld1_multi_part_uk():
    assert etld1("https://app.bank.co.uk/login") == "bank.co.uk"


def test_etld1_deep_multi_part():
    assert etld1("https://a.b.c.bank.co.uk") == "bank.co.uk"


def test_etld1_au():
    assert etld1("https://www.bank.com.au") == "bank.com.au"


def test_etld1_jp():
    assert etld1("https://example.co.jp/path") == "example.co.jp"


def test_etld1_url_without_scheme():
    assert etld1("app.bank.com/path") == "bank.com"


def test_etld1_mailto():
    assert etld1("mailto:user@bank.com") == "bank.com"


def test_etld1_idn_punycode():
    # bücher.de in punycode; urlparse preserves case but we lowercase.
    assert etld1("https://xn--bcher-kva.example/p") == "xn--bcher-kva.example"


def test_etld1_ip_returns_none():
    # IP addresses shouldn't be treated as domains for policy purposes.
    assert etld1("http://1.2.3.4/foo") is None


def test_etld1_empty():
    assert etld1("") is None


def test_etld1_garbage():
    assert etld1("not a url at all") is None


def test_etld1_single_label():
    assert etld1("http://localhost/foo") is None


# ── domain_matches ───────────────────────────────────────────────────────────


def test_match_exact():
    assert domain_matches("bank.com", "bank.com")
    assert not domain_matches("app.bank.com", "bank.com")  # exact is exact


def test_match_wildcard_suffix():
    assert domain_matches("app.bank.com", "*.bank.com")
    assert domain_matches("a.b.bank.com", "*.bank.com")
    assert not domain_matches("bank.com", "*.bank.com")  # wildcard requires subdomain


def test_match_wildcard_all():
    assert domain_matches("anything.test", "*")


def test_match_case_insensitive():
    assert domain_matches("Bank.COM", "bank.com")
    assert domain_matches("app.BANK.com", "*.bank.COM")


def test_match_empty():
    assert not domain_matches("", "bank.com")
    assert not domain_matches("bank.com", "")


def test_match_with_whitespace_pattern():
    assert domain_matches("bank.com", "  bank.com  ")


# ── URL-form pattern normalisation (the actual bug) ─────────────────────────


def test_match_url_with_scheme_and_path():
    # User typed `https://mail.google.com/` in the sidepanel.
    # Gate must normalise before matching the hostname.
    assert domain_matches("mail.google.com", "https://mail.google.com/")


def test_match_url_http_scheme():
    assert domain_matches("evil.com", "http://evil.com/login?x=1")


def test_match_url_uppercase_scheme():
    assert domain_matches("MAIL.GOOGLE.COM", "HTTPS://Mail.Google.com/")


def test_match_url_with_port():
    assert domain_matches("bank.com", "https://bank.com:8080/x")


def test_match_url_with_userinfo():
    assert domain_matches("evil.com", "https://user@evil.com/path")


def test_wildcard_url_form():
    assert domain_matches("app.bank.com", "https://*.bank.com/")


def test_empty_pattern_after_normalise_returns_false():
    assert not domain_matches("bank.com", "https://")
    assert not domain_matches("bank.com", "///")
