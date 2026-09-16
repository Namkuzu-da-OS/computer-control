"""Confirmation boundary for genuinely destructive operations.

Everything else (clicks, typing, launching, settings, installs) passes freely.
A gated call returns a `confirmation_required` result with a token; re-issuing
the same call with confirm=<token> executes it. Tokens expire after 5 minutes.
"""
import re
import secrets
import time

_PATTERNS = [
    r"\bformat(-volume)?\b.*\b[a-z]:", r"\bformat\s+[a-z]:", r"\bdiskpart\b", r"\bclear-disk\b", r"\bremove-partition\b",
    r"\binitialize-disk\b", r"\bbcdedit\b.*\b(delete|/deletevalue|/set)\b", r"\bcipher\s+/w", r"\bsdelete\b",
    r"\brm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\b\s+(/|~|\$home|[a-z]:\\?)\s*$", r"\brm\s+-rf\s+/\s",
    r"\bremove-item\b.*-recurse.*\b([a-z]:\\|\$env:userprofile|\$home|~)\s*['\"]?\s*$",
    r"\brd\b\s+/s.*\b[a-z]:\\?\s*$", r"\brmdir\b\s+/s.*\b[a-z]:\\?\s*$", r"\bdel\b\s+/[sq].*\b[a-z]:\\\*",
    r"\bnet\s+user\b.*\s/delete", r"\bremove-localuser\b", r"\bremove-aduser\b", r"\bdisable-computer\b",
    r"\bstop-computer\b", r"\brestart-computer\b", r"\bshutdown\b\s+/[rsp]", r"\bsystemreset\b",
    r"\bwmic\b.*\b(delete|format)\b", r"\breg\s+delete\s+hk(lm|cu|cr)\\?\s*$", r"\bremove-item\b.*\bhk(lm|cu):\\?\s*$",
    r"\bvssadmin\b.*\bdelete\b", r"\bwbadmin\b.*\bdelete\b", r"\bmanage-bde\b.*-(off|forcerecovery)",
    r"\bicacls\b.*\/reset", r"\btakeown\b.*\/r", r"\bgit\s+push\b.*--force", r"\bdrop\s+(database|table)\b",
]
_RX = [re.compile(p, re.I) for p in _PATTERNS]
_pending: dict[str, tuple[float, str]] = {}


def check(text: str) -> str | None:
    """Return a human-readable reason if `text` looks destructive, else None."""
    for rx in _RX:
        if rx.search(text or ""):
            return f"matches destructive pattern: {rx.pattern}"
    return None


def gate(text: str, confirm: str | None) -> dict | None:
    """None = proceed. dict = confirmation_required payload to return to the caller."""
    reason = check(text)
    if reason is None:
        return None
    now = time.time()
    for k, (ts, _) in list(_pending.items()):
        if now - ts > 300:
            _pending.pop(k, None)
    if confirm and confirm in _pending and _pending[confirm][1] == text:
        _pending.pop(confirm, None)
        return None
    token = secrets.token_hex(4)
    _pending[token] = (now, text)
    return {
        "confirmation_required": True,
        "reason": reason,
        "confirm_token": token,
        "how": f"Ask the user to confirm out loud, then re-run the same call with confirm='{token}' (valid 5 min).",
    }
