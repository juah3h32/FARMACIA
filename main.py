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


_WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def _webview2_installed() -> bool:
    """En Windows, pywebview necesita el runtime WebView2 (Edge Chromium) para
    dibujar la interfaz. Si falta — como en Windows 10 LTSC, que no trae Edge
    preinstalado — pywebview cae en silencio al motor viejo de Internet
    Explorer: no lanza error, pero la interfaz se ve sin estilos y con
    modales que deberían estar ocultos aparecen todos apilados."""
    if sys.platform != "win32":
        return True
    try:
        import winreg
    except ImportError:
        return True
    candidatos = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{_WEBVIEW2_GUID}"),
    ]
    for hive, path in candidatos:
        try:
            winreg.OpenKey(hive, path)
            return True
        except OSError:
            continue
    return False


def _install_webview2() -> bool:
    """Descarga e instala en silencio el runtime oficial de WebView2 (~2MB,
    bootstrapper de Microsoft). Requiere internet la primera vez únicamente."""
    import urllib.request
    import subprocess
    import tempfile
    import os

    url = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
    dest = os.path.join(tempfile.gettempdir(), "MicrosoftEdgeWebView2Setup.exe")
    try:
        with urllib.request.urlopen(url, timeout=15) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        subprocess.run([dest, "/silent", "/install"], check=True, timeout=120)
        return True
    except Exception as e:
        _log_error(f"No se pudo instalar WebView2 automáticamente: {e}")
        return False


class _BootSplash:
    """Pantalla nativa con spinner mostrada mientras arranca todo (BD, usuarios
    por defecto, componentes de Windows, servidor local) — así nunca hay un
    tramo en blanco donde parezca que el programa no abrió o está roto."""

    def __init__(self):
        import customtkinter as ctk
        import tkinter as tk

        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("Farmacia Eben-Ezer")
        self.root.geometry("420x300")
        self.root.resizable(False, False)
        self.root.configure(fg_color="#1d2140")
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self.root.after(10, lambda: self.root.eval("tk::PlaceWindow . center"))
        self.root.attributes("-topmost", True)

        self._canvas = tk.Canvas(self.root, width=64, height=64, bg="#1d2140", highlightthickness=0)
        self._canvas.pack(pady=(64, 16))
        self._angle = 0
        self._arc = self._canvas.create_arc(4, 4, 60, 60, start=0, extent=110,
                                             style="arc", outline="#4A6FE0", width=5)
        self._spinning = True
        self._spin()

        ctk.CTkLabel(self.root, text="Farmacia Eben-Ezer", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="white").pack()
        self.status_label = ctk.CTkLabel(self.root, text="Iniciando...", font=ctk.CTkFont(size=12),
                                          text_color="#B9BDD6")
        self.status_label.pack(pady=(6, 0))

    def _spin(self):
        if not self._spinning:
            return
        self._angle = (self._angle + 12) % 360
        self._canvas.itemconfig(self._arc, start=self._angle)
        self.root.after(30, self._spin)

    def set_status(self, text: str) -> None:
        try:
            self.root.after(0, lambda: self.status_label.configure(text=text))
        except Exception:
            pass

    def close(self) -> None:
        self._spinning = False
        try:
            self.root.after(0, self.root.destroy)
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main():
    # La pantalla de carga solo tiene sentido en una instalacion NUEVA (elegir
    # modo de trabajo + preparar la base de datos por primera vez, que sí
    # tarda). En una instalacion ya existente (la inmensa mayoria de los
    # arranques) debe abrir directo, igual que siempre lo hizo antes de que
    # se agregara esta pantalla — sin ventana intermedia de por medio.
    instalacion_nueva = cfg.NEEDS_FIRST_RUN_SETUP
    if instalacion_nueva:
        _run_first_time_setup_wizard()

    _boot_and_launch(mostrar_splash=instalacion_nueva)


def _boot_and_launch(mostrar_splash: bool) -> None:
    splash = _BootSplash() if mostrar_splash else None
    boot_result = {"port": None, "done": False}

    def _status(texto: str) -> None:
        if splash:
            splash.set_status(texto)

    def _boot():
        try:
            # Instalar WebView2 en SEGUNDO PLANO, sin bloquear el arranque — la
            # descarga/instalación puede tardar hasta ~2 min o quedar esperando
            # un permiso de Windows (UAC) que en equipos viejos no siempre se ve
            # a primera vista, y eso dejaba el programa entero atorado sin abrir
            # nunca. Si no alcanza a quedar lista para esta sesión, pywebview
            # simplemente usa el motor viejo (igual que siempre) y ya quedará
            # instalada para el siguiente arranque.
            if not _webview2_installed():
                threading.Thread(target=_install_webview2, daemon=True, name="WebView2Install").start()

            _status("Preparando base de datos y usuarios...")
            init_db()

            # Con catálogo público activo el puerto tiene que ser fijo (8000) — si
            # cambiara en cada arranque, el port-forwarding del router dejaría de
            # apuntar al puerto correcto. Sin catálogo público, puerto libre al azar
            # como siempre (más simple, sin choques con otros programas).
            if cfg.CATALOGO_PUBLICO:
                port = cfg.API_PORT
            else:
                port = _find_free_port(cfg.API_PORT)
                if not port:
                    _log_error("No se pudo encontrar puerto libre para la API")
                    return
            cfg.API_PORT = port

            if cfg.TURSO_SYNC:
                _status("Sincronizando con la nube...")
                from app.database.sync_service import import_from_turso, start_background_sync, start_image_watch
                sync_done = threading.Event()

                def _import_and_signal():
                    try:
                        import_from_turso()
                    finally:
                        sync_done.set()

                threading.Thread(target=_import_and_signal, daemon=True, name="TursoImport").start()
                sync_done.wait(timeout=8)  # no colgar el arranque si la red está lenta
                # El latido hace un pull COMPLETO de las ~28 tablas cada vez, sin filtro
                # incremental — a 30s eso es mucha lectura constante en Turso aunque no
                # haya cambios (ni en esta PC ni en otras). Local ya es la fuente de
                # verdad para esta PC; el pull solo existe para ver cambios de OTRAS PCs,
                # así que no necesita ser tan frecuente. 180s sigue siendo rápido para
                # una farmacia con una o dos cajas.
                start_background_sync(interval=180)
                # Hilo aparte, mucho más frecuente (12s) pero barato — solo para fotos de
                # producto nuevas/cambiadas, así se ven en las demás PCs en segundos sin
                # esperar el latido de 180s (ver start_image_watch en sync_service.py).
                start_image_watch(interval=12)

            _status("Iniciando servidor local...")

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

            _status("Cargando pantalla principal...")
            _wait_for_api(port)

            boot_result["port"] = port
        except Exception as e:
            _log_error(f"Boot crash: {e}\n" + traceback.format_exc())
        finally:
            boot_result["done"] = True
            if splash:
                splash.close()

    def _watchdog():
        # Ultimo respaldo: si algo en _boot() se cuelga de verdad (BD bloqueada
        # por otro proceso, red que nunca corta la conexion, etc.) el hilo de
        # arriba se queda atorado para siempre y nunca marca boot_result["done"]
        # - sin esto el programa se queda "abierto" pero nunca muestra el login.
        # Mejor forzar que abra en modo reducido (CustomTkinter, sin esperar la
        # API) que dejarlo pegado sin explicacion.
        time.sleep(60)
        if not boot_result["done"]:
            _log_error("Boot watchdog: el arranque no termino en 60s, forzando apertura")
            boot_result["done"] = True
            if splash:
                splash.close()

    threading.Thread(target=_boot, daemon=True, name="Boot").start()
    threading.Thread(target=_watchdog, daemon=True, name="BootWatchdog").start()

    if splash:
        splash.run()  # bloquea hasta que _boot() (o el watchdog) llame a splash.close()
    else:
        # Instalacion existente: sin ventana de carga, abrir directo como
        # siempre - solo esperar (sin mostrar nada) a que termine el arranque
        # o a que el watchdog fuerce la apertura en modo reducido.
        while not boot_result["done"]:
            time.sleep(0.1)

    _start_ui(boot_result["port"])


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


def _start_ui(port) -> None:
    # port es None cuando el arranque nunca llego a levantar el servidor local
    # (se colgo antes, o el watchdog de main() lo corto) - en ese caso ni
    # siquiera intentar pywebview, ir directo al respaldo de CustomTkinter.
    if port is not None:
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
