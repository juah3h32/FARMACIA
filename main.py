import threading
import socket
import time
import sys
import traceback
import app.config as cfg
from app.database.connection import init_db
from app.api.server import start_api_server


def _log_error(msg: str) -> None:
    try:
        log = cfg.DATA_DIR / "error.log"
        with open(log, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


def _find_free_port(start: int, attempts: int = 10) -> int | None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_api(port: int, timeout: int = 12) -> bool:
    import urllib.request
    url = f"http://127.0.0.1:{port}/api/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.25)
    return False


def main():
    init_db()

    port = _find_free_port(cfg.API_PORT)
    if not port:
        print("[FarmaciaPOS] No se pudo encontrar puerto libre para la API")
        sys.exit(1)
    cfg.API_PORT = port

    # Turso sync in background — never blocks startup
    if cfg.TURSO_SYNC:
        from app.database.sync_service import import_from_turso, start_background_sync
        threading.Thread(target=import_from_turso, daemon=True, name="TursoImport").start()
        start_background_sync(interval=60)

    def _api_with_log():
        try:
            start_api_server()
        except Exception as e:
            _log_error(f"API thread crash: {e}\n" + traceback.format_exc())

    threading.Thread(target=_api_with_log, daemon=True, name="APIServer").start()

    from app.services import updater_service
    updater_service.start_background_check()

    _start_ui(port)


class _PyWebViewApi:
    """Exposes native desktop dialogs to the web UI via window.pywebview.api.*"""

    def get_save_path(self, default_name: str) -> str:
        """Open native Save-As dialog; return chosen path or empty string."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.asksaveasfilename(
                defaultextension=".db",
                filetypes=[("Base de datos SQLite", "*.db"), ("Todos los archivos", "*.*")],
                initialfile=default_name,
                title="Guardar respaldo de base de datos",
            )
            root.destroy()
            return path or ""
        except Exception:
            return ""


def _start_ui(port: int) -> None:
    try:
        import webview
        # webview renders the web SPA — must wait for API to be ready
        if not _wait_for_api(port):
            _log_error("El servidor API no respondió a tiempo")
            raise RuntimeError("API timeout")
        window = webview.create_window(
            title="Farmacia Eben-Ezer — POS",
            url=f"http://127.0.0.1:{port}",
            width=cfg.WINDOW_WIDTH,
            height=cfg.WINDOW_HEIGHT,
            resizable=True,
            min_size=(1000, 680),
            fullscreen=False,
            js_api=_PyWebViewApi(),
        )
        webview.start(debug=False)
        return
    except Exception as e:
        _log_error(f"pywebview falló ({type(e).__name__}: {e}) — usando CustomTkinter\n"
                   + traceback.format_exc())

    # CTK fallback — uses SQLAlchemy directly, no API wait needed
    try:
        import customtkinter as ctk
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        from app.ui.login_screen import LoginScreen
        app = LoginScreen()
        app.mainloop()
    except Exception as e:
        _log_error(f"CustomTkinter falló: {e}\n" + traceback.format_exc())


if __name__ == "__main__":
    main()
