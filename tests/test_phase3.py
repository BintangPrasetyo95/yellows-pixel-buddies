"""Phase 3 (privacy & security hardening) regression tests. See temp/IMPLEMENTATION_PLAN.md §6.

H11 verified updates · M10 static update worker · M11 safe git update · M9 key never in URLs/logs/files ·
M15 idle-time wrap · H12 sensitive-window capture filter · (M6 exact launch allowlist: tests/test_phase4_profiles.py)
No test here downloads anything, runs PowerShell, or touches the real update folder.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import privacy
import update_security as us
import yellows_pixel_buddies as ypb

REPO = ypb.GITHUB_REPO
FAKE_KEY = "AIzaSyD" + "x" * 32


# =====================================================================================
# privacy.redact_secrets / logging filter (M9)
# =====================================================================================

@pytest.mark.parametrize("text", [
    f"Network error: HTTPSConnectionPool(host='generativelanguage.googleapis.com'): Max retries exceeded with url: "
    f"/v1beta/models/gemini:generateContent?key={FAKE_KEY} (Caused by NameResolutionError)",
    f'{{"api_key": "{FAKE_KEY}"}}',
    f"x-goog-api-key: {FAKE_KEY}",
    f"see https://x.test/a?alt=json&key=supersecretvalue123&b=1",
    f"token={FAKE_KEY}",
])
def test_redact_secrets_removes_keys(text):
    out = privacy.redact_secrets(text)
    assert FAKE_KEY not in out and "supersecretvalue123" not in out
    assert privacy.REDACTED in out


def test_redact_keeps_normal_text():
    t = "Pink says hi. The keyboard is fine. Hotkey ctrl+k."
    assert privacy.redact_secrets(t) == t
    assert not privacy.contains_secret(t)


def test_log_filter_redacts_formatted_records():
    logger = logging.getLogger("pink.test.redact")
    seen: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    h = _Capture()
    logger.addHandler(h)
    logger.propagate = False
    privacy.install_log_redaction(logger)
    try:
        logger.warning("Model %s had network error (%s)", "flash", f"...generateContent?key={FAKE_KEY}")
        assert seen and FAKE_KEY not in seen[-1]
    finally:
        logger.removeHandler(h)


# =====================================================================================
# privacy.is_sensitive_window (H12)
# =====================================================================================

@pytest.mark.parametrize("exe,title,expected", [
    ("keepassxc.exe", "Passwords.kdbx - KeePassXC", True),
    ("Bitwarden.exe", "Bitwarden", True),
    ("msedge.exe", "New InPrivate tab - Microsoft Edge", True),
    ("chrome.exe", "New Incognito Tab - Google Chrome", True),
    ("chrome.exe", "Sign in - Google Accounts", True),
    ("chrome.exe", "Chase Bank - Online Banking", True),
    ("chrome.exe", "PayPal Checkout", True),
    ("consent.exe", "User Account Control", True),
    ("code.exe", "main.py - Visual Studio Code", False),
    ("chrome.exe", "lofi hip hop radio - YouTube", False),
    ("spotify.exe", "Spotify Premium", False),
    ("", "", False),
])
def test_sensitive_windows(exe, title, expected):
    assert privacy.is_sensitive_window(exe, title) is expected


# =====================================================================================
# update_security (H11, M10)
# =====================================================================================

@pytest.mark.parametrize("url,expected", [
    (f"https://github.com/{REPO}/releases/download/v1.0/Yellows-Pixel-Buddies.exe", True),
    (f"http://github.com/{REPO}/releases/download/v1.0/x.exe", False),                 # not https
    (f"https://evil.example/{REPO}/releases/download/v1.0/x.exe", False),             # wrong host
    ("https://github.com/someone-else/fork/releases/download/v1.0/x.exe", False),    # wrong repo
    (f"https://github.com.evil.example/{REPO}/releases/download/v1/x.exe", False),
    (f"https://github.com/{REPO}/archive/main.zip", False),
    ("", False),
])
def test_trusted_release_url(url, expected):
    assert us.is_trusted_release_url(url, REPO) is expected


def test_trusted_download_hosts():
    assert us.is_trusted_download_host("https://objects.githubusercontent.com/x")
    assert us.is_trusted_download_host("https://release-assets.githubusercontent.com/x")
    assert not us.is_trusted_download_host("http://objects.githubusercontent.com/x")
    assert not us.is_trusted_download_host("https://cdn.evil.example/x")


def test_parse_sha256sums_formats():
    h1, h2 = "a" * 64, "B" * 64
    sums = us.parse_sha256sums(f"{h1}  Yellows-Pixel-Buddies.exe\n{h2} *dist\\Yellows-Pixel-Buddies-Setup.exe\n# comment\n")
    assert sums == {"yellows-pixel-buddies.exe": h1, "yellows-pixel-buddies-setup.exe": h2.lower()}
    assert us.expected_hash_for(sums, "Yellows-Pixel-Buddies.EXE") == h1
    with pytest.raises(us.ChecksumUnavailable):
        us.expected_hash_for(sums, "other.exe")


@pytest.mark.parametrize("name,expected", [
    ("Yellows-Pixel-Buddies.exe", "Yellows-Pixel-Buddies.exe"),
    ("../evil.exe", "evil.exe"),          # directories stripped: can't escape the staging folder
    ("..\\..\\evil.exe", "evil.exe"),
    ("C:evil.exe", "evil.exe"),           # drive prefix stripped too
    ("x.dll", None), ("", None), ("..", None), ("update.exe.txt", None), ('a"b.exe', None),
])
def test_asset_filename_is_basename_exe_only(name, expected):
    if expected is None:
        with pytest.raises(us.UpdateVerificationError):
            us.safe_asset_filename(name)
    else:
        assert us.safe_asset_filename(name) == expected


def test_verify_file(tmp_path):
    f = tmp_path / "u.exe"
    f.write_bytes(b"Z" * (us.MIN_UPDATE_BYTES + 10))
    good = hashlib.sha256(f.read_bytes()).hexdigest()
    us.verify_file(f, good)
    with pytest.raises(us.UpdateVerificationError):
        us.verify_file(f, "0" * 64)
    small = tmp_path / "s.exe"
    small.write_bytes(b"x")
    with pytest.raises(us.UpdateVerificationError):
        us.verify_file(small, hashlib.sha256(b"x").hexdigest())


def test_updater_script_is_static_and_never_elevates_a_file():
    ps = us.UPDATER_PS1
    assert "{os.getpid()}" not in ps and "{up_path}" not in ps and "{current_exe}" not in ps   # no Python splicing
    assert "[Parameter(Mandatory = $true)][string]$SourcePath" in ps
    assert "-EncodedCommand" in ps and "-Verb RunAs" in ps
    child = ps[ps.index("$ChildMain = @'"):ps.index("'@", ps.index("$ChildMain = @'"))]
    assert "Start-Process" not in child and "RunAs" not in child     # elevated child only copies
    assert ".old" in ps and ".new" in ps and "HASH_MISMATCH" in ps    # verified swap with rollback


def test_updater_command_passes_paths_as_arguments():
    src = r"C:\Users\Bintang's PC\AppData\Local\YellowsPixelBuddies\updates\Yellows-Pixel-Buddies.exe"
    cmd = us.updater_command("w.ps1", 123, src, r"D:\Apps\Pink's\Yellows-Pixel-Buddies.exe", "AB" * 32, "u.log")
    assert cmd[cmd.index("-SourcePath") + 1] == src            # apostrophe survives untouched
    assert cmd[cmd.index("-ExpectedSha256") + 1] == "ab" * 32


# =====================================================================================
# UpdateCheckerThread / UpdateDownloaderThread with a fake network (H11)
# =====================================================================================

class _Resp:
    def __init__(self, url, content=b"", text=None, status=200, history=(), json_data=None):
        self.url, self.content, self.status_code, self.history = url, content, status, list(history)
        self.text = text if text is not None else content.decode("latin-1")
        self.headers = {"content-length": str(len(content))}
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def json(self):
        return self._json


PAYLOAD = b"MZ" + b"\x90" * (us.MIN_UPDATE_BYTES + 1000)
ASSET = "Yellows-Pixel-Buddies.exe"
DL_URL = f"https://github.com/{REPO}/releases/download/v9.9.9/{ASSET}"
SUMS_URL = f"https://github.com/{REPO}/releases/download/v9.9.9/SHA256SUMS.txt"
CDN = "https://objects.githubusercontent.com/github-production-release-asset/1"


def _fake_requests(monkeypatch, payload=PAYLOAD, sums_hash=None, final_url=CDN):
    sums_hash = sums_hash or hashlib.sha256(payload).hexdigest()

    def fake_get(url, *a, **k):
        if url == SUMS_URL:
            return _Resp(CDN + "/sums", text=f"{sums_hash}  {ASSET}\n", history=[_Resp(SUMS_URL)])
        if url == DL_URL:
            return _Resp(final_url, content=payload, history=[_Resp(DL_URL)])
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(ypb.requests, "get", fake_get)


def _run_downloader(monkeypatch, tmp_path, sums_url=SUMS_URL):
    monkeypatch.setattr(ypb, "_update_staging_dir", lambda: tmp_path)
    th = ypb.UpdateDownloaderThread(DL_URL, ASSET, sums_url, REPO)
    done, failed = [], []
    th.completed.connect(lambda p, h: done.append((p, h)))
    th.failed.connect(failed.append)
    th.run()   # synchronous
    return done, failed


def test_download_verified(qapp, monkeypatch, tmp_path):
    _fake_requests(monkeypatch)
    done, failed = _run_downloader(monkeypatch, tmp_path)
    assert failed == [] and len(done) == 1
    path, sha = done[0]
    assert Path(path).read_bytes() == PAYLOAD and sha == hashlib.sha256(PAYLOAD).hexdigest()


def test_download_hash_mismatch_is_refused_and_deleted(qapp, monkeypatch, tmp_path):
    _fake_requests(monkeypatch, sums_hash="0" * 64)
    done, failed = _run_downloader(monkeypatch, tmp_path)
    assert done == [] and "mismatch" in failed[0].lower()
    assert not (tmp_path / ASSET).exists()


def test_download_without_checksum_is_never_auto_installed(qapp, monkeypatch, tmp_path):
    _fake_requests(monkeypatch)
    done, failed = _run_downloader(monkeypatch, tmp_path, sums_url="")
    assert done == [] and failed[0].startswith("NO_CHECKSUM")


def test_download_redirect_off_github_is_refused(qapp, monkeypatch, tmp_path):
    _fake_requests(monkeypatch, final_url="https://cdn.evil.example/payload.exe")
    done, failed = _run_downloader(monkeypatch, tmp_path)
    assert done == [] and "left github" in failed[0].lower()


def test_checker_reports_checksum_asset(qapp, monkeypatch):
    release = {"tag_name": "v99.0.0", "body": "notes", "assets": [
        {"name": ASSET, "browser_download_url": DL_URL},
        {"name": "SHA256SUMS.txt", "browser_download_url": SUMS_URL},
    ]}
    monkeypatch.setattr(ypb.requests, "get", lambda *a, **k: _Resp("https://api.github.com/x", json_data=release))
    th = ypb.UpdateCheckerThread("0.9.8.6", REPO)
    got = []
    th.update_available.connect(lambda *args: got.append(args))
    th.run()
    assert got == [("v99.0.0", "notes", DL_URL, ASSET, SUMS_URL)]


def test_checker_rejects_untrusted_asset_url(qapp, monkeypatch):
    release = {"tag_name": "v99.0.0", "body": "", "assets": [
        {"name": ASSET, "browser_download_url": "https://evil.example/Yellows-Pixel-Buddies.exe"}]}
    monkeypatch.setattr(ypb.requests, "get", lambda *a, **k: _Resp("https://api.github.com/x", json_data=release))
    th = ypb.UpdateCheckerThread("0.9.8.6", REPO)
    avail, failed = [], []
    th.update_available.connect(lambda *a: avail.append(a))
    th.check_failed.connect(failed.append)
    th.run()
    assert avail == [] and "untrusted" in failed[0]


# =====================================================================================
# apply_application_update (H11, M10)
# =====================================================================================

class _Exited(Exception):
    pass


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(ypb, "release_single_instance_lock", lambda: None)
    monkeypatch.setattr(ypb.os, "_exit", lambda code=0: (_ for _ in ()).throw(_Exited(code)))
    launched = []
    monkeypatch.setattr(ypb.subprocess, "Popen", lambda cmd, **k: launched.append(cmd))
    return launched


def _payload_file(tmp_path, name=ASSET):
    f = tmp_path / name
    f.write_bytes(PAYLOAD)
    return f, hashlib.sha256(PAYLOAD).hexdigest()


def test_apply_refuses_tampered_payload(frozen, tmp_path):
    f, _ = _payload_file(tmp_path)
    assert ypb.apply_application_update(str(f), "1" * 64) is False
    assert frozen == [] and not f.exists()          # nothing launched, unverified file removed


def test_apply_runs_static_worker_with_verified_hash(frozen, tmp_path):
    f, sha = _payload_file(tmp_path)
    with pytest.raises(_Exited):
        ypb.apply_application_update(str(f), sha)
    cmd = frozen[0]
    assert cmd[0] == "powershell.exe" and cmd[cmd.index("-ExpectedSha256") + 1] == sha
    script = Path(cmd[cmd.index("-File") + 1]).read_text(encoding="utf-8")
    assert script == us.UPDATER_PS1                  # exactly the static text: no values spliced in
    assert not (tmp_path / "apply_update.bat").exists()


def test_apply_runs_installer_directly(frozen, tmp_path):
    f, sha = _payload_file(tmp_path, "Yellows-Pixel-Buddies-Setup.exe")
    with pytest.raises(_Exited):
        ypb.apply_application_update(str(f), sha)
    assert frozen[0] == [str(f.resolve()), "/CLOSEAPPLICATIONS"]


def test_apply_keeps_running_if_helper_cannot_start(frozen, monkeypatch, tmp_path):
    f, sha = _payload_file(tmp_path)

    def boom(*a, **k):
        raise OSError("powershell missing")

    monkeypatch.setattr(ypb.subprocess, "Popen", boom)
    assert ypb.apply_application_update(str(f), sha) is False   # no os._exit into nothing (M10)


def test_leftover_update_files(tmp_path):
    exe = tmp_path / "Yellows-Pixel-Buddies.exe"
    exe.write_bytes(b"x")
    (tmp_path / "Yellows-Pixel-Buddies.exe.old").write_bytes(b"o")
    assert [p.name for p in us.leftover_update_files(exe)] == ["Yellows-Pixel-Buddies.exe.old"]


# =====================================================================================
# GitUpdateThread against real throwaway repositories (M11)
# =====================================================================================

def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, check=True)


@pytest.fixture
def repos(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git not available")
    origin, work, other = tmp_path / "origin.git", tmp_path / "work", tmp_path / "other"
    _git(tmp_path, "init", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", str(origin), str(other))
    _git(other, "checkout", "-b", "main")
    (other / "app.py").write_text("v1\n")
    _git(other, "add", "app.py")
    _git(other, "commit", "-m", "v1")
    _git(other, "push", "origin", "main")
    _git(tmp_path, "clone", "-b", "main", str(origin), str(work))
    return origin, work, other


def _run_git_update(work):
    th = ypb.GitUpdateThread(work, branch="main")
    out = {"ok": [], "same": [], "fail": []}
    th.succeeded.connect(lambda c, d: out["ok"].append((c, d)))
    th.up_to_date.connect(lambda: out["same"].append(True))
    th.failed.connect(out["fail"].append)
    th.run()
    return out


def test_git_update_up_to_date_is_not_success(qapp, repos):
    _o, work, _other = repos
    assert _run_git_update(work)["same"] == [True]


def test_git_update_fast_forwards_and_flags_requirements(qapp, repos):
    _o, work, other = repos
    (other / "requirements.txt").write_text("PyQt5\n")
    _git(other, "add", "requirements.txt")
    _git(other, "commit", "-m", "deps")
    _git(other, "push", "origin", "main")
    out = _run_git_update(work)
    assert out["fail"] == [] and out["ok"] and out["ok"][0][1] is True
    assert (work / "requirements.txt").exists()


def test_git_update_refuses_dirty_tree(qapp, repos):
    _o, work, _other = repos
    (work / "app.py").write_text("local edit\n")
    out = _run_git_update(work)
    assert out["ok"] == [] and "local changes" in out["fail"][0]


def test_git_update_refuses_feature_branch(qapp, repos):
    _o, work, _other = repos
    _git(work, "checkout", "-b", "fix/something")
    out = _run_git_update(work)
    assert out["ok"] == [] and "fix/something" in out["fail"][0]


# =====================================================================================
# M15 idle time, M9 persistence, H12 capture gate
# =====================================================================================

@pytest.mark.parametrize("now,last,expected", [
    (10_000, 4_000, 6.0),
    (2**31 + 5_000, 2**31 - 5_000, 10.0),      # past 24.8 days: used to go negative -> 0
    (3_000, 2**32 - 2_000, 5.0),               # across the 49.7-day DWORD wrap
])
def test_idle_seconds_wrap(now, last, expected):
    assert ypb.idle_seconds_from_ticks(now, last) == expected


def test_record_error_never_persists_the_key(mem):
    mem.record_error("hi", f"Network error: ...generateContent?key={FAKE_KEY}", spoken_text="* oops")
    assert FAKE_KEY not in json.dumps(mem.history)
    if mem.session_file.exists():
        assert FAKE_KEY not in mem.session_file.read_text(encoding="utf-8")


def test_old_session_files_are_scrubbed_once(tmp_path):
    sessions = tmp_path / "memory" / "sessions"
    sessions.mkdir(parents=True)
    leaked = sessions / "session_20261101_100000.json"
    leaked.write_text(json.dumps({"messages": [{"error": f"url?key={FAKE_KEY}"}]}), encoding="utf-8")
    ypb.MemoryManager(tmp_path)
    text = leaked.read_text(encoding="utf-8")
    assert FAKE_KEY not in text and json.loads(text)["messages"][0]["error"].endswith(privacy.REDACTED)
    assert (tmp_path / "memory" / ".secrets_redacted_v1").exists()


def test_gemini_worker_sends_key_in_header(qapp, monkeypatch):
    seen = {}

    def fake_post(url, headers=None, **k):
        seen["url"], seen["headers"] = url, headers or {}
        raise RuntimeError("stop here")

    monkeypatch.setattr(ypb.requests, "post", fake_post)
    th = ypb.GeminiWorkerThread(api_key=FAKE_KEY, user_prompt="hi", system_instruction="", history=[],
                                screenshot_b64=None, model_name="gemini-test", is_auto_peek=False, parent=None)
    with pytest.raises(RuntimeError):
        th._call_gemini("gemini-test")
    assert FAKE_KEY not in seen["url"] and seen["headers"].get("x-goog-api-key") == FAKE_KEY


@pytest.fixture(scope="module")
def pet(qapp):
    from tests.conftest import shutdown_pet

    p = ypb.YellowsPixelBuddies(ypb.SpriteBank(ypb.SPRITES_DIR, 1.0))
    yield p
    shutdown_pet(p)


@pytest.mark.slow
def test_capture_gate(pet, monkeypatch):
    fg = {"exe": "code.exe", "title": "main.py - Visual Studio Code"}
    monkeypatch.setattr(ypb, "get_foreground_process_info", lambda: (1, fg["exe"], "", fg["title"], 2))
    pet._autonomous_vision_enabled = False
    assert pet._may_capture_autonomously("auto comment") is False          # no opt-in
    pet._autonomous_vision_enabled = True
    try:
        assert pet._may_capture_autonomously("auto comment") is True
        fg.update(exe="chrome.exe", title="Sign in - Online Banking")
        assert pet._may_capture_autonomously("auto comment") is False      # sensitive window
        fg.update(exe="keepassxc.exe", title="vault")
        assert pet._may_capture_autonomously("cinema") is False
    finally:
        pet._autonomous_vision_enabled = False


@pytest.mark.slow
def test_capture_is_visible_in_tray_tooltip(pet):
    pet._note_screen_capture("auto comment")
    assert pet._last_screen_capture[1] == "auto comment"
    if getattr(pet, "_tray_icon", None) is not None:
        assert "last looked at your screen" in pet._tray_icon.toolTip()
