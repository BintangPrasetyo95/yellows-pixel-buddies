"""Uploads on a slow uplink (found in 0.9.9.0 manual QA, Task 4 Step 2).

``requests`` applies the *connect* timeout until the whole request body is sent. With a fixed 5 s, a ~600 KB
takeover screenshot on a ~64 KB/s uplink died every time with "The write operation timed out", and the vision
agent then re-sent the same upload to six more models. The connect timeout now grows with the body size, and a
network error is retried once on the same model instead of hopping models.
"""
from __future__ import annotations

import logging

import pytest
import requests

import action_planner
from pink.ai import transport

SCREENSHOT_B64 = "A" * 600_000   # the size of a typical takeover screenshot


# ------------------------------------------------------------------ pink.ai.transport (pure)

def test_small_request_keeps_the_fast_connect_timeout():
    assert transport.connect_timeout(0) == transport.CONNECT_TIMEOUT_S == 5.0
    assert transport.connect_timeout(2_000) < 5.1


def test_connect_timeout_grows_with_the_upload():
    # 600 KB at the assumed minimum uplink (32 KB/s) needs ~19 s on top of the connection itself.
    assert transport.connect_timeout(600_000) == pytest.approx(5.0 + 600_000 / transport.MIN_UPLINK_BYTES_PER_S)
    assert transport.connect_timeout(600_000) >= 20.0


def test_connect_timeout_is_capped():
    assert transport.connect_timeout(10**9) == transport.CONNECT_TIMEOUT_S + transport.MAX_UPLOAD_ALLOWANCE_S


def test_payload_size_counts_the_image():
    small = {"contents": [{"parts": [{"text": "hi"}]}]}
    big = {"contents": [{"parts": [{"text": "hi"}, {"inlineData": {"data": SCREENSHOT_B64}}]}]}
    assert transport.payload_size(small) < 200
    assert transport.payload_size(big) > 600_000


# ------------------------------------------------------------------ main chat (GeminiWorkerThread)

def test_chat_request_timeout_scales_with_body_and_respects_deadline():
    import yellows_pixel_buddies as ypb

    assert ypb.request_timeout(None, body_bytes=600_000)[0] == transport.connect_timeout(600_000)
    # never past the request's overall deadline (REVIEW M19: offline chat must still give up in time)
    connect, read = ypb.request_timeout(110.0, now=100.0, body_bytes=10**9)
    assert connect <= 10.0 and read == 10.0


def test_chat_and_question_workers_scale_connect_timeout_for_screenshots(qapp, monkeypatch):
    import yellows_pixel_buddies as ypb

    seen = []

    def post(url, **kw):
        seen.append(kw["timeout"])
        raise requests.exceptions.ConnectionError("offline")

    monkeypatch.setattr(ypb.requests, "post", post)
    chat = ypb.GeminiWorkerThread(api_key="k", user_prompt="look", system_instruction="sys", history=[],
                                  screenshot_b64=SCREENSHOT_B64)
    chat.run()
    assert seen and seen[0][0] >= 20.0 and seen[0][1] <= ypb.GEMINI_TIMEOUT_S

    seen.clear()
    question = ypb.GeminiQuestionWorkerThread(api_key="k", user_prompt="q", system_instruction="sys",
                                              screenshot_b64=SCREENSHOT_B64)
    question.run()
    assert seen and seen[0][0] >= 20.0 and seen[0][1] <= ypb.GEMINI_TIMEOUT_S


# ------------------------------------------------------------------ vision agent (action_planner)

class _Resp:
    status_code = 200
    headers: dict = {}
    text = ""

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": '{"action": "done"}'}]}, "finishReason": "STOP"}]}


def _call():
    return action_planner._call_gemini_json("sys", "user", SCREENSHOT_B64, api_key="k", model="m1")


def test_vision_upload_gets_a_size_based_connect_timeout(monkeypatch):
    seen = []
    monkeypatch.setattr(action_planner.requests, "post", lambda url, **kw: seen.append(kw["timeout"]) or _Resp())
    assert _call() == {"action": "done"}
    connect, read = seen[0]
    assert connect >= 20.0 and read == action_planner.GEMINI_READ_TIMEOUT_S


def test_network_error_retries_same_model_once_then_gives_up(monkeypatch, caplog):
    urls = []

    def post(url, **kw):
        urls.append(url)
        raise requests.exceptions.ConnectionError("('Connection aborted.', TimeoutError('The write operation timed out'))")

    monkeypatch.setattr(action_planner.requests, "post", post)
    with caplog.at_level(logging.WARNING, logger=action_planner.log.name):
        assert _call() is None
    assert len(urls) == 2 and urls[0] == urls[1] and "/models/m1:" in urls[0]   # no hopping through fallbacks
    assert "write operation timed out" in caplog.text                           # the cause is in the log


def test_network_error_then_success_on_retry(monkeypatch):
    calls = []

    def post(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("reset")
        return _Resp()

    monkeypatch.setattr(action_planner.requests, "post", post)
    assert _call() == {"action": "done"} and len(calls) == 2


def test_slow_model_still_falls_back_to_the_next_model(monkeypatch):
    urls = []

    def post(url, **kw):
        urls.append(url)
        if len(urls) == 1:
            raise requests.exceptions.ReadTimeout("model took too long")   # upload done; the model was slow
        return _Resp()

    monkeypatch.setattr(action_planner.requests, "post", post)
    assert _call() == {"action": "done"}
    assert "/models/m1:" in urls[0] and "/models/m1:" not in urls[1]


def test_connect_timeout_retries_same_model_once_and_redacts_secrets(monkeypatch, caplog):
    urls = []
    fake_secret = "AIzaSyD" + "z" * 32

    def post(url, **kw):
        urls.append(url)
        raise requests.exceptions.ConnectTimeout(f"timed out talking to ?key={fake_secret}")

    monkeypatch.setattr(action_planner.requests, "post", post)
    with caplog.at_level(logging.WARNING, logger=action_planner.log.name):
        assert _call() is None
    assert len(urls) == 2 and urls[0] == urls[1]
    assert fake_secret not in caplog.text and "timed out" in caplog.text
