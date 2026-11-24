"""Pure text understanding: durations, clock times, dates, AFK / focus intents, goal values (plan 8.4, REVIEW T2/T4).

No Qt, no torch, no app state: tests import this directly, and so do yellows_pixel_buddies.py and shop_window.py.
"""
from __future__ import annotations

import datetime
import re

import takeover_gate


_DURATION_UNITS = (
    (r"hours?|hrs?|jam|h", 3600),
    (r"minutes?|mins?|menit|m", 60),
    (r"seconds?|secs?|detik|s", 1),
)


_DURATION_PART = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(u for u, _ in _DURATION_UNITS) + r")(?![a-z])"
)


def _duration_unit_seconds(unit: str) -> int:
    for pattern, secs in _DURATION_UNITS:
        if re.fullmatch(pattern, unit):
            return secs
    return 0


def parse_duration_string(text: str) -> int | None:
    """Parse a duration into seconds: '25m', '15min', '1h30m', '1m30s', '1.5m', '2 hours and 15 minutes',
    '45s', '10' (bare number = minutes), Indonesian '15 menit', '1 jam', '30 detik' (REVIEW M14)."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t.isdigit():
        return int(t) * 60
    m_hm = re.fullmatch(r"(\d+)\s*h(?:ours?|rs?)?\s*(\d{1,2})", t)   # '1h30' = 1 h 30 min
    if m_hm:
        return int(m_hm.group(1)) * 3600 + int(m_hm.group(2)) * 60
    t = re.sub(r"\b(?:and|dan)\b|,(?!\d)", " ", t)
    parts = list(_DURATION_PART.finditer(t))
    if not parts or _DURATION_PART.sub("", t).strip():
        return None                     # unknown words left over -> not a duration
    total = sum(float(m.group(1).replace(",", ".")) * _duration_unit_seconds(m.group(2)) for m in parts)
    total_s = int(round(total))
    return total_s if total_s > 0 else None


_MERIDIEM = r"a\.?m\.?|p\.?m\.?|pagi|siang|sore|malam"


def parse_clock_time(text: str) -> tuple[int, int] | None:
    """Parse a clock time into (hour, minute): '14:30', '2:30pm', '7.30 pm', '7:30 a.m.', '8am', '08:00',
    Indonesian '7 malam', '07.30 pagi', 'jam 3 sore' (REVIEW M14)."""
    t = (text or "").strip().lower()
    t = re.sub(r"^(?:at|jam|pukul|pkl\.?)\s+", "", t)
    m12 = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*(" + _MERIDIEM + r")", t)
    if m12:
        hour = int(m12.group(1))
        minute = int(m12.group(2) or 0)
        mer = m12.group(3).replace(".", "")
        if not (1 <= hour <= 12 and 0 <= minute < 60):
            return None
        if mer in ("pm", "sore", "malam") or (mer == "siang" and hour < 10):
            if hour < 12:
                hour += 12
            elif mer == "malam":        # '12 malam' = midnight
                hour = 0
        elif mer in ("am", "pagi") and hour == 12:
            hour = 0
        return (hour, minute)
    m24 = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?::\d{2})?", t)
    if m24:
        hour, minute = int(m24.group(1)), int(m24.group(2))
        if 0 <= hour < 24 and 0 <= minute < 60:
            return (hour, minute)
    return None


def nl_alarm_probe(text: str) -> bool:
    """True if ``text`` is a plain-language alarm request ('set an alarm for 7:30 am ...')."""
    return bool(re.match(
        r"^(?:please\s+)?(?:set\s+(?:an?\s+)?)?alarm(?:\s+(?:for|at))?\s+\d{1,2}(?:[:.]\d{2})?",
        (text or "").strip(), re.IGNORECASE,
    ))


def split_leading_value(text: str, parser, max_tokens: int = 4) -> tuple[str | None, str]:
    """Split '<value> <label...>' where the value may span several words ('1 hour', '7:30 PM').

    Tries the longest leading run of up to ``max_tokens`` words that ``parser`` accepts and returns
    (value_text, rest). Used by /timer and /alarm, which used to split on the first space and so read
    '/timer 1 hour' as 1 minute and '/alarm 7:30 PM' as 07:30 (REVIEW M14).
    """
    toks = (text or "").split()
    for n in range(min(max_tokens, len(toks)), 0, -1):
        head = " ".join(toks[:n])
        if parser(head) is not None:
            return head, " ".join(toks[n:])
    return None, (text or "").strip()


def _looks_like_instruction(clean: str) -> bool:
    """A command or a request for Pink to do something: never an announcement about the user."""
    if clean.startswith("/"):
        return True
    return takeover_gate.is_imperative_request(clean)


def check_is_departure_message(text: str) -> bool:
    """Return True if the text indicates the user is leaving / stepping away / going AFK.

    Phrases must actually announce leaving (REVIEW H21): "I'm going to test the build", "I need to run the
    tests" or "reply to Mom saying bye" are ordinary requests, not goodbyes.
    """
    clean = text.strip().lower().replace("’", "'")
    if not clean:
        return False
    if clean in ("/afk", "/away", "/brb", "/bye", "/leave", "/gtg", "/g2g", "/gotta_go"):
        return True
    if clean.strip(" .!") in ("afk", "brb", "bbl", "gtg", "g2g", "bye", "goodbye", "bye bye", "cya", "farewell", "ttyl",
                              "dadah", "pamit", "otw"):
        return True
    if _looks_like_instruction(clean):
        return False
    if re.search(r"\b(?:you|u|they|we|he|she)\s+(?:have|got|need|must|gotta)", clean):
        return False
    end = r"\s*(?:now|soon|asap|for\s+(?:a\s+bit|a\s+while|now|today|tonight))?\s*[.!,]*\s*(?:bye[!. ]*)?$"
    patterns = [
        r"\b(?:i\s+)?(?:have|got|need|must)\s+to\s+(?:go|leave|head\s+out|bounce|step\s+out)\b(?!\s+(?:and|through|over|back|with|for\s+it))",
        r"\b(?:i\s+)?(?:have|got|need|must)\s+to\s+run" + end,          # '...need to run' only as a sign-off
        r"\b(?:i\s+)?gotta\s+(?:go|leave|head\s+out|bounce|step\s+out)\b",
        r"\b(?:i\s+)?gotta\s+run" + end,
        r"\b(?:i'?m|i\s+am)\s+(?:leaving|heading\s+out|logging\s+off|signing\s+off|"
        r"going\s+(?:out|away|offline|home|to\s+(?:sleep|bed|work|school|class|the\s+gym)))\b",
        r"\b(?:i'?m|i\s+am)\s+(?:off|going|gonna\s+go)" + end,
        r"\b(?:going\s+)?afk\b",
        r"\b(?:brb|be\s+right\s+back|bbl)\b",
        r"\b(?:gtg|g2g)\b",
        r"\bstepping\s+(?:away|out)\b",
        # goodbyes only when they close the message
        r"(?:^|[.!,;]\s*|\b(?:ok(?:ay)?|alright|well)\s+)(?:good\s*bye|bye(?:\s*bye)?|farewell|see\s+ya|see\s+you(?:\s+(?:later|soon|tomorrow))?|"
        r"cya|ttyl|talk\s+to\s+you\s+later|good\s*night)[!. ]*$",
        # Indonesian
        r"\b(?:aku|saya|gue|gw)\s+(?:pergi|cabut|pamit|tidur|off)\s+dulu\b",
        r"\b(?:mau|harus)\s+(?:pergi|cabut|tidur|keluar)(?:\s+dulu)?" + end,
        r"\b(?:sampai\s+jumpa|dadah|pamit\s+dulu)\b",
    ]
    return any(re.search(pat, clean) for pat in patterns)


def check_is_return_message(text: str) -> bool:
    """Return True if the text indicates the user has returned from being away.

    Requires the user to be the one returning (REVIEW H21): "my API call returned 500" is not a return.
    """
    clean = text.strip().lower().replace("’", "'")
    if not clean:
        return False
    if clean in ("/back", "/return", "/here", "/im_back"):
        return True
    if clean.strip(" .!") in ("back", "im back", "i'm back", "i am back", "i returned", "i have returned", "i'm here",
                              "aku balik", "aku kembali", "udah balik", "sudah balik", "sudah kembali"):
        return True
    if clean.startswith("/"):
        return False
    patterns = [
        r"\b(?:i'?m|i\s+am)\s+back\b",
        r"\bi\s+(?:have\s+|'ve\s+)?returned\b(?!\s+(?:the|a|an|my|your|it|them|this|that)\b)",
        r"\bi\s+(?:came|got)\s+back\b",
        r"^back\s+(?:now|again|from)\b",
        r"\b(?:aku|saya|gue|gw)\s+(?:udah\s+|sudah\s+)?(?:balik|kembali|pulang)\b",
    ]
    return any(re.search(pat, clean) for pat in patterns)


DEFAULT_FOCUS_ANNOYANCE_DURATION_S: float = 8 * 60.0  # 8 minutes


_NOT_PINK_FOCUS = re.compile(r"focus\s+assist|windows\s+focus|focus\s+session|focus\s+time\b|focus\s+on\s+(?:the|this|that|my)\s+\w+\s+(?:window|tab|app)")


_QUESTION_OR_REQUEST = re.compile(
    r"^(?:what|how|why|when|where|which|who|is|does|do|can|could|would|should|will|please|pls|pink[,!:]?|hey|help|tell\s+me|"
    r"turn\s+(?:on|off)|enable|disable|open|set\s+up|show\s+me|explain)\b"
)


def check_is_focus_message(text: str) -> tuple[bool, float]:
    """Return (True, duration_seconds) if the user says THEY are focusing now.

    Defaults to 8 minutes (480.0 seconds). Questions, requests and Windows "Focus assist" talk don't count, and
    the phrasing must be about the user ("I need to focus"), not "you need to focus" or "I'm locked in my
    account" (REVIEW M13).
    """
    clean = text.strip().lower().replace("’", "'")
    if not clean:
        return False, 0.0

    # Slash commands
    if clean.startswith(("/focus", "/focusing", "/deepwork", "/lockin")):
        m_dur = re.search(r"/(?:focus|focusing|deepwork|lockin)\s+(\d+)\s*(m|min|minutes)?\b", clean)
        if m_dur:
            mins = float(m_dur.group(1))
            return True, max(1.0, mins) * 60.0
        return True, DEFAULT_FOCUS_ANNOYANCE_DURATION_S
    if clean.startswith("/"):
        return False, 0.0

    if _QUESTION_OR_REQUEST.search(clean) or _NOT_PINK_FOCUS.search(clean) or clean.endswith("?"):
        return False, 0.0

    patterns = [
        r"\b(?:i'?m|i\s+am)\s+(?:trying\s+to\s+focus|focusing|in\s+focus\s+mode|entering\s+focus\s+mode|doing\s+deep\s+work)\b",
        r"^(?:(?:i'?m\s+)?(?:try|trying)\s+to\s+focus)\b",
        r"\bi\s+(?:really\s+)?(?:need|have|got|gotta|want)\s+to\s+focus\b",
        r"^(?:need|gotta|have)\s+to\s+focus\b",
        r"\bi'?m\s+(?:gonna|going\s+to)\s+focus\b",
        r"^(?:gonna|going\s+to)\s+focus\b",
        r"\blet\s+me\s+focus\b",
        r"^focusing\s+(?:on|right\s+now|here|today|now)\b",
        r"^(?:focus\s+mode|deep\s+work)(?:\s+(?:on|time|now))?[.!]*$",
        r"\b(?:i'?m|i\s+am)\s+locked\s+in(?!\s+(?:my|the|a|an|this|that|your)\b)",
        r"^(?:locking\s+in|locked\s+in)[.!]*$",
        r"^(?:focusing|trying\s+to\s+focus)[.!]?$",
        r"\b(?:aku|saya|gue|gw)\s+(?:mau|lagi|harus)\s+fokus\b",
    ]
    for pat in patterns:
        if re.search(pat, clean):
            # Check if custom minutes mentioned, e.g. "trying to focus for 15 minutes"
            m_dur = re.search(r"\bfor\s+(\d+)\s*(?:m|min|minutes?|menit)\b", clean)
            if m_dur:
                mins = float(m_dur.group(1))
                return True, max(1.0, mins) * 60.0
            return True, DEFAULT_FOCUS_ANNOYANCE_DURATION_S

    return False, 0.0


def check_is_unfocus_message(text: str) -> bool:
    """Return True if the user explicitly announces they are done focusing (not a question or a
    Windows "Focus assist" request) (REVIEW M13)."""
    clean = text.strip().lower().replace("’", "'")
    if not clean:
        return False
    if clean in ("/unfocus", "/stopfocus", "/done_focus", "/end_focus"):
        return True
    if clean.startswith("/") or _NOT_PINK_FOCUS.search(clean) or clean.endswith("?"):
        return False
    if re.search(r"^(?:what|how|why|can|could|would|please|pink[,!:]?|help|tell\s+me|turn|enable|disable)\b", clean):
        return False
    patterns = [
        r"\b(?:i'?m\s+|i\s+am\s+|i'?ve\s+)?(?:done|finished|stopped)\s+focusing\b",
        r"^(?:stop|end|cancel)\s+focus(?:\s+mode)?[.!]*$",
        r"\b(?:i'?m\s+|i\s+am\s+)out\s+of\s+focus\s+mode\b",
        r"^(?:focus\s+mode\s+(?:off|over|done))[.!]*$",
        r"\b(?:aku|saya|gue|gw)\s+(?:udah|sudah|selesai)\s+fokus\b",
    ]
    return any(re.search(pat, clean) for pat in patterns)


def evaluate_goal_value(text: str) -> int:
    """Pink decides what a personal goal/milestone is worth (awarding between P$ 03 and P$ 08)."""
    clean = (text or "").lower()
    score = 4
    major_kws = [
        "finish", "complete", "publish", "ship", "launch", "exam", "thesis",
        "marathon", "project", "degree", "clean", "build", "develop", "refactor",
        "gym", "workout", "fitness", "run", "exercise", "learn", "study",
        "write", "chapter", "release", "portfolio", "presentation", "assignment",
        "win", "champion", "nationals", "#1", "first"
    ]
    score += sum(1 for kw in major_kws if kw in clean)
    if len(clean.split()) >= 6:
        score += 1
    if len(clean) >= 35:
        score += 1
    trivial_kws = ["water", "drink", "check", "eat", "snack", "stretch", "breathe", "nap"]
    if any(kw in clean for kw in trivial_kws):
        score -= 1
    return max(3, min(8, score))


_MONTH_NAMES = {
    "jan": 1, "january": 1, "januari": 1, "feb": 2, "february": 2, "februari": 2, "mar": 3, "march": 3, "maret": 3,
    "apr": 4, "april": 4, "may": 5, "mei": 5, "jun": 6, "june": 6, "juni": 6, "jul": 7, "july": 7, "juli": 7,
    "aug": 8, "august": 8, "agu": 8, "agt": 8, "agustus": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "okt": 10, "oktober": 10, "nov": 11, "november": 11,
    "dec": 12, "december": 12, "des": 12, "desember": 12,
}


_WEEKDAY_NAMES = (
    ("monday", "senin"), ("tuesday", "selasa"), ("wednesday", "rabu"), ("thursday", "kamis"),
    ("friday", "jumat"), ("saturday", "sabtu"), ("sunday", "minggu"),
)


def parse_target_date(text: str | None, day_first: bool | None = None) -> str | None:
    """Parse a date string or relative duration into ISO YYYY-MM-DD format.

    Numeric dates: if one part can only be a day (> 12) the order is unambiguous; otherwise ``day_first``
    decides (pass True for Indonesian users, who write 05/12/2026 for 5 December). Indonesian month names and
    'besok' / 'lusa' / 'minggu depan' / 'bulan depan' are understood, and a date whose year was written
    explicitly is never pushed into next year (REVIEW L8).
    """
    clean = (text or "").strip().lower()
    if not clean or clean in ("none", "null", "clear", "cancel", "remove", "no", "off"):
        return None

    clean = re.sub(r"^(?:by|on|deadline|target|until|sebelum|tanggal|tgl\.?)[:\s]*", "", clean).strip()
    today = datetime.date.today()

    m_iso = re.match(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$", clean)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        try:
            return datetime.date(y, m, d).isoformat()
        except ValueError:
            return None

    m_num = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", clean)
    if m_num:
        a, b, y = int(m_num.group(1)), int(m_num.group(2)), int(m_num.group(3))
        if a > 12 and b <= 12:
            d, m = a, b
        elif b > 12 and a <= 12:
            m, d = a, b
        elif day_first:
            d, m = a, b
        else:
            m, d = a, b
        try:
            return datetime.date(y, m, d).isoformat()
        except ValueError:
            return None

    m_rel = re.match(r"^(?:in\s+|dalam\s+)?(\d+)\s*(days?|d|hari)$", clean)
    if m_rel:
        return (today + datetime.timedelta(days=int(m_rel.group(1)))).isoformat()

    m_rel_w = re.match(r"^(?:in\s+|dalam\s+)?(\d+)\s*(weeks?|w|minggu|pekan)$", clean)
    if m_rel_w:
        return (today + datetime.timedelta(weeks=int(m_rel_w.group(1)))).isoformat()

    m_rel_m = re.match(r"^(?:in\s+|dalam\s+)?(\d+)\s*(months?|m|bulan)$", clean)
    if m_rel_m:
        return (today + datetime.timedelta(days=int(m_rel_m.group(1)) * 30)).isoformat()

    if clean in ("tomorrow", "tmrw", "besok"):
        return (today + datetime.timedelta(days=1)).isoformat()
    if clean in ("lusa",):
        return (today + datetime.timedelta(days=2)).isoformat()
    if clean in ("next week", "minggu depan", "pekan depan"):
        return (today + datetime.timedelta(days=7)).isoformat()
    if clean in ("next month", "bulan depan"):
        return (today + datetime.timedelta(days=30)).isoformat()

    tokens = re.findall(r"[a-zA-Z]+|\d+", clean)
    month_val = None
    day_val = None
    year_val = today.year
    year_explicit = False
    for tok in tokens:
        if tok in _MONTH_NAMES:
            month_val = _MONTH_NAMES[tok]
        elif tok.isdigit():
            v = int(tok)
            if v > 1000:
                year_val = v
                year_explicit = True
            elif day_val is None and 1 <= v <= 31:
                day_val = v
    if month_val and day_val:
        try:
            d_res = datetime.date(year_val, month_val, day_val)
            if d_res < today and not year_explicit:
                d_res = datetime.date(year_val + 1, month_val, day_val)
            return d_res.isoformat()
        except ValueError:
            return None

    words = set(tokens)
    for idx, names in enumerate(_WEEKDAY_NAMES):
        if words & set(names):
            days_ahead = (idx - today.weekday()) % 7
            if days_ahead <= 0 or "next" in words or "depan" in words:
                days_ahead += 7
            return (today + datetime.timedelta(days=days_ahead)).isoformat()

    return None


def evaluate_task_value(text: str) -> int:
    """Pink evaluates a task's worth between P$ 1 and P$ 4 based on effort, complexity, and scope."""
    clean = (text or "").strip().lower()
    if not clean:
        return 1

    words = re.findall(r"[a-zA-Z0-9_]+", clean)
    if not words:
        return 1

    word_set = set(words)
    score = 2  # Baseline reward for standard daily chores

    # 1. High-complexity / Heavy cognitive or heavy manual labor (+2)
    heavy_kws = {
        "code", "coding", "program", "programming", "develop", "dev", "build", "deploy",
        "deployment", "refactor", "refactoring", "algorithm", "database", "sql", "migration",
        "infrastructure", "infra", "architecture", "thesis", "dissertation", "exam", "finals",
        "midterm", "audit", "presentation", "slides", "pipeline", "backend", "frontend",
        "fullstack", "security", "docker", "kubernetes", "deepwork", "assignment", "paper"
    }
    if any(w in word_set for w in heavy_kws):
        score += 2

    # 2. Medium-complexity / Substantial chores (+1)
    medium_kws = {
        "study", "studying", "homework", "research", "analyze", "analysis", "review",
        "write", "writing", "draft", "article", "essay", "chapter", "documentation", "docs",
        "clean", "cleaning", "organize", "organizing", "declutter", "vacuum", "mop", "laundry",
        "cook", "cooking", "mealprep", "bake", "baking", "workout", "exercise", "gym",
        "fitness", "run", "running", "cardio", "budget", "finance", "taxes", "debug",
        "debugging", "test", "testing", "practice", "rehearse", "design", "figma",
        "wireframe", "read", "reading", "translate", "translation", "groceries", "grocery"
    }
    if any(w in word_set for w in medium_kws):
        score += 1

    # 3. Action / Execution commitment verbs (+1)
    commitment_kws = {
        "finish", "complete", "completed", "submit", "submitted", "publish", "published",
        "ship", "shipped", "finalize", "finalized", "implement", "implemented", "solve", "solved"
    }
    if any(w in word_set for w in commitment_kws):
        score += 1

    # 4. Detail & specificity bonus (+1 if user clearly defined scope)
    if len(words) >= 6 or len(clean) >= 32:
        score += 1

    # 5. Micro-habits & trivial actions (-1, but min 1)
    trivial_kws = {
        "water", "drink", "sip", "snack", "eat", "bite", "stretch", "breathe",
        "blink", "afk", "glance", "check", "tap", "nap", "brush", "floss", "rest"
    }
    if any(w in word_set for w in trivial_kws):
        score -= 1

    return max(1, min(4, score))
