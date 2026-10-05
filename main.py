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


# Asistente tipo POS profesional (Square/Shopify): la sucursal trabaja LOCAL
# desde el primer minuto y la nube se conecta cuando se quiera — al conectar la
# cuenta de Turso se busca/crea su base de datos (una sola vez) y se sube todo.
_WIZARD_OPTIONS = [
    {
        "mode": "nueva",
        "icon": "🏪",
        "title": "Sucursal nueva",
        "desc": "Primera caja de una sucursal que abre.\nFunciona sin internet; la nube se conecta cuando quieras.",
        "badge": "NUEVA",
        "accent": "#16A34A",
    },
    {
        "mode": "existente",
        "icon": "☁",
        "title": "Caja de una sucursal existente",
        "desc": "Otra computadora para una sucursal que ya trabaja.\nBaja su inventario, ventas y cajeros de la nube.",
        "badge": None,
        "accent": "#2563EB",
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


def _wizard_ilustracion(tipo: str, color: str, size: int = 76):
    """Fachada de farmacia dibujada con PIL (sin archivos extra) para las
    tarjetas del asistente: 'nueva' (+), 'existente' (nube), 'offline' (sin red)."""
    from PIL import Image, ImageDraw
    S = 4 * size
    k = S / 100.0
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    claro = tuple(int(c + (255 - c) * 0.86) for c in rgb)
    osc = tuple(int(c * 0.62) for c in rgb)
    R = lambda *v: [x * k for x in v]
    d.rounded_rectangle(R(0, 0, 100, 100), radius=24 * k, fill=claro)
    d.ellipse(R(16, 84, 84, 92), fill=(15, 23, 42, 28))
    d.rectangle(R(22, 40, 78, 86), fill="white", outline=osc, width=int(1.6 * k))   # edificio
    d.rounded_rectangle(R(18, 26, 82, 40), radius=3 * k, fill=osc)                    # letrero
    d.rectangle(R(22, 30, 28, 36), fill="white")                                      # cruz médica
    d.rectangle(R(24.3, 31, 25.7, 35), fill=rgb)
    d.rectangle(R(23, 32.3, 27, 33.7), fill=rgb)
    for t in range(4):                                                                 # letras del letrero
        d.rounded_rectangle(R(34 + t * 11, 31.5, 42 + t * 11, 34.5), radius=k, fill=(255, 255, 255, 210))
    for t in range(6):                                                                 # toldo
        x0 = 22 + t * 56 / 6
        col = rgb if t % 2 == 0 else (255, 255, 255)
        d.rectangle(R(x0, 40, x0 + 56 / 6, 47), fill=col)
        d.pieslice(R(x0, 43, x0 + 56 / 6, 51), 0, 180, fill=col)
    d.rectangle(R(27, 55, 47, 73), fill=(224, 242, 254), outline=osc, width=int(1.2 * k))  # vitrina
    d.line(R(37, 55, 37, 73), fill=osc, width=int(k))
    d.rectangle(R(54, 54, 72, 86), fill=osc)                                           # puerta
    d.rectangle(R(57, 57, 69, 67), fill=(186, 230, 253))
    d.ellipse(R(68, 70, 70.5, 72.5), fill=(253, 230, 138))
    # Distintivo de la esquina
    d.ellipse(R(66, 6, 94, 34), fill=rgb, outline="white", width=int(2.2 * k))
    if tipo == "nueva":
        d.rectangle(R(78.6, 12, 81.4, 28), fill="white")
        d.rectangle(R(72, 18.6, 88, 21.4), fill="white")
    elif tipo == "existente":
        d.ellipse(R(71, 17, 81, 26), fill="white")
        d.ellipse(R(76, 13, 87, 24), fill="white")
        d.rounded_rectangle(R(71, 20, 89, 27), radius=3 * k, fill="white")
    else:
        for r in (11, 7):
            d.arc(R(80 - r, 22 - r, 80 + r, 22 + r), 215, 325, fill="white", width=int(2 * k))
        d.ellipse(R(78.5, 21.5, 81.5, 24.5), fill="white")
        d.line(R(71, 12, 89, 30), fill="white", width=int(2.4 * k))
    return im.resize((size, size), Image.LANCZOS)


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
    root.geometry("960x620")
    root.resizable(False, False)
    root.configure(fg_color=BG)
    root.protocol("WM_DELETE_WINDOW", lambda: None)  # no cerrar sin elegir
    root.after(10, lambda: root.eval('tk::PlaceWindow . center'))
    root.attributes("-topmost", True)

    # ── Panel de marca (izquierda): logo, bienvenida y pasos ──────────────
    lado = ctk.CTkFrame(root, fg_color=NAVY, corner_radius=0, width=300)
    lado.pack(side="left", fill="y")
    lado.pack_propagate(False)
    try:
        from PIL import Image as _PILImage
        _logo = _PILImage.open(cfg.BASE_DIR / "assets" / "logos" / "BLANCO_LOGO.png")
        ctk.CTkLabel(lado, text="", image=ctk.CTkImage(_logo, size=(220, 61))).pack(pady=(44, 0))
    except Exception:
        ctk.CTkLabel(lado, text="Farmacia Eben-Ezer", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="white").pack(pady=(50, 0))
    ctk.CTkLabel(lado, text="Bienvenido", font=ctk.CTkFont(size=24, weight="bold"),
                 text_color="white").pack(anchor="w", padx=34, pady=(42, 4))
    ctk.CTkLabel(lado, text="Vamos a preparar este equipo.\nToma menos de un minuto.",
                 font=ctk.CTkFont(size=13), text_color="#B9BDD6", justify="left").pack(anchor="w", padx=34)

    pasos_frame = ctk.CTkFrame(lado, fg_color="transparent")
    pasos_frame.pack(fill="x", padx=34, pady=(40, 0))
    _pasos = []
    for n, texto in enumerate(("Tipo de equipo", "Datos de la sucursal", "Listo para vender"), start=1):
        fila = ctk.CTkFrame(pasos_frame, fg_color="transparent")
        fila.pack(fill="x", pady=7)
        circ = ctk.CTkLabel(fila, text=str(n), width=30, height=30, corner_radius=15,
                            font=ctk.CTkFont(size=13, weight="bold"))
        circ.pack(side="left")
        lbl = ctk.CTkLabel(fila, text=texto, font=ctk.CTkFont(size=13, weight="bold"))
        lbl.pack(side="left", padx=12)
        _pasos.append((circ, lbl))

    def _paso(actual: int):
        for n, (circ, lbl) in enumerate(_pasos, start=1):
            if n < actual:
                circ.configure(text=str(n), fg_color="#16A34A", text_color="white")
                lbl.configure(text_color="#86EFAC")
            elif n == actual:
                circ.configure(text=str(n), fg_color="white", text_color=NAVY)
                lbl.configure(text_color="white")
            else:
                circ.configure(text=str(n), fg_color="#2D3260", text_color="#8A90B8")
                lbl.configure(text_color="#8A90B8")

    ctk.CTkLabel(lado, text="Esto solo se pregunta una vez", font=ctk.CTkFont(size=11),
                 text_color="#6B7199").pack(side="bottom", pady=22)

    # ── Contenido (derecha) ───────────────────────────────────────────────
    body = ctk.CTkFrame(root, fg_color="transparent")
    body.pack(side="left", fill="both", expand=True, padx=40, pady=34)

    titulo = ctk.CTkLabel(body, text="¿Qué es este equipo?",
                          font=ctk.CTkFont(size=22, weight="bold"), text_color="#0F172A")
    titulo.pack(anchor="w")
    subtitulo = ctk.CTkLabel(body, text="Elige cómo va a trabajar esta computadora.",
                             font=ctk.CTkFont(size=13), text_color=GRAY)
    subtitulo.pack(anchor="w", pady=(2, 18))

    def _encabezado(t: str, sub: str):
        titulo.configure(text=t)
        subtitulo.configure(text=sub)

    cards_frame = ctk.CTkFrame(body, fg_color="transparent")
    cards_frame.pack(fill="both", expand=True)

    progress_frame = ctk.CTkFrame(body, fg_color="transparent")
    progress_img = ctk.CTkLabel(progress_frame, text="")
    status_label = ctk.CTkLabel(progress_frame, text="Configurando...", font=ctk.CTkFont(size=14, weight="bold"),
                                 text_color=NAVY, justify="center")
    progress = ctk.CTkProgressBar(progress_frame, width=420, height=8, mode="indeterminate",
                                  progress_color="#16A34A")

    import json as _json

    def _status(texto: str):
        root.after(0, lambda t=texto: status_label.configure(text=t))

    def _mostrar_progreso(tipo: str = "nueva", color: str = "#16A34A"):
        for f in (cards_frame, form_nueva, form_existente):
            f.pack_forget()
        _paso(3)
        _encabezado("Preparando todo...", "No cierres esta ventana — en un momento abre el programa.")
        progress_img.configure(image=ctk.CTkImage(_wizard_ilustracion(tipo, color, 150), size=(150, 150)))
        progress_frame.pack(fill="both", expand=True, pady=(20, 0))
        progress_img.pack(pady=(10, 22))
        status_label.pack(pady=(0, 16))
        progress.pack()
        progress.start()

    def _guardar_setup(data: dict):
        cfg.SETUP_FILE.write_text(_json.dumps(data), encoding="utf-8")
        cfg.reload_setup()

    def _setup_offline():
        try:
            _guardar_setup({"sync_mode": "offline"})
        except Exception as e:
            _log_error(f"Setup offline: {e}")
        _status("Preparando base de datos local...")
        time.sleep(0.8)  # da tiempo visual — que el spinner no parpadee
        root.after(0, root.destroy)

    def _setup_nueva(nombre: str, direccion: str, telefono: str, api_token: str):
        from app.database.sucursales import normalizar_clave
        try:
            clave = normalizar_clave(nombre) or "sucursal"
            _guardar_setup({"sync_mode": "local", "sucursal": {
                "clave": clave, "nombre": nombre, "direccion": direccion, "telefono": telefono}})
            _status(f"Creando Sucursal {nombre}...")
            init_db()
            if api_token:
                from app.services import turso_cuenta
                try:
                    turso_cuenta.conectar_esta_sucursal(api_token, progreso=_status)
                    _status("Sucursal conectada a la nube ✓")
                    time.sleep(1.2)
                except Exception as e:
                    _log_error(f"Conectar sucursal nueva a Turso: {e}")
                    _status("No se pudo conectar a la nube — la sucursal funciona local.\n"
                            "Conéctala después en Configuración → Sucursal.")
                    time.sleep(4)
        except Exception as e:
            _log_error(f"Setup sucursal nueva: {e}\n" + traceback.format_exc())
        root.after(0, root.destroy)

    def _setup_existente(suc: dict, api_token: str, org: str):
        from app.services import turso_cuenta
        try:
            turso_cuenta.unir_caja_a_sucursal(suc, api_token, org, progreso=_status)
        except Exception as e:
            _log_error(f"Setup caja existente: {e}\n" + traceback.format_exc())
        root.after(0, root.destroy)

    # ── Formulario: sucursal nueva ────────────────────────────────────────
    form_nueva = ctk.CTkFrame(body, fg_color="transparent")

    def _campo(parent, etiqueta, placeholder="", secreto=False):
        ctk.CTkLabel(parent, text=etiqueta, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#374151").pack(anchor="w", pady=(8, 2))
        e = ctk.CTkEntry(parent, placeholder_text=placeholder, height=36, show="•" if secreto else "")
        e.pack(fill="x")
        return e

    n_nombre = _campo(form_nueva, "Nombre de la sucursal *", "Ej. López Mateos")
    n_dir = _campo(form_nueva, "Dirección", "Calle, número, colonia, ciudad")
    n_tel = _campo(form_nueva, "Teléfono", "Teléfono de la sucursal")
    n_tok = _campo(form_nueva, "Token de tu cuenta Turso (opcional)", "Pégalo para conectar la nube ahora", secreto=True)
    n_err = ctk.CTkLabel(form_nueva, text="", text_color="#DC2626", font=ctk.CTkFont(size=11))
    n_err.pack(anchor="w", pady=(6, 0))
    n_btns = ctk.CTkFrame(form_nueva, fg_color="transparent")
    n_btns.pack(fill="x", pady=(8, 0))

    def _crear_nueva():
        nombre = n_nombre.get().strip()
        if not nombre:
            n_err.configure(text="Escribe el nombre de la sucursal")
            return
        _mostrar_progreso("nueva", "#16A34A")
        threading.Thread(target=_setup_nueva, args=(nombre, n_dir.get().strip(), n_tel.get().strip(),
                                                    n_tok.get().strip()), daemon=True).start()

    # ── Formulario: caja de una sucursal existente ───────────────────────
    form_existente = ctk.CTkFrame(body, fg_color="transparent")
    # Botones primero (abajo): pack reparte el espacio en orden, así nunca se recortan
    e_btns = ctk.CTkFrame(form_existente, fg_color="transparent")
    e_btns.pack(side="bottom", fill="x", pady=(10, 0))
    e_tok = _campo(form_existente, "Token de Turso *", "El token de tu cuenta — sirve para todas tus sucursales", secreto=True)
    e_ayuda = ctk.CTkLabel(form_existente, justify="left", font=ctk.CTkFont(size=11), text_color=GRAY,
                           text="Se crea en Turso → Settings → API Tokens → Create. Con él se encuentran solas todas tus sucursales.",
                           wraplength=520)
    e_ayuda.pack(anchor="w", pady=(6, 0))

    # Alternativa plegable: URL + token de UNA sola base (oculta por defecto)
    url_frame = ctk.CTkFrame(form_existente, fg_color="#EEF2FF", corner_radius=12)
    url_interior = ctk.CTkFrame(url_frame, fg_color="transparent")
    url_interior.pack(fill="x", padx=14, pady=(4, 12))
    e_url = _campo(url_interior, "URL de la base de datos", "libsql://farmacia-....turso.io")
    ctk.CTkLabel(url_interior, justify="left", font=ctk.CTkFont(size=11), text_color=GRAY, wraplength=480,
                 text="En Turso: entra a la base → copia su 'Database URL'. En el campo de arriba pega el token "
                      "de esa base (botón 'Create Token').").pack(anchor="w", pady=(6, 0))
    _url_abierto = {"v": False}

    def _toggle_url():
        _url_abierto["v"] = not _url_abierto["v"]
        if _url_abierto["v"]:
            e_ayuda.pack_forget()
            url_frame.pack(fill="x", pady=(6, 0), after=url_toggle)
            url_toggle.configure(text="▾  Usar el token de una sola base (con su URL)")
            e_tok.configure(placeholder_text="Token de esa base de datos")
        else:
            url_frame.pack_forget()
            e_ayuda.pack(anchor="w", pady=(6, 0), before=url_toggle)
            e_url.delete(0, "end")
            url_toggle.configure(text="▸  Usar el token de una sola base (con su URL)")
            e_tok.configure(placeholder_text="El token de tu cuenta — sirve para todas tus sucursales")

    url_toggle = ctk.CTkButton(form_existente, text="▸  Usar el token de una sola base (con su URL)",
                               fg_color="transparent", hover_color="#EEF2FF", text_color="#2563EB",
                               anchor="w", height=30, font=ctk.CTkFont(size=12, weight="bold"),
                               command=_toggle_url)
    url_toggle.pack(anchor="w", pady=(10, 0))
    root._wizard_toggle_url = _toggle_url  # para pruebas automáticas
    e_info = ctk.CTkLabel(form_existente, text="", text_color=GRAY, font=ctk.CTkFont(size=11), justify="left")
    e_info.pack(anchor="w", pady=(6, 0))
    e_lista = ctk.CTkFrame(form_existente, fg_color="transparent", height=1)  # crece con los resultados
    e_lista.pack(fill="x")
    e_sel = ctk.StringVar(value="")
    e_estado = {"lista": [], "org": ""}

    def _buscar():
        tok = e_tok.get().strip()
        if not tok:
            e_info.configure(text="Pega el token de tu cuenta de Turso", text_color="#DC2626")
            return
        url = e_url.get().strip() if _url_abierto["v"] else ""
        if _url_abierto["v"] and not url:
            e_info.configure(text="Pega la URL de esa base de datos (libsql://...)", text_color="#DC2626")
            return
        e_info.configure(text="Buscando sucursales...", text_color=GRAY)

        def _bg():
            from app.services import turso_cuenta
            try:
                if url:   # token de UNA base de datos + su URL
                    org = ""
                    lista = [turso_cuenta.sucursal_por_token_de_bd(url, tok)]
                else:     # token de la cuenta: todas las sucursales
                    org = turso_cuenta.detectar_org(tok)
                    lista = turso_cuenta.sucursales_de_cuenta(tok, org, incluir_sin_identidad=True)
            except Exception as e:
                root.after(0, lambda m=str(e): e_info.configure(text=m, text_color="#DC2626"))
                return

            def _pintar():
                for w in e_lista.winfo_children():
                    w.destroy()
                e_estado.update(lista=lista, org=org)
                if not lista:
                    e_info.configure(text="No hay sucursales conectadas a la nube en esta cuenta.\n"
                                          "Elige 'Sucursal nueva' para crear la primera.", text_color="#D97706")
                    return
                e_info.configure(text="¿De qué sucursal es esta caja?", text_color="#0F172A")
                for suc in lista:
                    ctk.CTkRadioButton(e_lista, text=f"Sucursal {suc['nombre']}", variable=e_sel,
                                       value=suc["clave"]).pack(anchor="w", pady=4)
                e_sel.set(lista[0]["clave"])
            root.after(0, _pintar)
        threading.Thread(target=_bg, daemon=True).start()

    def _conectar_existente():
        suc = next((x for x in e_estado["lista"] if x["clave"] == e_sel.get()), None)
        if not suc:
            e_info.configure(text="Primero busca y elige la sucursal", text_color="#DC2626")
            return
        _mostrar_progreso("existente", "#2563EB")
        threading.Thread(target=_setup_existente, args=(suc, e_tok.get().strip(), e_estado["org"]),
                         daemon=True).start()

    def _volver():
        form_nueva.pack_forget()
        form_existente.pack_forget()
        _paso(1)
        _encabezado("¿Qué es este equipo?", "Elige cómo va a trabajar esta computadora.")
        cards_frame.pack(fill="both", expand=True)

    for frame, accion, texto in ((n_btns, _crear_nueva, "Crear sucursal"),
                                 (e_btns, _conectar_existente, "Conectar esta caja")):
        ctk.CTkButton(frame, text="← Volver", fg_color="#E2E8F0", text_color="#0F172A",
                      hover_color="#CBD5E1", width=110, height=38, command=_volver).pack(side="left")
        ctk.CTkButton(frame, text=texto, fg_color=NAVY, height=38, command=accion).pack(side="right")
    ctk.CTkButton(e_btns, text="Buscar sucursales", fg_color="#2563EB", height=38,
                  command=_buscar).pack(side="right", padx=8)

    def _elegir(mode: str):
        if mode == "offline":
            _mostrar_progreso("offline", "#D97706")
            threading.Thread(target=_setup_offline, daemon=True).start()
            return
        cards_frame.pack_forget()
        _paso(2)
        if mode == "nueva":
            _encabezado("Sucursal nueva", "Funciona sin internet desde el primer minuto. La nube se conecta cuando quieras.")
        else:
            _encabezado("Caja de una sucursal existente", "Pega el token de tu cuenta de Turso y elige la sucursal.")
        (form_nueva if mode == "nueva" else form_existente).pack(fill="both", expand=True)

    root._wizard_elegir = _elegir  # para pruebas automáticas del asistente
    root._wizard_volver = _volver
    root._wizard_progreso = _mostrar_progreso

    def _make_card(parent, opt):
        card = ctk.CTkFrame(parent, fg_color="white", corner_radius=16, border_width=2,
                            border_color=BORDER, height=124)
        card.pack(fill="x", pady=7)
        card.pack_propagate(False)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=12)

        img = ctk.CTkImage(_wizard_ilustracion(opt["mode"], opt["accent"], 92), size=(92, 92))
        icon = ctk.CTkLabel(inner, text="", image=img)
        icon.pack(side="left", padx=(0, 18))

        text_col = ctk.CTkFrame(inner, fg_color="transparent")
        text_col.pack(side="left", fill="both", expand=True, pady=6)

        title_row = ctk.CTkFrame(text_col, fg_color="transparent")
        title_row.pack(anchor="w", fill="x")
        ctk.CTkLabel(title_row, text=opt["title"], font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#0F172A").pack(side="left")
        if opt["badge"]:
            ctk.CTkLabel(title_row, text=opt["badge"], font=ctk.CTkFont(size=9, weight="bold"),
                         text_color="white", fg_color=opt["accent"], corner_radius=6, padx=8,
                         height=18).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(text_col, text=opt["desc"], font=ctk.CTkFont(size=12), text_color=GRAY,
                     justify="left", anchor="w").pack(anchor="w", pady=(6, 0))
        flecha = ctk.CTkLabel(inner, text="›", font=ctk.CTkFont(size=30), text_color="#CBD5E1")
        flecha.pack(side="right", padx=(8, 4))

        # Toda la tarjeta es clickeable, con hover (borde + flecha del color de la opción).
        def _on(_e=None):
            card.configure(border_color=opt["accent"], fg_color="#FBFCFE")
            flecha.configure(text_color=opt["accent"])

        def _off(_e=None):
            card.configure(border_color=BORDER, fg_color="white")
            flecha.configure(text_color="#CBD5E1")

        widgets = [card, inner, icon, text_col, title_row, flecha] + list(text_col.winfo_children()) + list(title_row.winfo_children())
        for w in widgets:
            w.bind("<Button-1>", lambda e: _elegir(opt["mode"]))
            w.bind("<Enter>", _on)
            w.bind("<Leave>", _off)
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    for opt in _WIZARD_OPTIONS:
        _make_card(cards_frame, opt)
    _paso(1)

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
    # Si falta WebView2, pywebview cae en silencio al motor viejo de Internet
    # Explorer: la ventana SI abre, pero se ve sin estilos (como si no tuviera
    # diseño) y con menus/modales apilados. Mostrar la pantalla de carga
    # también en este caso — así hay progreso visible mientras se instala en
    # vez de abrir de inmediato con el motor roto. El límite de 60s en
    # _boot_and_launch sigue de respaldo por si la instalación tarda de más.
    falta_webview2 = not _webview2_installed()
    if instalacion_nueva:
        # El .exe compilado corre con console=False (sin ventana de consola) -
        # si el asistente falla por cualquier motivo (ej. un equipo viejo con
        # problemas para dibujar la interfaz), antes eso tumbaba el programa
        # entero SIN NINGUN aviso visible, ni siquiera un traceback en algun
        # lado. Mejor seguir sin el asistente (queda "turso" como modo por
        # defecto, ver app/config.py) que desaparecer sin explicacion.
        try:
            _run_first_time_setup_wizard()
        except Exception as e:
            _log_error(f"Asistente de primer arranque falló: {e}\n" + traceback.format_exc())

    mostrar_splash = instalacion_nueva or falta_webview2
    try:
        _boot_and_launch(mostrar_splash=mostrar_splash, esperar_webview2=falta_webview2)
    except Exception as e:
        _log_error(f"Boot con splash falló: {e}\n" + traceback.format_exc())
        # Si la pantalla de carga (tkinter/customtkinter) fue lo que fallo, no
        # tiene sentido tirar todo el programa por eso — reintentar sin ella
        # antes de rendirse. El arranque en si (BD, servidor local) no depende
        # de que la ventana de carga exista.
        if mostrar_splash:
            try:
                _boot_and_launch(mostrar_splash=False, esperar_webview2=False)
                return
            except Exception as e2:
                e = e2

        # Ultimo respaldo real: si CUALQUIER COSA truena antes de llegar a
        # abrir una ventana, mostrar un mensaje nativo de Windows en vez de
        # que el programa desaparezca sin ningun rastro (console=False no deja
        # ver ni un traceback). El log queda para poder diagnosticar despues.
        _log_error(f"Fallo fatal antes de abrir la ventana principal: {e}\n" + traceback.format_exc())
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Farmacia Eben-Ezer no pudo abrir. Se guardó el detalle del error en "
                f"{cfg.DATA_DIR / 'error.log'} — comparte ese archivo con soporte.",
                "Farmacia Eben-Ezer — POS",
                0x10,  # MB_ICONERROR
            )
        except Exception:
            pass


def _boot_and_launch(mostrar_splash: bool, esperar_webview2: bool = False) -> None:
    splash = _BootSplash() if mostrar_splash else None
    boot_result = {"port": None, "done": False}

    def _status(texto: str) -> None:
        if splash:
            splash.set_status(texto)

    def _boot():
        try:
            # Instalar WebView2 en un hilo aparte — nunca debe colgar el
            # arranque indefinidamente (descarga/UAC puede tardar hasta ~2
            # min). Cuando SÍ hay pantalla de carga visible por falta de
            # WebView2 (esperar_webview2=True), vale la pena esperar un rato
            # acotado a que termine: si no, pywebview cae en silencio al motor
            # viejo de Internet Explorer y la ventana abre sin estilos/diseño.
            # El watchdog de 60s de más abajo sigue siendo el límite real si
            # la descarga es muy lenta — mejor abrir con el motor viejo que
            # quedarse pegado.
            if not _webview2_installed():
                hilo_webview2 = threading.Thread(target=_install_webview2, daemon=True, name="WebView2Install")
                hilo_webview2.start()
                if esperar_webview2:
                    _status("Preparando componente de Windows (primera vez)...")
                    hilo_webview2.join(timeout=40)

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
    # (se colgo antes, o el watchdog de main() lo corto).
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
            _log_error(f"pywebview falló ({type(e).__name__}: {e})\n" + traceback.format_exc())

    # Ya no existe una pantalla de respaldo distinta (el viejo login de
    # CustomTkinter se eliminó): si la interfaz moderna no pudo abrir, avisar
    # claramente en vez de mostrar una pantalla distinta a la real. La causa
    # más común es que falte el runtime WebView2 en el equipo.
    _log_error("No se pudo abrir la interfaz moderna (pywebview) y ya no hay pantalla de respaldo.")
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            "Farmacia Eben-Ezer no pudo abrir la interfaz. Esto suele pasar si "
            "falta el componente WebView2 de Windows o si el equipo no tuvo "
            "internet para instalarlo. Reinicia el programa; si el problema "
            "sigue, comparte este archivo con soporte:\n"
            f"{cfg.DATA_DIR / 'error.log'}",
            "Farmacia Eben-Ezer — POS",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
