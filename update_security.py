"""Auto-update integrity helpers (REVIEW H11, M10). Pure Python; the PowerShell worker is static text.

Threat model fixed here:
* H11: a release asset used to be executed after a size check only. Now every update must match a SHA-256
  published in the release's ``SHA256SUMS.txt`` (written by build_release.bat), the download must come from
  GitHub over HTTPS, and the hash is re-checked right before running and inside the (elevated) copy step.
* H11: the elevated retry used to re-run a script from a user-writable temp folder and relaunch Pink as
  Administrator. Now the elevated child is passed via -EncodedCommand (no file to swap), only copies, and
  exits 0/1; the non-elevated parent verifies the result itself and relaunches Pink without elevation.
* M10: paths used to be spliced into the script's param() defaults (an apostrophe broke the update and the
  app never came back). The worker now takes every value as a parameter, swaps via ``.new``/``.old`` with
  rollback, and never leaves the install without a working exe.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

MIN_UPDATE_BYTES = 500 * 1024
CHECKSUM_ASSET_NAMES = ("sha256sums.txt", "sha256sums", "checksums.txt", "checksums.sha256")
# browser_download_url is on github.com and redirects to GitHub's release CDN.
TRUSTED_DOWNLOAD_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
})
_SHA256_LINE = re.compile(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")


class UpdateVerificationError(Exception):
    """The update can't be proven authentic; never install it automatically."""


class ChecksumUnavailable(UpdateVerificationError):
    """The release publishes no usable SHA-256 for this asset."""


def is_trusted_release_url(url: str, repo: str) -> bool:
    """https://github.com/<repo>/releases/download/... only."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    return (
        u.scheme == "https"
        and (u.hostname or "").lower() == "github.com"
        and u.path.lower().startswith(f"/{repo.lower()}/releases/download/")
    )


def is_trusted_download_host(url: str) -> bool:
    """HTTPS on GitHub or GitHub's release CDN (for every redirect hop and the final URL)."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return False
    return u.scheme == "https" and (u.hostname or "").lower() in TRUSTED_DOWNLOAD_HOSTS


def find_checksum_asset(assets: list[dict]) -> dict | None:
    for a in assets or []:
        if str(a.get("name", "")).strip().lower() in CHECKSUM_ASSET_NAMES:
            return a
    return None


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse 'sha256sum' style lines ('<64 hex>  name' or '<64 hex> *name') into {lowercase name: hex}."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = _SHA256_LINE.match(line)
        if m:
            name = Path(m.group(2).strip().replace("\\", "/")).name.lower()
            out[name] = m.group(1).lower()
    return out


def expected_hash_for(sums: dict[str, str], asset_name: str) -> str:
    h = sums.get(Path(asset_name or "").name.lower())
    if not h:
        raise ChecksumUnavailable(f"SHA256SUMS has no entry for {asset_name!r}")
    return h


def safe_asset_filename(name: str) -> str:
    """Basename only, must be a .exe (an asset name can't steer where the file is written)."""
    base = Path(str(name or "")).name.strip()
    if not base or base in (".", "..") or not base.lower().endswith(".exe") or any(c in base for c in '<>:"|?*'):
        raise UpdateVerificationError(f"unsafe update asset name {name!r}")
    return base


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file(path: str | Path, expected_sha256: str) -> None:
    p = Path(path)
    if not p.is_file() or p.stat().st_size < MIN_UPDATE_BYTES:
        raise UpdateVerificationError(f"update payload missing or too small: {p}")
    actual = sha256_file(p)
    if actual.lower() != (expected_sha256 or "").lower():
        raise UpdateVerificationError(f"SHA-256 mismatch for {p.name}: got {actual}, expected {expected_sha256}")


# ---------------------------------------------------------------------------------------------
# Static PowerShell worker. NO Python formatting happens on this text: every value is a parameter.
# ---------------------------------------------------------------------------------------------
UPDATER_PS1 = r'''# Pink Auto-Update Worker (static script; all values arrive as parameters - see update_security.py)
param(
    [int]$TargetPid = 0,
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$TargetPath,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [string]$LogPath = ""
)

$Common = @'
function Log-Message([string]$msg) {
    if ($LogPath) {
        $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
        Add-Content -LiteralPath $LogPath -Value $line -ErrorAction SilentlyContinue
    }
}
function Get-Sha256([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Install-Update {
    # Verified copy -> TARGET.new, then TARGET -> TARGET.old, TARGET.new -> TARGET; roll back on failure.
    $expected = $ExpectedSha256.ToLowerInvariant()
    if ((Get-Sha256 $SourcePath) -ne $expected) { throw "HASH_MISMATCH: source" }
    $newPath = "$TargetPath.new"
    $oldPath = "$TargetPath.old"
    Copy-Item -LiteralPath $SourcePath -Destination $newPath -Force -ErrorAction Stop
    if ((Get-Sha256 $newPath) -ne $expected) {
        Remove-Item -LiteralPath $newPath -Force -ErrorAction SilentlyContinue
        throw "HASH_MISMATCH: staged copy"
    }
    if (Test-Path -LiteralPath $oldPath) { Remove-Item -LiteralPath $oldPath -Force -ErrorAction Stop }
    Move-Item -LiteralPath $TargetPath -Destination $oldPath -Force -ErrorAction Stop
    try {
        Move-Item -LiteralPath $newPath -Destination $TargetPath -Force -ErrorAction Stop
    } catch {
        if (-not (Test-Path -LiteralPath $TargetPath) -and (Test-Path -LiteralPath $oldPath)) {
            Move-Item -LiteralPath $oldPath -Destination $TargetPath -Force -ErrorAction SilentlyContinue
        }
        throw
    }
}
function Try-Install([int]$attempts) {
    for ($i = 1; $i -le $attempts; $i++) {
        try {
            Install-Update
            Log-Message "Update installed on attempt $i."
            return $true
        } catch {
            $err = "$_"
            Log-Message "Attempt $i failed: $err"
            if ($err -like "HASH_MISMATCH*") { return $false }
            if ($err -like "*denied*" -or $err -like "*UnauthorizedAccess*") { return $false }   # needs elevation, retrying won't help
            Start-Sleep -Milliseconds 500
        }
    }
    return $false
}
'@

$ChildMain = @'
# Elevated, copy-only: never launches anything and never elevates again.
if (Try-Install 10) { exit 0 } else { exit 1 }
'@

. ([ScriptBlock]::Create($Common))

function Quote-PS([string]$s) { "'" + $s.Replace("'", "''") + "'" }

Log-Message "=== Pink Updater Worker Started (pid $TargetPid) ==="
if ($TargetPid -gt 0) {
    try {
        $proc = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
        if ($proc) { $null = $proc.WaitForExit(20000) }
    } catch { Log-Message "Process wait note: $_" }
}
Start-Sleep -Milliseconds 600

$installed = Try-Install 30

if (-not $installed -and (Test-Path -LiteralPath $SourcePath) -and ((Get-Sha256 $SourcePath) -eq $ExpectedSha256.ToLowerInvariant())) {
    # e.g. Program Files: ask for elevation ONLY for the copy. The child gets its script inline
    # (-EncodedCommand), so there is no file an unprivileged process could swap before UAC is approved.
    Log-Message "Normal install failed; requesting elevation for the copy step only."
    $child = "`$SourcePath = $(Quote-PS $SourcePath)`n" +
             "`$TargetPath = $(Quote-PS $TargetPath)`n" +
             "`$ExpectedSha256 = $(Quote-PS $ExpectedSha256)`n" +
             "`$LogPath = $(Quote-PS $LogPath)`n" + $Common + "`n" + $ChildMain
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($child))
    try {
        $p = Start-Process powershell -ArgumentList "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded" -Verb RunAs -PassThru -Wait
        Log-Message "Elevated copy exited with code $($p.ExitCode)."
    } catch { Log-Message "Elevation was cancelled or failed: $_" }
    # Trust the file, not the exit code.
    $installed = (Test-Path -LiteralPath $TargetPath) -and ((Get-Sha256 $TargetPath) -eq $ExpectedSha256.ToLowerInvariant())
}

if ($installed) {
    Log-Message "Launching updated application (not elevated): $TargetPath"
    Start-Process -FilePath $TargetPath
    Remove-Item -LiteralPath $SourcePath -Force -ErrorAction SilentlyContinue
    Log-Message "Update finished successfully."
    exit 0
}

Log-Message "ERROR: update not installed; relaunching the previous version."
if (Test-Path -LiteralPath $TargetPath) { Start-Process -FilePath $TargetPath }
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show(
    "Pink could not install the update (the file may be locked, write-protected, or failed verification).`n`nYour current version was kept. You can update manually from the GitHub Releases page.",
    "Update Notification",
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning
) | Out-Null
exit 1
'''


def updater_command(script_path: str | Path, pid: int, source: str | Path, target: str | Path,
                    expected_sha256: str, log_path: str | Path) -> list[str]:
    """Argument list for the worker: values travel as separate arguments, never inside the script text."""
    return [
        "powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
        "-ExecutionPolicy", "Bypass", "-File", str(script_path),
        "-TargetPid", str(int(pid)),
        "-SourcePath", str(source),
        "-TargetPath", str(target),
        "-ExpectedSha256", str(expected_sha256).lower(),
        "-LogPath", str(log_path),
    ]


def leftover_update_files(exe_path: str | Path) -> list[Path]:
    """Files a finished update leaves next to the exe (safe to delete once the new version runs)."""
    exe = Path(exe_path)
    return [p for p in (exe.with_name(exe.name + ".old"), exe.with_name(exe.name + ".new")) if p.exists()]
