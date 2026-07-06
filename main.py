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


def _wait_for_api(port: int, timeout: int = 30) -> bool:
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


_WIZARD_OPTIONS = [
    {
        "mode": "turso",
        "icon": "☁",
        "title": "Nube (Turso)",
        "desc": "Respaldo automático y sincroniza entre varias computadoras.\nRecomendado si tienes internet estable.",
        "badge": "RECOMENDADO",
        "accent": "#16A34A",
    },
    {
        "mode": "local",
        "icon": "🖥",
        "title": "Solo este equipo",
        "desc": "Todo se queda en esta computadora, sin nube.\nIdeal para una sola caja, sin necesidad de red.",
        "badge": None,
        "accent": "#1d2140",
    },
    {
        "mode": "offline",
        "icon": "⭘",
        "title": "Sin conexión (temporal)",
        "desc": "Empieza sin internet — podrás activar la nube\nmás adelante desde Configuración.",
        "badge": None,
        "accent": "#D97706",
    },
]


def _run_first_time_setup_wizard() -> None:
    """Ventana nativa que aparece ANTES de la ventana principal, solo la primera
    vez que se instala en un equipo nuevo. Deja elegir el modo de trabajo
    (Nube/Local/Offline) con tarjetas tipo POS profesional, y muestra progreso
    real mientras configura todo."""
    import customtkinter as ctk

    ctk.set_appearance_mode("Light")
    ctk.set_default_color_theme("blue")

    NAVY = "#1d2140"
    GRAY = "#64748B"
    BORDER = "#E2E8F0"
    BG = "#F8FAFC"

    root = ctk.CTk()
    root.title("Configuración inicial — Farmacia Eben-Ezer")
    root.geometry("620x600")
    root.resizable(False, False)
    root.configure(fg_color=BG)
    root.protocol("WM_DELETE_WINDOW", lambda: None)  # no cerrar sin elegir
    root.after(10, lambda: root.eval('tk::PlaceWindow . center'))
    root.attributes("-topmost", True)

    # ── Encabezado con marca ──────────────────────────────────────────────
    header = ctk.CTkFrame(root, fg_color=NAVY, corner_radius=0, height=110)
    header.pack(fill="x")
    header.pack_propagate(False)
    ctk.CTkLabel(header, text="Farmacia Eben-Ezer — POS", font=ctk.CTkFont(size=17, weight="bold"),
                 text_color="white").pack(pady=(24, 2))
    ctk.CTkLabel(header, text="Configuración inicial · esto solo se pregunta una vez",
                 font=ctk.CTkFont(size=12), text_color="#B9BDD6").pack()

    body = ctk.CTkFrame(root, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=28, pady=22)

    ctk.CTkLabel(body, text="¿Cómo va a trabajar este equipo?",
                 font=ctk.CTkFont(size=15, weight="bold"), text_color="#0F172A").pack(anchor="w", pady=(0, 14))

    cards_frame = ctk.CTkFrame(body, fg_color="transparent")
    cards_frame.pack(fill="both", expand=True)

    progress_frame = ctk.CTkFrame(body, fg_color="transparent")
    status_label = ctk.CTkLabel(progress_frame, text="Configurando...", font=ctk.CTkFont(size=13),
                                 text_color=NAVY)
    progress = ctk.CTkProgressBar(progress_frame, width=420, mode="indeterminate")

    def _do_setup(mode: str):
        try:
            cfg.SETUP_FILE.write_text(
                __import__("json").dumps({"sync_mode": mode}), encoding="utf-8"
            )
        except Exception:
            pass
        cfg.reload_setup()

        if mode == "turso":
            steps = [
                ("Descargando datos de la nube...", lambda: __import__("app.database.sync_service", fromlist=["import_from_turso"]).import_from_turso()),
                ("Subiendo datos locales...", lambda: __import__("app.database.sync_service", fromlist=["sync_to_turso"]).sync_to_turso()),
                ("Sincronizando cambios recientes...", lambda: __import__("app.database.sync_service", fromlist=["sync_from_turso"]).sync_from_turso()),
            ]
            for texto, fn in steps:
                root.after(0, lambda t=texto: status_label.configure(text=t))
                try:
                    fn()
                except Exception as e:
                    _log_error(f"Setup inicial Turso falló ({texto}): {e}")
        else:
            root.after(0, lambda: status_label.configure(text="Preparando base de datos local..."))
            time.sleep(0.8)  # da tiempo visual — no queremos que el spinner parpadee y desaparezca

        root.after(0, root.destroy)

    def _elegir(mode: str):
        cards_frame.pack_forget()
        progress_frame.pack(fill="x", expand=True, pady=(40, 0))
        status_label.pack(pady=(0, 14))
        progress.pack()
        progress.start()
        threading.Thread(target=_do_setup, args=(mode,), daemon=True).start()

    def _make_card(parent, opt):
        card = ctk.CTkFrame(parent, fg_color="white", corner_radius=14, border_width=2,
                             border_color=BORDER, height=108)
        card.pack(fill="x", pady=7)
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=14)

        icon_box = ctk.CTkFrame(inner, fg_color=opt["accent"], corner_radius=12, width=52, height=52)
        icon_box.pack(side="left", padx=(0, 16))
        icon_box.pack_propagate(False)
        ctk.CTkLabel(icon_box, text=opt["icon"], font=ctk.CTkFont(size=22), text_color="white").pack(expand=True)

        text_col = ctk.CTkFrame(inner, fg_color="transparent")
        text_col.pack(side="left", fill="both", expand=True)

        title_row = ctk.CTkFrame(text_col, fg_color="transparent")
        title_row.pack(anchor="w", fill="x")
        ctk.CTkLabel(title_row, text=opt["title"], font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#0F172A").pack(side="left")
        if opt["badge"]:
            badge = ctk.CTkLabel(title_row, text=opt["badge"], font=ctk.CTkFont(size=9, weight="bold"),
                                  text_color="white", fg_color="#16A34A", corner_radius=6, padx=8, height=18)
            badge.pack(side="left", padx=(10, 0))
        ctk.CTkLabel(text_col, text=opt["desc"], font=ctk.CTkFont(size=11), text_color=GRAY,
                     justify="left", anchor="w").pack(anchor="w", pady=(4, 0))

        # Toda la tarjeta es clickeable, con hover sutil.
        widgets = [card, inner, icon_box, text_col, title_row] + list(inner.winfo_children()) + list(text_col.winfo_children())
        for w in widgets:
            w.bind("<Button-1>", lambda e: _elegir(opt["mode"]))
            w.bind("<Enter>", lambda e: card.configure(border_color=opt["accent"]))
            w.bind("<Leave>", lambda e: card.configure(border_color=BORDER))

    for opt in _WIZARD_OPTIONS:
        _make_card(cards_frame, opt)

    root.mainloop()


def main():
    if cfg.NEEDS_FIRST_RUN_SETUP:
        _run_first_time_setup_wizard()

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
        start_background_sync(interval=30)

    def _api_with_log():
        try:
            start_api_server()
        except Exception as e:
            _log_error(f"API thread crash: {e}\n" + traceback.format_exc())

    threading.Thread(target=_api_with_log, daemon=True, name="APIServer").start()

    from app.services import updater_service
    updater_service.start_background_check()

    # Cargar configuración Mercado Pago Point (token siempre; device_id opcional hasta que se detecte)
    if cfg.MP_ACCESS_TOKEN:
        from app.services.mercadopago_service import mp_point
        mp_point.configure(cfg.MP_ACCESS_TOKEN, cfg.MP_DEVICE_ID or "")

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

    def abrir_url_externa(self, url: str) -> bool:
        """Abre una URL en el navegador predeterminado del sistema (no en la ventana webview)."""
        try:
            import webbrowser
            return webbrowser.open(url)
        except Exception:
            return False

    def get_pdf_save_path(self, default_name: str) -> str:
        """Open native Save-As dialog for PDF files; return chosen path or empty string."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf",
                filetypes=[("Archivo PDF", "*.pdf"), ("Todos los archivos", "*.*")],
                initialfile=default_name,
                title="Guardar reporte PDF",
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
