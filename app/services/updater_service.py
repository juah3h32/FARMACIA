import json
import shutil
import subprocess
import sys
import tempfile
import threading
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
}
_callbacks: list = []


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").strip().split("."))
    except Exception:
        return (0,)


# ── Public API ────────────────────────────────────────────────────────────────

def start_background_check() -> None:
    """Fire-and-forget check on app startup."""
    threading.Thread(target=_do_check, daemon=True).start()


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

def _do_check() -> None:
    if not cfg.GITHUB_RELEASES_URL:
        return
    try:
        req = urllib.request.Request(
            cfg.GITHUB_RELEASES_URL,
            headers={"User-Agent": "FarmaciaPOS-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        tag = data.get("tag_name", "")
        latest = _parse_version(tag)
        current = _parse_version(cfg.VERSION)
        available = latest > current
        version = tag.lstrip("v")
        url = None
        for asset in data.get("assets", []):
            if asset.get("name", "").lower().endswith(".zip"):
                url = asset["browser_download_url"]
                break

        with _lock:
            _status.update({"checked": True, "available": available,
                            "version": version, "url": url})
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
    url = st.get("url")
    if not url:
        return False, "No se encontró archivo de descarga en el release"

    tmp = Path(tempfile.gettempdir())
    zip_path = tmp / "FarmaciaPOS_update.zip"
    extract_dir = tmp / "FarmaciaPOS_update_extracted"
    install_dir = Path(sys.executable).parent

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FarmaciaPOS-Updater/1.0"})
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

    ps_path = tmp / "farmacia_updater.ps1"
    src = str(source_dir).replace("'", "''")
    dst = str(install_dir).replace("'", "''")
    exe = str(install_dir / "FarmaciaPOS.exe").replace("'", "''")
    zp  = str(zip_path).replace("'", "''")
    xd  = str(extract_dir).replace("'", "''")

    ps_path.write_text(
        f"Start-Sleep -Seconds 2\n"
        f"$src = '{src}'\n"
        f"$dst = '{dst}'\n"
        f"$exe = '{exe}'\n"
        f"try {{\n"
        f"    Copy-Item -Path \"$src\\*\" -Destination $dst -Recurse -Force -ErrorAction Stop\n"
        f"    Start-Process -FilePath $exe\n"
        f"}} catch {{\n"
        f"    $cmd = \"Copy-Item -Path '$src\\*' -Destination '$dst' -Recurse -Force;"
        f" Start-Process -FilePath '$exe'\"\n"
        f"    Start-Process powershell -Verb RunAs"
        f" -ArgumentList \"-NonInteractive -Command `\"$cmd`\"\" -Wait\n"
        f"}}\n"
        f"Remove-Item -Path '{zp}' -Force -ErrorAction SilentlyContinue\n"
        f"Remove-Item -Path '{xd}' -Recurse -Force -ErrorAction SilentlyContinue\n"
        f"Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue\n",
        encoding="utf-8",
    )

    subprocess.Popen(
        ["powershell", "-NonInteractive", "-WindowStyle", "Hidden", "-File", str(ps_path)],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )

    if progress_callback:
        progress_callback(1.0)
    return True, ""
