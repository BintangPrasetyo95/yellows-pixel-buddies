"""Privacy helpers: secret redaction and sensitive-window detection. Pure Python, unit-tested.

* ``redact_secrets`` strips API keys from any text before it is logged or saved (REVIEW M9).
  ``requests`` error messages contain the full request URL, and the Gemini key used to travel in
  ``?key=...``. Session files and logs are exactly what users share in bug reports.
* ``is_sensitive_window`` decides whether Pink may take an *unprompted* screenshot (REVIEW H12):
  password managers, private/incognito windows, banking and sign-in pages are never captured
  automatically.
"""
from __future__ import annotations

import logging
import re

# Google API keys ("AIza" + 35 chars) and any key=/api_key=/token= query or JSON value.
_GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_KEY_PARAM = re.compile(r"(?i)\b((?:api[_-]?)?key|token|access_token|x-goog-api-key)(\s*[=:]\s*[\"']?)([^&\s\"',)}\]]+)")
REDACTED = "REDACTED"


def redact_secrets(text: object) -> str:
    """Return ``text`` with API keys and key=/token= values replaced by REDACTED."""
    s = str(text) if text is not None else ""
    if not s:
        return s
    s = _GOOGLE_KEY.sub(REDACTED, s)
    return _KEY_PARAM.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", s)


def contains_secret(text: object) -> bool:
    s = str(text) if text is not None else ""
    return bool(_GOOGLE_KEY.search(s) or re.search(r"(?i)[?&]key=[^&\s\"']{8,}", s))


class RedactSecretsFilter(logging.Filter):
    """Logging filter that redacts secrets from every record before any handler writes it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if contains_secret(msg):
            record.msg = redact_secrets(msg)
            record.args = ()
        return True


def install_log_redaction(logger: logging.Logger | None = None) -> None:
    """Attach RedactSecretsFilter to ``logger`` (default: root) and all of its handlers, once."""
    target = logger or logging.getLogger()
    for obj in [target, *target.handlers]:
        if not any(isinstance(f, RedactSecretsFilter) for f in obj.filters):
            obj.addFilter(RedactSecretsFilter())


# ---------------------------------------------------------------------------------------------
# Sensitive foreground windows: never screenshot these on Pink's own initiative
# ---------------------------------------------------------------------------------------------
SENSITIVE_EXES = frozenset({
    "keepass.exe", "keepassxc.exe", "1password.exe", "bitwarden.exe", "lastpass.exe", "dashlane.exe",
    "enpass.exe", "roboform.exe", "nordpass.exe", "proton pass.exe", "keeper.exe",
    "credentialuibroker.exe", "consent.exe", "logonui.exe", "lockapp.exe",
})
_SENSITIVE_TITLE = re.compile(
    r"(?i)\b(?:inprivate|incognito|private\s+(?:browsing|window)|password|passwords|passcode|kata\s+sandi|"
    r"sign\s*in|log\s*in|login|masuk\s+ke|2fa|two[- ]factor|authenticator|verification\s+code|one[- ]time\s+(?:code|password)|"
    r"bank|banking|internet\s+banking|m-?banking|paypal|credit\s+card|debit\s+card|checkout|payment|wallet|"
    r"seed\s+phrase|recovery\s+(?:phrase|key)|private\s+key)\b"
)


def is_sensitive_window(exe_name: str | None, title: str | None) -> bool:
    """True if a window should never be captured automatically (password managers, private windows,
    sign-in / banking / payment pages, Windows credential & UAC prompts)."""
    exe = (exe_name or "").strip().lower()
    if exe in SENSITIVE_EXES:
        return True
    return bool(_SENSITIVE_TITLE.search(title or ""))
