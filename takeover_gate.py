"""Pure policy for when Pink Takeover (Desktop Cursor Control) may start, and how voice answers
to a takeover confirmation are read.

No Qt, no Win32, no network: everything here is unit-tested in tests/test_takeover_gate.py.

Background (temp/REVIEW.md C1, C4, H1): takeovers used to start whenever the model emitted a
``[desktop_action: ...]`` tag and the user's text happened to contain a word like "do" or "show".
Screenshots, dropped images and window titles can put that tag in the model's mouth, so the
decision now depends on *where the request came from* (``TurnOrigin``) and on the user's
``takeover_mode`` setting, never on incidental wording.
"""
from __future__ import annotations

import re
from enum import Enum

# ---------------------------------------------------------------------------------------------
# Modes (persisted as the "takeover_mode" setting)
# ---------------------------------------------------------------------------------------------
TAKEOVER_MODE_OFF = "off"                # no takeovers at all
TAKEOVER_MODE_SLASH_ONLY = "slash_only"  # only explicit /do, /takeover, /act, /cursor commands
TAKEOVER_MODE_ASSISTED = "assisted"      # also model-proposed takeovers, always confirmed first
TAKEOVER_MODES = (TAKEOVER_MODE_OFF, TAKEOVER_MODE_SLASH_ONLY, TAKEOVER_MODE_ASSISTED)
DEFAULT_TAKEOVER_MODE = TAKEOVER_MODE_SLASH_ONLY

SLASH_PREFIXES = ("/do ", "/takeover ", "/act ", "/cursor ")


class TurnOrigin(str, Enum):
    """Where the text that produced a Gemini reply came from."""

    TYPED = "typed"        # the user typed it into the chat box
    SLASH = "slash"        # an explicit /do-style command
    VOICE = "voice"        # push-to-talk transcript (always sent with a screenshot)
    IMAGE = "image"        # synthetic prompt for a dropped/attached image
    AMBIENT = "ambient"    # Pink's own screen peek, tray observation, cinema, song comment
    QUESTION = "question"  # answer to one of Pink's AI questions
    SHOP = "shop"          # "Ask Pink" inside the shop window


class GateDecision(Enum):
    AUTO = "auto"          # start immediately (explicit user command)
    CONFIRM = "confirm"    # show the parsed intent and ask Proceed / Cancel (default Cancel)
    DENY = "deny"          # never start; tags are stripped and logged


def normalize_mode(mode: str | None) -> str:
    m = (mode or "").strip().lower()
    return m if m in TAKEOVER_MODES else DEFAULT_TAKEOVER_MODE


def is_slash_command(text: str) -> bool:
    return (text or "").strip().lower().startswith(SLASH_PREFIXES)


# A request the user actually phrased as an instruction, at the START of their own words.
# English + Indonesian verbs. Deliberately excludes "do", "show", "act", "start" (which match
# ordinary questions like "what do you think?" or "can you show me how X works?").
# Polite/indirect openers ("help me", "I want you to", "go", "bantu aku", "coba") still need one of the
# verbs right after them, so "help me understand X" stays a question. Indonesian verbs take the
# colloquial -in / -kan suffixes ("bukain", "kirimin", "puterin").
_IMPERATIVE = re.compile(
    r"^(?:(?:hey\s+)?pink[,!:.]?\s+)?(?:please\s+|pls\s+|tolong\s+)?"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?|(?:please\s+)?help\s+me\s+(?:to\s+)?|i\s+(?:want|need)\s+you\s+to\s+"
    r"|go\s+(?:and\s+)?|bantu(?:in)?\s+(?:aku|saya|gue|gw)\s+(?:untuk\s+)?|coba\s+)?"
    r"(?:open|launch|run|click|type|press|send|reply|play|pause|search|go\s+to|switch\s+to|close|quit|navigate\s+to|message|"
    r"buka(?:in|kan)?|jalan(?:in|kan)|put(?:a|e)r(?:in|kan)?|kirim(?:in|kan)?|bal(?:a|e)s(?:in|kan)?|cari(?:in|kan)?|"
    r"klik(?:in)?|ketik(?:in|kan)?|tutup(?:in)?|pergi\s+ke)\b"
)


def is_imperative_request(user_text: str) -> bool:
    return bool(_IMPERATIVE.match((user_text or "").strip().lower()))


def takeover_decision(user_text: str, origin: TurnOrigin | str, had_visual: bool, mode: str | None) -> GateDecision:
    """Decide what to do with a takeover the model proposed (or the user commanded).

    * ``off``: always DENY.
    * explicit slash command (origin SLASH or text starting with /do etc.): AUTO.
    * ``slash_only``: everything else is DENY.
    * ``assisted``: only turns the user made themselves (TYPED or VOICE), whose own words open with
      an imperative request, may CONFIRM. Synthetic prompts ("[User dropped an image ...]"),
      ambient, question, image and shop turns are always DENY. A turn that carried a screenshot or
      image never auto-starts: it can at most CONFIRM, and the confirmation shows the parsed intent.
    """
    mode = normalize_mode(mode)
    if mode == TAKEOVER_MODE_OFF:
        return GateDecision.DENY

    try:
        origin = TurnOrigin(origin)
    except ValueError:
        return GateDecision.DENY

    text = (user_text or "").strip()
    if origin is TurnOrigin.SLASH or (origin in (TurnOrigin.TYPED, TurnOrigin.VOICE) and is_slash_command(text)):
        return GateDecision.AUTO

    if mode == TAKEOVER_MODE_SLASH_ONLY:
        return GateDecision.DENY

    if origin not in (TurnOrigin.TYPED, TurnOrigin.VOICE):
        return GateDecision.DENY
    if text.startswith("["):  # synthetic prompt built by the app, not the user's words
        return GateDecision.DENY
    if not is_imperative_request(text):
        return GateDecision.DENY
    return GateDecision.CONFIRM  # had_visual or not: model-proposed takeovers are always confirmed


_HINT_MAX_CHARS = 160


def dropped_takeover_hint(user_text: str, origin: TurnOrigin | str, mode: str | None, language: str = "en") -> str | None:
    """The line Pink adds when the model proposed a takeover that ``takeover_decision`` DENIED.

    Without it Pink says "Fine, I'll open it!" and then nothing happens. The hint offers the explicit
    ``/do`` command built from the user's OWN words, never from the model's tag, so content on screen
    can't put a command in Pink's mouth. Only for the user's own typed/voice turns and only while takeovers
    are switched on; every other case returns None.
    """
    mode = normalize_mode(mode)
    if mode == TAKEOVER_MODE_OFF:
        return None
    try:
        origin = TurnOrigin(origin)
    except ValueError:
        return None
    if origin not in (TurnOrigin.TYPED, TurnOrigin.VOICE):
        return None
    text = " ".join((user_text or "").split())
    if not text or text.startswith("[") or is_slash_command(text):
        return None
    if len(text) > _HINT_MAX_CHARS:
        text = text[:_HINT_MAX_CHARS].rstrip() + "…"
    if language == "id":
        return f"* ...eh, tunggu! Yang itu aku belum bisa langsung ambil alih. Ketik: /do {text}"
    return f"* ...wait! I can't take over for that one on my own. Type: /do {text}"


# ---------------------------------------------------------------------------------------------
# Voice answers to a confirmation prompt
# ---------------------------------------------------------------------------------------------
_NEGATIVE = frozenset({
    "no", "nope", "nah", "cancel", "stop", "abort", "don't", "dont", "not", "never", "wait", "halt",
    "jangan", "batal", "batalkan", "tidak", "enggak", "nggak", "gak", "ga", "ogah", "hentikan", "belum", "berhenti",
})
_POSITIVE = frozenset({
    "yes", "yeah", "yep", "yup", "proceed", "confirm", "confirmed", "ok", "okay", "sure", "go",
    "ya", "iya", "lanjut", "lanjutkan", "oke", "gas", "sip", "setuju", "boleh", "betul", "benar",
})
_FILLER = frozenset({"please", "do", "it", "ahead", "pink", "now", "tolong", "aja", "dong", "deh"})
_MAX_YES_WORDS = 4


def classify_yes_no(text: str) -> str | None:
    """Return "yes", "no", or None (ambiguous: ask again).

    Words, not substrings: any negation wins (fail safe), and "yes" is only accepted for a short
    reply made of affirmatives and filler. "No, don't send it", "I'm not sure", "Jangan dilanjut ya"
    and "hentikan, bahaya!" are all "no"; "look at that" is ambiguous, not "ok".
    """
    words = re.findall(r"[a-z']+", (text or "").lower().replace("’", "'"))
    if not words:
        return None
    if any(w in _NEGATIVE or w.endswith("n't") for w in words):
        return "no"
    if len(words) <= _MAX_YES_WORDS and any(w in _POSITIVE for w in words) and all(w in _POSITIVE or w in _FILLER for w in words):
        return "yes"
    return None
