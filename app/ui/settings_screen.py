import customtkinter as ctk
from tkinter import messagebox
import tkinter as tk
from app.database.connection import get_db_session
from app.database.models import Configuracion
from app.services.printer_service import printer_service, PrinterService
from app.services.scanner_service import scanner_service
import app.config as cfg


class SettingsScreen(ctk.CTkFrame):
    def __init__(self, parent, user):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.user = user
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        scroll.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(scroll, text="⚙️ Configuración", font=ctk.CTkFont(size=20, weight="bold")).grid(
            row=0, column=0, pady=(0, 16), sticky="w")

        # Seccion: Info farmacia
        self._seccion(scroll, "🏥 Información de la Farmacia", row=1)
        info_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        info_frame.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        info_frame.grid_columnconfigure(1, weight=1)

        farm_fields = [
            ("Nombre de la Farmacia:", "farmacia_nombre"),
            ("Dirección:", "farmacia_direccion"),
            ("Teléfono:", "farmacia_telefono"),
            ("RFC:", "farmacia_rfc"),
        ]
        self.farm_entries = {}
        for i, (label, key) in enumerate(farm_fields):
            ctk.CTkLabel(info_frame, text=label, anchor="e", font=ctk.CTkFont(size=12)).grid(
                row=i, column=0, padx=(16, 8), pady=8, sticky="e")
            e = ctk.CTkEntry(info_frame, height=34)
            e.grid(row=i, column=1, padx=(0, 16), pady=8, sticky="ew")
            self.farm_entries[key] = e

        ctk.CTkButton(
            info_frame, text="💾 Guardar Info Farmacia", height=36, width=200,
            fg_color="#4CAF50", hover_color="#388E3C",
            command=lambda: self._guardar_seccion(self.farm_entries)
        ).grid(row=len(farm_fields), column=0, columnspan=2, padx=16, pady=(4, 16))

        # Seccion: Impresora
        self._seccion(scroll, "🖨️ Impresora de Tickets", row=3)
        print_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        print_frame.grid(row=4, column=0, sticky="ew", pady=(0, 16))
        print_frame.grid_columnconfigure(1, weight=1)

        # Tipo
        ctk.CTkLabel(print_frame, text="Tipo:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(16, 8), pady=8, sticky="e")
        self.opt_impresora = ctk.CTkOptionMenu(
            print_frame,
            values=["windows", "usb", "serial", "network"],
            command=self._on_printer_type_change,
        )
        self.opt_impresora.grid(row=0, column=1, padx=(0, 16), pady=8, sticky="ew")

        # Ancho de papel
        ctk.CTkLabel(print_frame, text="Papel:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(16, 8), pady=8, sticky="e")
        self.opt_ancho = ctk.CTkOptionMenu(print_frame, values=["50mm  (26 col)", "58mm  (32 col)", "80mm  (48 col)"])
        self.opt_ancho.grid(row=1, column=1, padx=(0, 16), pady=8, sticky="ew")

        # Fila Windows: lista de impresoras
        self._row_win = ctk.CTkFrame(print_frame, fg_color="transparent")
        self._row_win.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4))
        self._row_win.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._row_win, text="Impresora:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 8), sticky="e")
        
        self.opt_win_printer = ctk.CTkOptionMenu(
            self._row_win, values=["(cargando...)"],
            command=self._on_win_printer_change
        )
        self.opt_win_printer.grid(row=0, column=1, sticky="ew")
        
        ctk.CTkButton(self._row_win, text="↺", width=36, height=34,
                      command=self._refresh_win_printers).grid(row=0, column=2, padx=(6, 0))

        # Fila nombre manual (se muestra si eligen "Manual")
        self._row_win_manual = ctk.CTkFrame(print_frame, fg_color="transparent")
        self._row_win_manual.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4))
        self._row_win_manual.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._row_win_manual, text="Nombre manual:", anchor="e",
                     font=ctk.CTkFont(size=11), text_color="gray60").grid(row=0, column=0, padx=(0, 8), sticky="e")
        self.entry_win_manual = ctk.CTkEntry(self._row_win_manual, height=34, placeholder_text="Ej: XP-58")
        self.entry_win_manual.grid(row=0, column=1, sticky="ew")

        # Fila manual (USB/Serial/Net): puerto / IP
        self._row_port = ctk.CTkFrame(print_frame, fg_color="transparent")
        self._row_port.grid(row=4, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 4))
        self._row_port.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._row_port, text="Puerto/IP:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 8), sticky="e")
        self.entry_puerto = ctk.CTkEntry(self._row_port, height=34,
                                          placeholder_text="COM1  ó  192.168.1.x:9100")
        self.entry_puerto.grid(row=0, column=1, sticky="ew")

        btn_frame = ctk.CTkFrame(print_frame, fg_color="transparent")
        btn_frame.grid(row=5, column=0, columnspan=2, padx=16, pady=(8, 8))
        ctk.CTkButton(btn_frame, text="💾 Guardar", height=36, fg_color="#4CAF50",
                      command=self._guardar_impresora).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="🔌 Conectar y Probar", height=36,
                      fg_color="#2196F3", hover_color="#1976D2",
                      command=self._probar_impresora).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_frame, text="🔍 Diagnóstico", height=36,
                      fg_color="#9C27B0", hover_color="#7B1FA2",
                      command=self._abrir_diag_impresora).pack(side="left")

        self.lbl_printer_status = ctk.CTkLabel(print_frame, text="Estado: Desconectada",
                                                text_color="#F44336", font=ctk.CTkFont(size=12))
        self.lbl_printer_status.grid(row=6, column=0, columnspan=2, padx=16, pady=(0, 12))

        # Seccion: API
        self._seccion(scroll, "🌐 API REST (Conexión con App)", row=5)
        api_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        api_frame.grid(row=6, column=0, sticky="ew", pady=(0, 16))

        api_url = f"http://localhost:{cfg.API_PORT}/api"
        ctk.CTkLabel(api_frame, text="URL de la API:", font=ctk.CTkFont(size=13)).pack(
            anchor="w", padx=16, pady=(12, 4))
        url_frame = ctk.CTkFrame(api_frame, fg_color=("#f5f5f5", "#3b3b3b"), corner_radius=6)
        url_frame.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkLabel(url_frame, text=api_url, font=ctk.CTkFont(size=12, family="Courier"),
                     text_color="#2196F3").pack(padx=10, pady=8, anchor="w")

        ctk.CTkLabel(api_frame, text="Documentación interactiva (Swagger):", font=ctk.CTkFont(size=13)).pack(
            anchor="w", padx=16, pady=(0, 4))
        docs_frame = ctk.CTkFrame(api_frame, fg_color=("#f5f5f5", "#3b3b3b"), corner_radius=6)
        docs_frame.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(docs_frame, text=f"http://localhost:{cfg.API_PORT}/docs",
                     font=ctk.CTkFont(size=12, family="Courier"), text_color="#4CAF50").pack(
            padx=10, pady=8, anchor="w")

        ctk.CTkLabel(api_frame,
                     text="Tu app móvil/web debe hacer POST a /api/auth/login primero para obtener el token,\n"
                          "luego incluirlo en el header: Authorization: Bearer <token>",
                     font=ctk.CTkFont(size=11), text_color="gray60", justify="left").pack(
            padx=16, pady=(0, 12), anchor="w")

        # Seccion: Escáner
        self._seccion(scroll, "📡 Escáner de Código de Barras", row=7)
        scan_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        scan_frame.grid(row=8, column=0, sticky="ew", pady=(0, 16))
        scan_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(scan_frame, text="Modo de conexión:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(16, 8), pady=8, sticky="e")
        self.opt_scanner_modo = ctk.CTkOptionMenu(
            scan_frame,
            values=["hid", "serial"],
            command=self._on_scanner_mode_change,
        )
        self.opt_scanner_modo.grid(row=0, column=1, padx=(0, 16), pady=8, sticky="ew")

        ctk.CTkLabel(scan_frame, text="Puerto COM:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(16, 8), pady=8, sticky="e")

        port_row = ctk.CTkFrame(scan_frame, fg_color="transparent")
        port_row.grid(row=1, column=1, padx=(0, 16), pady=8, sticky="ew")
        port_row.grid_columnconfigure(0, weight=1)

        self._scan_ports: list[str] = []
        self.opt_scanner_puerto = ctk.CTkOptionMenu(port_row, values=["(seleccionar)"])
        self.opt_scanner_puerto.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(port_row, text="↺", width=36, height=34,
                      command=self._refresh_ports).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(scan_frame, text="Velocidad (baud):", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=2, column=0, padx=(16, 8), pady=8, sticky="e")
        self.opt_scanner_baud = ctk.CTkOptionMenu(
            scan_frame,
            values=["9600", "115200", "38400", "19200", "4800"],
        )
        self.opt_scanner_baud.grid(row=2, column=1, padx=(0, 16), pady=8, sticky="ew")

        scan_btn_row = ctk.CTkFrame(scan_frame, fg_color="transparent")
        scan_btn_row.grid(row=3, column=0, columnspan=2, padx=16, pady=(4, 8))
        ctk.CTkButton(scan_btn_row, text="🔍 Detectar puertos", height=36,
                      command=self._refresh_ports).pack(side="left", padx=(0, 8))
        ctk.CTkButton(scan_btn_row, text="💾 Guardar y conectar", height=36,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._guardar_scanner).pack(side="left", padx=(0, 8))
        ctk.CTkButton(scan_btn_row, text="🔌 Probar", height=36,
                      fg_color="#2196F3", hover_color="#1976D2",
                      command=self._probar_scanner).pack(side="left", padx=(0, 8))
        ctk.CTkButton(scan_btn_row, text="🔎 Diagnóstico", height=36,
                      fg_color="#9C27B0", hover_color="#7B1FA2",
                      command=self._abrir_diagnostico).pack(side="left")

        self.lbl_scanner_status = ctk.CTkLabel(
            scan_frame, text="Estado: HID (teclado) activo",
            text_color="#4CAF50", font=ctk.CTkFont(size=12))
        self.lbl_scanner_status.grid(row=4, column=0, columnspan=2, padx=16, pady=(0, 12))

        ctk.CTkLabel(
            scan_frame,
            text="HID = escáner conectado como teclado USB/Bluetooth (modo por defecto).\n"
                 "Serial = escáner vía puerto COM (Bluetooth SPP, USB-CDC, RS-232).",
            font=ctk.CTkFont(size=11), text_color="gray60", justify="left",
        ).grid(row=5, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="w")

        # Seccion: Sistema
        self._seccion(scroll, "🖥️ Sistema", row=9)
        sys_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        sys_frame.grid(row=10, column=0, sticky="ew", pady=(0, 16))

        ctk.CTkLabel(sys_frame, text="Modo de apariencia:", font=ctk.CTkFont(size=12)).pack(
            anchor="w", padx=16, pady=(12, 4))
        self.opt_apariencia = ctk.CTkOptionMenu(
            sys_frame, values=["System", "Light", "Dark"],
            command=lambda v: ctk.set_appearance_mode(v)
        )
        self.opt_apariencia.pack(anchor="w", padx=16, pady=(0, 12))

        ctk.CTkLabel(sys_frame, text=f"Versión: {cfg.VERSION}  |  Base de datos: {cfg.DB_PATH}",
                     font=ctk.CTkFont(size=11), text_color="gray60").pack(
            padx=16, pady=(0, 12), anchor="w")

        # ── Base de Datos + Zona de Peligro (solo admin) ──────────────────────
        from app.database.models import RolUsuario
        if self.user.rol == RolUsuario.admin:
            self._seccion(scroll, "🗄️ Base de Datos", row=11)
            db_frame = ctk.CTkFrame(scroll, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
            db_frame.grid(row=12, column=0, sticky="ew", pady=(0, 16))

            ctk.CTkLabel(db_frame, text="Registros en base de datos local:",
                         font=ctk.CTkFont(size=12, weight="bold")).pack(
                anchor="w", padx=16, pady=(12, 4))

            counts_frame = ctk.CTkFrame(db_frame, fg_color=("#f5f5f5", "#3b3b3b"), corner_radius=6)
            counts_frame.pack(fill="x", padx=16, pady=(0, 8))
            counts_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

            _DISPLAY_TABLES = [
                ("productos",   "Productos"),   ("lotes",      "Lotes"),
                ("ventas",      "Ventas"),       ("items_venta","Items venta"),
                ("compras",     "Compras"),      ("clientes",   "Clientes"),
                ("proveedores", "Proveedores"),  ("categorias", "Categorías"),
                ("cortes_caja", "Cortes caja"),  ("usuarios",   "Usuarios"),
            ]
            self._db_count_labels: dict[str, ctk.CTkLabel] = {}
            for idx, (tbl, display) in enumerate(_DISPLAY_TABLES):
                col = (idx % 2) * 2
                row_n = idx // 2
                ctk.CTkLabel(counts_frame, text=f"{display}:", anchor="e",
                             font=ctk.CTkFont(size=11), text_color="gray60").grid(
                    row=row_n, column=col, padx=(10, 4), pady=3, sticky="e")
                lbl = ctk.CTkLabel(counts_frame, text="—", anchor="w",
                                   font=ctk.CTkFont(size=11, weight="bold"))
                lbl.grid(row=row_n, column=col + 1, padx=(0, 16), pady=3, sticky="w")
                self._db_count_labels[tbl] = lbl

            sync_row = ctk.CTkFrame(db_frame, fg_color="transparent")
            sync_row.pack(fill="x", padx=16, pady=(4, 12))
            self.lbl_sync_status = ctk.CTkLabel(
                sync_row, text="", font=ctk.CTkFont(size=11), text_color="gray60")
            self.lbl_sync_status.pack(side="right", padx=(8, 0))
            ctk.CTkButton(
                sync_row, text="☁  Sincronizar con Turso ahora", height=34,
                fg_color="#2196F3", hover_color="#1565C0",
                command=self._ejecutar_sync,
            ).pack(side="left")

            self._cargar_db_stats()

            self._seccion(scroll, "⚠️ Zona de Peligro", row=13)
            danger_frame = ctk.CTkFrame(
                scroll, corner_radius=10,
                fg_color=("#fff", "#2b2b2b"),
                border_width=2, border_color="#EF4444",
            )
            danger_frame.grid(row=14, column=0, sticky="ew", pady=(0, 16))

            # ── Botón 1: ventas + historial + cierres ─────────────────────────
            ctk.CTkLabel(
                danger_frame, text="Eliminar ventas, historial y cierres de caja",
                font=ctk.CTkFont(size=13, weight="bold"), text_color="#EF4444",
            ).pack(anchor="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(
                danger_frame,
                text="Borra ventas, movimientos de stock, auditoría y cortes de caja.\n"
                     "Conserva productos, clientes, proveedores y categorías.",
                font=ctk.CTkFont(size=11), text_color="gray60", justify="left",
            ).pack(anchor="w", padx=16, pady=(0, 6))
            ctk.CTkButton(
                danger_frame, text="🗑  Eliminar ventas / historial / cierres",
                height=34, fg_color="#F97316", hover_color="#C2410C", text_color="white",
                command=lambda: self._dlg_pin(
                    "Eliminar ventas, historial y cierres",
                    "Se eliminarán ventas, movimientos, auditoría\ny cortes de caja (local + Turso).",
                    self._ejecutar_purgar_ventas,
                ),
            ).pack(padx=16, pady=(0, 14), anchor="w")

            # Separador
            ctk.CTkFrame(danger_frame, height=1, fg_color="#EF4444").pack(fill="x", padx=16)

            # ── Botón 2: borrar TODO ───────────────────────────────────────────
            ctk.CTkLabel(
                danger_frame, text="Eliminar TODOS los registros",
                font=ctk.CTkFont(size=13, weight="bold"), text_color="#EF4444",
            ).pack(anchor="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(
                danger_frame,
                text="Borra absolutamente todo: ventas, productos, clientes, proveedores,\n"
                     "categorías, compras, movimientos, cortes y auditoría.\n"
                     "Se conservan únicamente los usuarios. Local + Turso. IRREVERSIBLE.",
                font=ctk.CTkFont(size=11), text_color="gray60", justify="left",
            ).pack(anchor="w", padx=16, pady=(0, 6))
            ctk.CTkButton(
                danger_frame, text="💀  Eliminar TODO sin dejar nada",
                height=34, fg_color="#EF4444", hover_color="#7F1D1D", text_color="white",
                command=lambda: self._dlg_pin(
                    "Eliminar TODOS los registros",
                    "Se eliminará todo excepto usuarios.\nEsta acción es IRREVERSIBLE.",
                    self._ejecutar_purgar_todo,
                ),
            ).pack(padx=16, pady=(0, 16), anchor="w")

        self._cargar_config()

    _PIN_ADMIN = "171215"

    def _dlg_pin(self, titulo: str, descripcion: str, on_confirm):
        """Diálogo de confirmación con PIN de administrador."""
        dlg = ctk.CTkToplevel(self)
        dlg.title(f"⚠️ {titulo}")
        dlg.geometry("420x280")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - 420) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 280) // 2
        dlg.geometry(f"420x280+{x}+{y}")

        ctk.CTkLabel(dlg, text=f"⚠️  {titulo}",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#EF4444", wraplength=380).pack(pady=(20, 6))
        ctk.CTkLabel(dlg, text=descripcion,
                     font=ctk.CTkFont(size=11), text_color="gray60",
                     wraplength=380, justify="center").pack(pady=(0, 12))
        ctk.CTkLabel(dlg, text="Ingresa el PIN de administrador:",
                     font=ctk.CTkFont(size=12)).pack(pady=(0, 4))

        entry = ctk.CTkEntry(dlg, width=160, height=36, justify="center", show="●")
        entry.pack(pady=(0, 4))
        entry.focus()

        lbl_err = ctk.CTkLabel(dlg, text="", text_color="#EF4444",
                               font=ctk.CTkFont(size=11))
        lbl_err.pack(pady=(0, 8))

        def _ok(event=None):
            if entry.get().strip() != self._PIN_ADMIN:
                lbl_err.configure(text="PIN incorrecto")
                entry.delete(0, "end")
                return
            dlg.destroy()
            on_confirm()

        entry.bind("<Return>", _ok)
        ctk.CTkButton(dlg, text="Confirmar", height=34,
                      fg_color="#EF4444", hover_color="#B91C1C", text_color="white",
                      command=_ok).pack(pady=(0, 6))
        ctk.CTkButton(dlg, text="Cancelar", height=32,
                      fg_color="transparent", border_width=1, border_color="#ccc",
                      command=dlg.destroy).pack()

    def _cargar_db_stats(self):
        import threading
        from app.database.sync_service import get_db_stats

        def _run():
            try:
                stats = get_db_stats()
                def _apply():
                    for tbl, lbl in self._db_count_labels.items():
                        n = stats.get(tbl, -1)
                        lbl.configure(text=str(n) if n >= 0 else "?")
                self.after(0, _apply)
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True, name="DBStats").start()

    def _ejecutar_sync(self):
        import threading
        from app.database.sync_service import force_sync
        from app.ui import toast

        def _run():
            try:
                self.after(0, lambda: self.lbl_sync_status.configure(
                    text="Sincronizando…", text_color="#FF9800"))
                stats = force_sync()
                def _done():
                    for tbl, lbl in self._db_count_labels.items():
                        n = stats.get(tbl, -1)
                        lbl.configure(text=str(n) if n >= 0 else "?")
                    self.lbl_sync_status.configure(
                        text="Sincronización completa", text_color="#4CAF50")
                    toast.show("Sincronización con Turso completa", kind="success", duration=4000)
                self.after(0, _done)
            except Exception as exc:
                self.after(0, lambda e=exc: (
                    self.lbl_sync_status.configure(text=f"Error: {e}", text_color="#EF4444"),
                    toast.show(f"Error de sync: {e}", kind="error", duration=7000),
                ))

        threading.Thread(target=_run, daemon=True, name="ForceSync").start()

    def _ejecutar_purgar_ventas(self):
        import threading
        from app.database.sync_service import purgar_ventas_historial_cierres
        from app.ui import toast

        def _run():
            try:
                purgar_ventas_historial_cierres()
                self.after(0, lambda: toast.show(
                    "Ventas, historial y cierres eliminados", kind="success", duration=5000))
            except Exception as exc:
                self.after(0, lambda e=exc: toast.show(
                    f"Error: {e}", kind="error", duration=7000))

        toast.show("Eliminando ventas, historial y cierres…", kind="warning", duration=15000)
        threading.Thread(target=_run, daemon=True, name="PurgarVentas").start()

    def _ejecutar_purgar_todo(self):
        import threading
        from app.database.sync_service import purgar_todos_los_datos
        from app.ui import toast

        def _run():
            try:
                purgar_todos_los_datos()
                self.after(0, lambda: toast.show(
                    "Todos los registros eliminados", kind="success", duration=5000))
            except Exception as exc:
                self.after(0, lambda e=exc: toast.show(
                    f"Error: {e}", kind="error", duration=7000))

        toast.show("Eliminando todos los registros…", kind="warning", duration=15000)
        threading.Thread(target=_run, daemon=True, name="PurgarTodo").start()

    def _seccion(self, parent, titulo: str, row: int):
        ctk.CTkLabel(parent, text=titulo, font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=row, column=0, pady=(8, 4), sticky="w")

    def _cargar_config(self):
        db = get_db_session()
        try:
            configs = {c.clave: c.valor for c in db.query(Configuracion).all()}
        finally:
            db.close()

        for key, entry in self.farm_entries.items():
            entry.delete(0, "end")
            entry.insert(0, configs.get(key, ""))

        tipo = configs.get("impresora_tipo", "windows")
        self.opt_impresora.set(tipo)
        self.entry_puerto.delete(0, "end")
        self.entry_puerto.insert(0, configs.get("impresora_puerto", ""))

        # Ancho de papel
        ancho = configs.get("impresora_ancho", "32")
        if ancho == "48":
            self.opt_ancho.set("80mm  (48 col)")
        elif ancho == "26":
            self.opt_ancho.set("50mm  (26 col)")
        else:
            self.opt_ancho.set("58mm  (32 col)")

        # Windows printer list
        self._refresh_win_printers()
        saved_wprinter = configs.get("impresora_nombre", "")
        printers = PrinterService.list_windows_printers()
        if saved_wprinter in printers:
            self.opt_win_printer.set(saved_wprinter)

        self._on_printer_type_change(tipo)

        # Scanner
        modo = configs.get("scanner_modo", "hid")
        self.opt_scanner_modo.set(modo)
        self.opt_scanner_baud.set(configs.get("scanner_baud", "9600"))
        self._refresh_ports()
        saved_port = configs.get("scanner_puerto", "")
        if saved_port and saved_port in self._scan_ports:
            self.opt_scanner_puerto.set(saved_port)
        self._on_scanner_mode_change(modo)
        self._update_scanner_status()

    def _guardar_seccion(self, entries: dict):
        db = get_db_session()
        try:
            for key, entry in entries.items():
                valor = entry.get().strip()
                c = db.query(Configuracion).filter(Configuracion.clave == key).first()
                if c:
                    c.valor = valor
                else:
                    db.add(Configuracion(clave=key, valor=valor))
            db.commit()
            messagebox.showinfo("OK", "Configuración guardada")
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()

    def _on_printer_type_change(self, tipo: str):
        if tipo == "windows":
            self._row_win.grid()
            self._row_win_manual.grid_remove()
            self._row_port.grid_remove()
            self._refresh_win_printers()
        else:
            self._row_win.grid_remove()
            self._row_win_manual.grid_remove()
            self._row_port.grid()

    def _on_win_printer_change(self, val: str):
        if val == "Escribir nombre manualmente...":
            self._row_win_manual.grid()
        else:
            self._row_win_manual.grid_remove()

    def _refresh_win_printers(self):
        printers = PrinterService.list_windows_printers()
        options = []
        if printers:
            options.extend(printers)
        
        options.append("Escribir nombre manualmente...")
        self.opt_win_printer.configure(values=options)
        
        current = self.opt_win_printer.get()
        if current not in options:
            if printers:
                self.opt_win_printer.set(printers[0])
            else:
                self.opt_win_printer.set("Escribir nombre manualmente...")
                self._row_win_manual.grid()
        
        if self.opt_win_printer.get() == "Escribir nombre manualmente...":
            self._row_win_manual.grid()
        else:
            self._row_win_manual.grid_remove()

    def _guardar_impresora(self):
        tipo = self.opt_impresora.get()
        _ancho_sel = self.opt_ancho.get()
        ancho = "48" if "80mm" in _ancho_sel else "26" if "50mm" in _ancho_sel else "32"
        if tipo == "windows":
            sel = self.opt_win_printer.get()
            if sel == "Escribir nombre manualmente...":
                nombre_win = self.entry_win_manual.get().strip()
                puerto = nombre_win
            else:
                nombre_win = sel
                puerto = sel
        else:
            puerto = self.entry_puerto.get().strip()
            nombre_win = ""

        if tipo == "windows" and not nombre_win:
            messagebox.showwarning("Atención", "Escribe el nombre de la impresora")
            return

        db = get_db_session()
        try:
            for key, valor in [
                ("impresora_tipo",   tipo),
                ("impresora_puerto", puerto),
                ("impresora_nombre", nombre_win),
                ("impresora_ancho",  ancho),
            ]:
                c = db.query(Configuracion).filter(Configuracion.clave == key).first()
                if c:
                    c.valor = valor
                else:
                    db.add(Configuracion(clave=key, valor=valor))
            db.commit()
            messagebox.showinfo("OK", "Configuración de impresora guardada")
        finally:
            db.close()

    def _abrir_diag_impresora(self):
        import traceback
        win = ctk.CTkToplevel(self)
        win.title("Diagnóstico de Impresora")
        win.geometry("500x400")
        win.grab_set()

        ctk.CTkLabel(win, text="🔎 Diagnóstico de Impresora",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 4))
        
        log_box = tk.Text(win, height=15, width=60, font=("Consolas", 10), bg="#1e1e1e", fg="#d4d4d4")
        log_box.pack(padx=20, pady=10, fill="both", expand=True)

        def add_log(txt):
            log_box.insert("end", f"{txt}\n")
            log_box.see("end")

        add_log("--- Iniciando Diagnóstico ---")
        try:
            printers = PrinterService.list_windows_printers()
            add_log(f"Impresoras detectadas: {len(printers)}")
            for p in printers:
                add_log(f" - {p}")
            
            import win32print
            try:
                def_p = win32print.GetDefaultPrinter()
                add_log(f"Predeterminada: {def_p}")
            except:
                add_log("Predeterminada: Error obteniendo")
            
        except Exception as e:
            add_log(f"ERROR: {e}")
            add_log(traceback.format_exc())

        add_log("--- Fin del Diagnóstico ---")
        ctk.CTkButton(win, text="Cerrar", command=win.destroy).pack(pady=10)

    def _probar_impresora(self):
        tipo = self.opt_impresora.get()
        if tipo == "windows":
            puerto = self.opt_win_printer.get()
        else:
            puerto = self.entry_puerto.get().strip()
        connected = printer_service.connect(tipo, puerto)
        if connected:
            ok = printer_service.test_printer()
            if ok:
                self.lbl_printer_status.configure(text="✅ Conectada y funcionando", text_color="#4CAF50")
            else:
                self.lbl_printer_status.configure(text="⚠ Conectada pero no imprime", text_color="#FF9800")
        else:
            self.lbl_printer_status.configure(text="❌ No se pudo conectar", text_color="#F44336")

    # ── Scanner helpers ───────────────────────────────────────────────────────

    def _refresh_ports(self):
        ports = scanner_service.list_ports()
        self._scan_ports = [p["device"] for p in ports]
        desc_list = [f"{p['device']} — {p['description'][:40]}" for p in ports] or ["(sin puertos COM)"]
        self._scan_port_labels = desc_list
        # Re-map label → device
        self._port_label_map = {}
        for p, label in zip(self._scan_ports, desc_list):
            self._port_label_map[label] = p
        self.opt_scanner_puerto.configure(values=desc_list if desc_list else ["(sin puertos COM)"])
        if desc_list:
            self.opt_scanner_puerto.set(desc_list[0])

    def _on_scanner_mode_change(self, mode: str):
        state = "normal" if mode == "serial" else "disabled"
        self.opt_scanner_puerto.configure(state=state)
        self.opt_scanner_baud.configure(state=state)

    def _guardar_scanner(self):
        modo   = self.opt_scanner_modo.get()
        label  = self.opt_scanner_puerto.get()
        puerto = self._port_label_map.get(label, label.split(" — ")[0]) if hasattr(self, "_port_label_map") else ""
        baud   = self.opt_scanner_baud.get()

        db = get_db_session()
        try:
            for key, valor in [
                ("scanner_modo",   modo),
                ("scanner_puerto", puerto if modo == "serial" else ""),
                ("scanner_baud",   baud),
            ]:
                c = db.query(Configuracion).filter(Configuracion.clave == key).first()
                if c:
                    c.valor = valor
                else:
                    db.add(Configuracion(clave=key, valor=valor))
            db.commit()
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
            return
        finally:
            db.close()

        # Tell MainWindow to restart scanner
        main = self._get_main_window()
        if main and hasattr(main, "restart_scanner"):
            ok = main.restart_scanner(modo, puerto if modo == "serial" else "", int(baud))
            if modo == "serial":
                if ok:
                    self.lbl_scanner_status.configure(
                        text=f"✅ Serial activo: {puerto} @ {baud}", text_color="#4CAF50")
                else:
                    self.lbl_scanner_status.configure(
                        text=f"❌ No se pudo abrir {puerto}", text_color="#F44336")
            else:
                self.lbl_scanner_status.configure(
                    text="✅ HID (teclado) activo", text_color="#4CAF50")
        else:
            messagebox.showinfo("Guardado", "Configuración guardada. Reinicia la app para aplicar.")

    def _probar_scanner(self):
        modo = self.opt_scanner_modo.get()
        if modo == "hid":
            messagebox.showinfo(
                "Modo HID",
                "El escáner está en modo teclado (HID).\n\n"
                "Asegúrate de que el escáner esté emparejado como dispositivo Bluetooth HID "
                "o conectado por USB.\n\n"
                "Para probar: haz clic en cualquier parte de la ventana principal y escanea "
                "un código — el sistema lo detectará automáticamente.",
            )
        else:
            label  = self.opt_scanner_puerto.get()
            puerto = self._port_label_map.get(label, label.split(" — ")[0]) if hasattr(self, "_port_label_map") else ""
            baud   = int(self.opt_scanner_baud.get())
            if not puerto:
                messagebox.showwarning("Puerto", "Selecciona un puerto COM primero")
                return
            self.lbl_scanner_status.configure(text=f"Probando {puerto}…", text_color="#FF9800")
            self.update()
            ok = scanner_service.start_serial(puerto, baud)
            if ok:
                self.lbl_scanner_status.configure(
                    text=f"✅ Puerto {puerto} abierto — escanea un código para probar",
                    text_color="#4CAF50")
            else:
                self.lbl_scanner_status.configure(
                    text=f"❌ No se pudo abrir {puerto}", text_color="#F44336")

    def _update_scanner_status(self):
        parts = []
        if scanner_service.is_hid_running:
            parts.append("✅ Hook HID activo (USB/BT)")
        if scanner_service.is_serial_running:
            parts.append(f"✅ Serial: {scanner_service.active_port}")
        if not parts:
            parts.append("⚠ Sin modo activo")
        self.lbl_scanner_status.configure(
            text="  |  ".join(parts),
            text_color="#4CAF50" if parts and "✅" in parts[0] else "#FF9800"
        )

    def _abrir_diagnostico(self):
        win = ctk.CTkToplevel(self)
        win.title("Diagnóstico de Escáner")
        win.geometry("520x460")
        win.grab_set()

        ctk.CTkLabel(win, text="🔎 Diagnóstico de Escáner",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 4))
        ctk.CTkLabel(
            win,
            text="Haz clic en el campo de abajo y escanea un código.\n"
                 "Verás exactamente qué teclas envía tu escáner.",
            font=ctk.CTkFont(size=12), text_color="gray60",
        ).pack(pady=(0, 8))

        entry = ctk.CTkEntry(win, placeholder_text="← Haz clic aquí, luego escanea",
                             height=44, font=ctk.CTkFont(size=14))
        entry.pack(fill="x", padx=20, pady=(0, 8))
        entry.focus()

        log_frame = ctk.CTkScrollableFrame(win, height=220)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))
        log_frame.grid_columnconfigure(0, weight=1)

        self._diag_row = 0
        self._diag_buf = []

        def add_line(text, color="#0F172A"):
            ctk.CTkLabel(log_frame, text=text, anchor="w",
                         font=ctk.CTkFont(size=11, family="Courier"),
                         text_color=color).grid(
                row=self._diag_row, column=0, sticky="w", padx=4, pady=1)
            self._diag_row += 1

        def on_key(event):
            char_repr = repr(event.char) if event.char else "(none)"
            color = "#16A34A" if event.keysym in ("Return", "KP_Enter", "Tab") else "#0F172A"
            add_line(
                f"keysym={event.keysym:<15} char={char_repr:<8} keycode={event.keycode}",
                color=color,
            )
            self._diag_buf.append(event.char if event.char and event.char.isprintable() else "")
            if event.keysym in ("Return", "KP_Enter", "Tab"):
                barcode = "".join(self._diag_buf[:-1]).strip()
                add_line(f"  → CÓDIGO COMPLETO: {barcode}", color="#2563EB")
                self._diag_buf.clear()

        entry.bind("<Key>", on_key)
        try:
            entry._entry.bind("<Key>", on_key)
        except Exception:
            pass

        add_line("Esperando escaneo...", color="gray")

        ctk.CTkButton(win, text="Limpiar", height=34,
                      command=lambda: [
                          w.destroy() for w in log_frame.winfo_children()
                      ] or add_line("Esperando escaneo...", color="gray") or
                      self._reset_diag()
                      ).pack(padx=20, pady=(0, 16), fill="x")

    def _reset_diag(self):
        self._diag_row = 0
        self._diag_buf = []

    def _get_main_window(self):
        w = self
        while w is not None:
            import customtkinter as _ctk
            if hasattr(w, "restart_scanner"):
                return w
            w = getattr(w, "master", None)
        return None

    def on_show(self):
        self._cargar_config()
        if hasattr(self, "_db_count_labels"):
            self._cargar_db_stats()
