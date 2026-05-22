import threading
import socket
import time
import sys
import app.config as cfg
from app.database.connection import init_db
from app.api.server import start_api_server


def _hide_console():
    """Hide the console window when running as a frozen windowed EXE."""
    if getattr(sys, 'frozen', False):
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE


def _find_free_port(start: int, attempts: int = 10) -> int | None:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return None


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
    _hide_console()
    init_db()

    if cfg.TURSO_SYNC:
        from app.database.sync_service import import_from_turso, start_background_sync
        import_from_turso()
        start_background_sync(interval=60)

    port = _find_free_port(cfg.API_PORT)
    if not port:
        print("[FarmaciaPOS] No se pudo encontrar puerto libre para la API")
        sys.exit(1)

    cfg.API_PORT = port
    api_thread = threading.Thread(target=start_api_server, daemon=True, name="APIServer")
    api_thread.start()

    if not _wait_for_api(port):
        print("[FarmaciaPOS] El servidor API no respondió a tiempo")
        sys.exit(1)

    try:
        import webview
        window = webview.create_window(
            title="Farmacia Eben-Ezer — POS",
            url=f"http://127.0.0.1:{port}",
            width=cfg.WINDOW_WIDTH,
            height=cfg.WINDOW_HEIGHT,
            resizable=True,
            min_size=(1000, 680),
        )
        webview.start(debug=False)
    except ImportError:
        # Fallback to CustomTkinter if pywebview not installed
        import customtkinter as ctk
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        from app.ui.login_screen import LoginScreen
        app = LoginScreen()
        app.mainloop()


if __name__ == "__main__":
    main()
