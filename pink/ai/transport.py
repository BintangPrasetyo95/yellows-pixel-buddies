"""HTTP timeouts for Gemini requests that carry a screenshot.

``requests`` keeps the *connect* timeout on the socket until the whole request body has been sent; the read
timeout only starts after that. A fixed 5 s connect timeout therefore also meant "upload everything in 5 s",
which a ~600 KB screenshot can't do on a slow uplink ("The write operation timed out"). The connect timeout
here is the time to open the connection plus an upload allowance for the body at a slow, assumed uplink.

No Qt, no network: pure arithmetic, tested in tests/test_upload_timeouts.py.
"""
from __future__ import annotations

import json

CONNECT_TIMEOUT_S = 5.0            # TCP + TLS handshake; offline still fails within this
MIN_UPLINK_BYTES_PER_S = 32_000    # slowest uplink we still want to work (~256 kbit/s)
MAX_UPLOAD_ALLOWANCE_S = 30.0      # never wait longer than this for an upload


def payload_size(payload: object) -> int:
    """Approximate request body size in bytes (``requests`` sends ``json=`` compactly as UTF-8)."""
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def connect_timeout(body_bytes: int) -> float:
    """Connect timeout for a request whose body is ``body_bytes`` long: handshake time plus upload allowance."""
    upload_s = max(0, body_bytes) / MIN_UPLINK_BYTES_PER_S
    return CONNECT_TIMEOUT_S + min(MAX_UPLOAD_ALLOWANCE_S, upload_s)
