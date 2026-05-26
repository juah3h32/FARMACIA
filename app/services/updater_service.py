import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import app.config as cfg

_lock = threading.Lock()
_status: dict = {
    "checked": False,
    "available": False,
    "version": None,
    "url": None,
    "asset_api_url": None,
}
_callbacks: list = []


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").strip().split("."))
    except Exception:
        return (0,)


# ── Public API ────────────────────────────────────────────────────────────────

def start_background_check() -> None:
    """Check on startup, then re-check every 30 min so new releases are detected."""
    def _loop():
        while True:
            _do_check()
            time.sleep(30 * 60)
    threading.Thread(target=_loop, daemon=True, name="UpdateChecker").start()


def check_for_update_async(callback=None) -> None:
    """Legacy helper used by CustomTkinter fallback UI."""
    if callback:
        _callbacks.append(callback)
    threading.Thread(target=_do_check, daemon=True).start()


def force_check() -> dict:
    """Synchronous check — blocks caller. Use only from API request handler."""
    _do_check()
    return get_status()


def get_status() -> dict:
    with _lock:
        return dict(_status)


# ── Internal ──────────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    h = {"User-Agent": "FarmaciaPOS-Updater/1.0", "Accept": "application/vnd.github+json"}
    if getattr(cfg, "GITHUB_TOKEN", ""):
        h["Authorization"] = f"Bearer {cfg.GITHUB_TOKEN}"
    return h


def _do_check() -> None:
    if not cfg.GITHUB_RELEASES_URL:
        return
    try:
        req = urllib.request.Request(cfg.GITHUB_RELEASES_URL, headers=_auth_headers())
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        latest = _parse_version(tag)
        current = _parse_version(cfg.VERSION)
        available = latest > current
        version = tag.lstrip("v")
        # For private repos: use the API asset URL (requires auth on download too)
        url = None
        asset_api_url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").lower().endswith(".zip"):
                url = asset.get("browser_download_url") or asset.get("url")
                asset_api_url = asset.get("url")
                break

        with _lock:
            _status.update({"checked": True, "available": available,
                            "version": version, "url": url,
                            "asset_api_url": asset_api_url})
    except Exception:
        with _lock:
            _status.update({"checked": True, "available": False})

    for cb in list(_callbacks):
        try:
            cb(_status["available"], _status["version"])
        except Exception:
            pass


# ── Download & install ────────────────────────────────────────────────────────

def download_and_install(progress_callback=None) -> tuple[bool, str]:
    st = get_status()
    # Prefer browser_download_url (public, no auth); fall back to API asset URL
    url = st.get("url")
    if not url:
        return False, "No se encontró archivo de descarga en el release"

    tmp = Path(tempfile.gettempdir())
    zip_path = tmp / "FarmaciaPOS_update.zip"
    extract_dir = tmp / "FarmaciaPOS_update_extracted"
    install_dir = Path(sys.executable).parent

    # ── Download ──────────────────────────────────────────────────────────────
    try:
        dl_headers = {"User-Agent": "FarmaciaPOS-Updater/1.0",
                      "Accept": "application/octet-stream"}
        if getattr(cfg, "GITHUB_TOKEN", ""):
            dl_headers["Authorization"] = f"Bearer {cfg.GITHUB_TOKEN}"
        req = urllib.request.Request(url, headers=dl_headers)
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(zip_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded / total * 0.85)
    except Exception as e:
        return False, f"Error de descarga: {e}"

    # ── Extract ───────────────────────────────────────────────────────────────
    try:
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(extract_dir)
        if progress_callback:
            progress_callback(0.92)
    except Exception as e:
        return False, f"Error al extraer: {e}"

    contents = list(extract_dir.iterdir())
    source_dir = contents[0] if len(contents) == 1 and contents[0].is_dir() else extract_dir

    # ── Build self-elevating PowerShell updater ───────────────────────────────
    # PS single-quoted strings: escape ' as ''
    src = str(source_dir).replace("'", "''")
    dst = str(install_dir).replace("'", "''")
    exe = str(install_dir / "FarmaciaPOS.exe").replace("'", "''")
    zp  = str(zip_path).replace("'", "''")
    xd  = str(extract_dir).replace("'", "''")

    ps_script = (
        "param()\n"
        # Self-elevate: if not admin, relaunch as admin and exit
        "if (-not ([Security.Principal.WindowsPrincipal]"
        "[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("
        "[Security.Principal.WindowsBuiltInRole]::Administrator)) {\n"
        "    Start-Process PowerShell -Verb RunAs"
        " -ArgumentList \"-NonInteractive -WindowStyle Hidden -File `\"$PSCommandPath`\"\""
        " -Wait\n"
        "    exit\n"
        "}\n\n"
        f"$src = '{src}'\n"
        f"$dst = '{dst}'\n"
        f"$exe = '{exe}'\n\n"
        # Wait for the app process to fully exit (max 30 s)
        "$deadline = (Get-Date).AddSeconds(30)\n"
        "while ((Get-Process -Name 'FarmaciaPOS' -ErrorAction SilentlyContinue)"
        " -and (Get-Date) -lt $deadline) {\n"
        "    Start-Sleep -Milliseconds 500\n"
        "}\n"
        "Start-Sleep -Seconds 1\n\n"
        # Copy new files over existing install
        "Copy-Item -Path \"$src\\*\" -Destination \"$dst\" -Recurse -Force\n\n"
        # Restart updated app
        "Start-Process -FilePath \"$exe\"\n\n"
        # Cleanup
        f"Remove-Item -Path '{zp}' -Force -ErrorAction SilentlyContinue\n"
        f"Remove-Item -Path '{xd}' -Recurse -Force -ErrorAction SilentlyContinue\n"
        "Start-Sleep -Milliseconds 500\n"
        "Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
    )

    ps_path = tmp / "farmacia_updater.ps1"
    # UTF-8 with BOM so PowerShell 5.1 reads it correctly
    ps_path.write_text(ps_script, encoding="utf-8-sig")

    # CREATE_BREAKAWAY_FROM_JOB ensures PS survives when the Python process exits
    flags = (subprocess.DETACHED_PROCESS
             | subprocess.CREATE_NO_WINDOW
             | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    subprocess.Popen(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-File", str(ps_path)],
        creationflags=flags,
        close_fds=True,
    )

    if progress_callback:
        progress_callback(1.0)
    return True, ""
