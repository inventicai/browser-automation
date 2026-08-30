"""eTLD+1 extraction + pattern matching. Stdlib only.

`etld1(url)` returns the registered domain (e.g. `bank.com`,
`bank.co.uk`). Used to whitelist/blacklist whole organisations, not
individual subdomains.

`domain_matches(domain, pattern)` supports exact and `*.example.com`
suffix patterns.

# ponytail: ~50-entry embedded multi-part public-suffix list instead of
# `tldextract`. Ceiling = misses obscure ccTLDs (.museum, .coop,
# country-specific multi-part like .gov.au when it's actually two-part
# already, etc.). Upgrade = replace with
# `from tldextract import TLDExtract; TLDExtract(fetch_from=True, suffix_list_urls=())`
# and a vendored PSL snapshot. Re-validate against tests/test_policy_domains.py.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# Multi-part public-suffix fragments we recognise. Lowercase, dot-separated,
# sorted longest-first for the suffix check. Picked to cover ~95% of
# commercial banks + SaaS deployments; not exhaustive.
MULTI_PART_SUFFIXES: tuple[str, ...] = (
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "ltd.uk", "plc.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
    "co.kr", "ne.kr", "or.kr", "go.kr",
    "co.in", "net.in", "org.in", "gov.in", "ac.in",
    "co.nz", "net.nz", "org.nz", "govt.nz", "ac.nz",
    "co.za", "org.za", "net.za", "gov.za", "ac.za",
    "com.br", "net.br", "org.br", "gov.br", "edu.br",
    "com.mx", "org.mx", "gob.mx", "edu.mx",
    "com.hk", "org.hk", "edu.hk", "gov.hk",
    "com.sg", "org.sg", "gov.sg", "edu.sg",
    "com.tw", "org.tw", "gov.tw", "edu.tw",
    "co.id", "or.id", "go.id", "ac.id",
    "com.ar", "org.ar", "gov.ar",
    "com.tr", "org.tr", "gov.tr", "edu.tr",
    "com.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn",
    "co.il", "org.il", "ac.il", "gov.il",
)


def _strip_www(host: str) -> str:
    if host.startswith("www.") and host.count(".") >= 2:
        return host[4:]
    return host


def _normalize_pattern(pattern: str) -> str:
    """Strip URL artefacts so user/admin entries match consistently.

    `https://mail.google.com/`  → `mail.google.com`
    `http://evil.com/path?q=1`  → `evil.com`
    `bank.com:8080`            → `bank.com:8080`  (port kept — domain form
                                                   is rare; the user-facing
                                                   UI strips scheme/path)
    `HTTPS://Mail.Google.COM/` → `mail.google.com`

    Also handles userinfo (`https://user@host/` → strips the `user@`).

    Returns "" for input that normalises to nothing (caller treats as no-op).
    """
    if not pattern:
        return ""
    pat = pattern.strip().lower().strip(".")
    if not pat:
        return ""
    # Strip scheme: anything before `://`.
    if "://" in pat:
        pat = pat.split("://", 1)[1]
    # Strip userinfo (`user@host` → `host`).
    if "@" in pat:
        pat = pat.rsplit("@", 1)[1]
    # Strip path/query/fragment (first `/`, `?`, `#`, or `:` for port).
    for sep in ("/", "?", "#", ":"):
        if sep in pat:
            pat = pat.split(sep, 1)[0]
    return pat.strip(".")


def etld1(url: str) -> str | None:
    """Return the registered domain (eTLD+1) for a URL, or None.

    Examples:
        https://app.bank.com/path   -> "bank.com"
        https://www.bank.com        -> "bank.com"
        https://a.b.c.bank.co.uk    -> "bank.co.uk"
        mailto:user@bank.com        -> "bank.com"
        not a url / empty           -> None
    """
    if not url:
        return None
    try:
        parsed = urlparse(url if "://" in url else f"http://{url}")
    except (ValueError, TypeError):
        return None

    host = parsed.hostname or ""
    # urlparse on `mailto:user@bank.com` returns .hostname=None and .path='user@bank.com'.
    if not host:
        path = parsed.path or ""
        if "@" in path:
            host = path.rsplit("@", 1)[-1]
    host = host.lower().strip(".")
    if not host:
        return None
    # IP literals (v4/v6) aren't domains for policy purposes.
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    host = _strip_www(host)

    # Find the longest matching multi-part suffix.
    matched_suffix = ""
    for suffix in MULTI_PART_SUFFIXES:
        if host.endswith("." + suffix) or host == suffix:
            if len(suffix) > len(matched_suffix):
                matched_suffix = suffix

    labels = host.split(".")
    if matched_suffix:
        # Need at least one more label before the suffix.
        if len(labels) < 3:
            return None
        return ".".join(labels[-2 - matched_suffix.count("."):])

    # Plain n-label TLD. IPv4 / IPv6 fall through with the literal host.
    if len(labels) < 2:
        return None
    return ".".join(labels[-2:])


def domain_matches(domain: str, pattern: str) -> bool:
    """True iff `domain` matches `pattern`.

    Pattern syntax:
        "bank.com"      exact match
        "*.bank.com"    suffix wildcard (matches a.bank.com, b.bank.com, NOT bank.com)
        "*"             match all

    Patterns are normalised — scheme (`https://`), userinfo, path, query,
    fragment, and trailing dot are stripped — so a user pasting
    `https://mail.google.com/` in the sidepanel matches `mail.google.com`.
    """
    if not domain or not pattern:
        return False
    pattern = _normalize_pattern(pattern)
    if not pattern:
        return False
    domain = domain.lower().strip(".")
    if not domain:
        return False
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        suffix = pattern[2:]
        return domain.endswith("." + suffix)
    return domain == pattern
