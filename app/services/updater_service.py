import json
import shutil
import sys
import tempfile
import threading
import time
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
    "is_installer": False,
    "releases": [],  # List of {tag, version, url, is_installer}
}
_callbacks: list = []


def _parse_version(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").strip().split("."))
    except Exception:
        return (0,)


# ── Public API ────────────────────────────────────────────────────────────────

def start_background_check() -> None:
    def _loop():
        while True:
            _do_check()
            time.sleep(30 * 60)
    threading.Thread(target=_loop, daemon=True, name="UpdateChecker").start()


def check_for_update_async(callback=None) -> None:
    if callback:
        _callbacks.append(callback)
    threading.Thread(target=_do_check, daemon=True).start()


def force_check() -> dict:
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
        import requests as _req
        resp = _req.get(cfg.GITHUB_RELEASES_URL, headers=_auth_headers(), timeout=8)
        resp.raise_for_status()
        releases_data = resp.json()

        if not isinstance(releases_data, list):
            # Might be a single release if URL still points to /latest
            releases_data = [releases_data]

        all_releases = []
        for data in releases_data:
            tag = data.get("tag_name", "")
            version = tag.lstrip("v")
            
            exe_url = exe_api = zip_url = zip_api = None
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                aurl = asset.get("browser_download_url") or asset.get("url")
                aapi = asset.get("url")
                if name.endswith(".exe") and not exe_url:
                    exe_url = aurl
                    exe_api = aapi
                elif name.endswith(".zip") and not zip_url:
                    zip_url = aurl
                    zip_api = aapi
            
            url = exe_url or zip_url
            if url:
                all_releases.append({
                    "tag": tag,
                    "version": version,
                    "url": url,
                    "is_installer": bool(exe_url),
                    "body": data.get("body", "")
                })

        if not all_releases:
            with _lock:
                _status.update({"checked": True, "available": False})
            return

        # Latest is the first one in the list (usually)
        latest_rel = all_releases[0]
        latest_ver = _parse_version(latest_rel["tag"])
        current_ver = _parse_version(cfg.VERSION)
        available = latest_ver > current_ver

        with _lock:
            _status.update({
                "checked": True,
                "available": available,
                "version": latest_rel["version"],
                "url": latest_rel["url"],
                "is_installer": latest_rel["is_installer"],
                "releases": all_releases,
            })
    except Exception:
        with _lock:
            _status.update({"checked": True, "available": False})

    for cb in list(_callbacks):
        try:
            cb(_status["available"], _status["version"])
        except Exception:
            pass


# ── Download & install ────────────────────────────────────────────────────────

def download_and_install(progress_callback=None, version_url=None, is_installer=None) -> tuple[bool, str]:
    st = get_status()
    url = version_url or st.get("url")
    if not url:
        return False, "No se encontró archivo de descarga"

    if is_installer is None:
        is_installer = st.get("is_installer", False) or url.lower().endswith(".exe")
    
    tmp = Path(tempfile.gettempdir())

    if is_installer:
        return _install_via_exe(url, tmp, progress_callback)
    else:
        return _install_via_zip(url, tmp, progress_callback)


_cancel_requested = False

def cancel_download():
    global _cancel_requested
    with _lock:
        _cancel_requested = True

def _download_file(url: str, dest: Path, progress_callback=None, pct_max: float = 0.85) -> tuple[bool, str]:
    """Download url → dest, reporting progress up to pct_max. Supports resuming."""
    global _cancel_requested
    with _lock:
        _cancel_requested = False
    try:
        import requests as _req
        hdrs = {"User-Agent": "FarmaciaPOS-Updater/1.0", "Accept": "application/octet-stream"}
        if getattr(cfg, "GITHUB_TOKEN", ""):
            hdrs["Authorization"] = f"Bearer {cfg.GITHUB_TOKEN}"
        
        # Resume support: check existing file size
        existing_size = dest.stat().st_size if dest.exists() else 0
        if existing_size > 0:
            hdrs["Range"] = f"bytes={existing_size}-"

        with _req.get(url, headers=hdrs, stream=True, timeout=60) as resp:
            # 416 = partial file is stale (new release replaced the asset) — restart fresh
            if resp.status_code == 416:
                if dest.exists():
                    dest.unlink()
                existing_size = 0
                hdrs.pop("Range", None)
                resp.close()
            if resp.status_code == 416 or resp.status_code not in (200, 206):
                # Re-request without Range header
                with _req.get(url, headers=hdrs, stream=True, timeout=60) as resp2:
                    resp2.raise_for_status()
                    existing_size = 0
                    total = int(resp2.headers.get("Content-Length") or 0)
                    downloaded = 0
                    with open(dest, "wb") as f:
                        for chunk in resp2.iter_content(chunk_size=65536):
                            with _lock:
                                if _cancel_requested:
                                    return False, "Actualización cancelada por el usuario"
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total and progress_callback:
                                progress_callback(min(0.99, (downloaded / total) * pct_max))
                    return True, ""
            # Handle 206 Partial Content or 200 OK
            if resp.status_code == 206:
                total_content_range = resp.headers.get("Content-Range")
                if total_content_range:
                    total = int(total_content_range.split("/")[-1])
                else:
                    total = int(resp.headers.get("Content-Length") or 0) + existing_size
            else:
                # 200 OK: server doesn't support range or file is new
                existing_size = 0
                total = int(resp.headers.get("Content-Length") or 0)

            downloaded = existing_size
            mode = "ab" if existing_size > 0 else "wb"
            
            with open(dest, mode) as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    with _lock:
                        if _cancel_requested:
                            return False, "Actualización cancelada por el usuario"
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded / total * pct_max)
        return True, ""
    except Exception as e:
        return False, f"Error de descarga: {e}"


def _launch_shellexecute(exe: str, args: str) -> tuple[bool, str]:
    """Launch exe with runas (UAC elevation) via ShellExecuteW."""
    try:
        import ctypes
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 0)
        if ret <= 32:
            return False, f"No se pudo lanzar (código {ret})"
        return True, ""
    except Exception as e:
        return False, f"Error al lanzar: {e}"


def _install_via_exe(url: str, tmp: Path, progress_callback=None) -> tuple[bool, str]:
    """Download Inno Setup installer and launch it directly (no PowerShell wrapper)."""
    installer_path = tmp / "FarmaciaPOS_update_setup.exe"

    ok, err = _download_file(url, installer_path, progress_callback, pct_max=0.95)
    if not ok:
        return False, err

    if progress_callback:
        progress_callback(1.0)

    # Launch installer directly — its own manifest requests UAC elevation.
    # No PowerShell = no black console window. The UAC prompt shows the app name/icon.
    # /VERYSILENT    : zero UI
    # /NORESTART     : no Windows reboot
    # /CLOSEAPPLICATIONS : cierra la app si sigue abierta
    # /SUPPRESSMSGBOXES  : sin popups de error
    # The [Run] section in installer.iss (without skipifsilent) relaunches the app.
    args = '/VERYSILENT /NORESTART /CLOSEAPPLICATIONS /SUPPRESSMSGBOXES'
    try:
        import ctypes
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "open", str(installer_path), args, None, 1
        )
        if ret <= 32:
            return False, f"No se pudo lanzar el instalador (código {ret})"
    except Exception as e:
        return False, f"Error al lanzar instalador: {e}"

    return True, ""


def _install_via_zip(url: str, tmp: Path, progress_callback=None) -> tuple[bool, str]:
    """Download ZIP, extract, replace app files via PS script."""
    zip_path = tmp / "FarmaciaPOS_update.zip"
    extract_dir = tmp / "FarmaciaPOS_update_extracted"
    install_dir = Path(sys.executable).parent

    ok, err = _download_file(url, zip_path, progress_callback, pct_max=0.85)
    if not ok:
        return False, err

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

    src = str(source_dir).replace("'", "''")
    dst = str(install_dir).replace("'", "''")
    exe = str(install_dir / "FarmaciaPOS.exe").replace("'", "''")
    log = str(tmp / "farmacia_update.log").replace("'", "''")
    zp  = str(zip_path).replace("'", "''")
    xd  = str(extract_dir).replace("'", "''")

    ps_script = (
        f"$src = '{src}'\n"
        f"$dst = '{dst}'\n"
        f"$exe = '{exe}'\n"
        f"$log = '{log}'\n\n"
        "$deadline = (Get-Date).AddSeconds(30)\n"
        "while ((Get-Process -Name 'FarmaciaPOS' -ErrorAction SilentlyContinue)"
        " -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 400 }\n"
        "Start-Sleep -Seconds 1\n\n"
        "try {\n"
        "    Copy-Item -Path \"$src\\*\" -Destination \"$dst\" -Recurse -Force -ErrorAction Stop\n"
        "    \"OK $(Get-Date)\" | Out-File $log -Encoding utf8\n"
        "} catch {\n"
        "    \"ERROR $_ $(Get-Date)\" | Out-File $log -Encoding utf8\n"
        "    exit 1\n"
        "}\n\n"
        "if (Test-Path \"$exe\") { Start-Process -FilePath \"$exe\" }\n\n"
        f"Remove-Item -Path '{zp}' -Force -ErrorAction SilentlyContinue\n"
        f"Remove-Item -Path '{xd}' -Recurse -Force -ErrorAction SilentlyContinue\n"
        "Start-Sleep -Milliseconds 500\n"
        "Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
    )

    ps_path = tmp / "farmacia_updater.ps1"
    ps_path.write_text(ps_script, encoding="utf-8-sig")

    if progress_callback:
        progress_callback(0.97)

    ps_exe = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    ps_args = f'-ExecutionPolicy Bypass -NonInteractive -WindowStyle Hidden -File "{ps_path}"'
    ok, err = _launch_shellexecute(ps_exe, ps_args)
    if not ok:
        return False, err

    if progress_callback:
        progress_callback(1.0)
    return True, ""
