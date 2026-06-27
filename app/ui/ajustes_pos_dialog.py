"""
Modal de Ajustes del Sistema con tarjetas de acceso rápido.
Accesible desde el POS screen.
Incluye: configurar impresora, editor de ticket, configurar báscula.
"""
import json
from tkinter import messagebox, filedialog
import tkinter as tk
import customtkinter as ctk

from app.database.connection import get_db_session
from app.database.models import Configuracion
from app.services.printer_service import PrinterService
import app.config as cfg


# ─── Utilidad DB ─────────────────────────────────────────────────────────────

def _get_config(keys: list[str]) -> dict:
    db = get_db_session()
    try:
        rows = {c.clave: c.valor for c in db.query(Configuracion).all()}
    finally:
        db.close()
    return {k: rows.get(k, "") for k in keys}


def _save_config(data: dict):
    db = get_db_session()
    try:
        for clave, valor in data.items():
            c = db.query(Configuracion).filter(Configuracion.clave == clave).first()
            if c:
                c.valor = valor
            else:
                db.add(Configuracion(clave=clave, valor=str(valor)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ─── Main modal ───────────────────────────────────────────────────────────────

class AjustesSistemaDialog(ctk.CTkToplevel):
    """Grid de tarjetas de acceso rápido a configuraciones del sistema."""

    CARDS = [
        ("🖨️", "Configurar\nImpresora",   "#2563EB", "#EFF6FF", "impresora"),
        ("🖊️", "Editor de\nTicket",       "#7C3AED", "#F5F3FF", "ticket"),
        ("⚖️", "Configurar\nBáscula",      "#16A34A", "#DCFCE7", "bascula"),
    ]

    def __init__(self, parent, user=None):
        super().__init__(parent)
        self.title("⚙️ Ajustes del Sistema")
        self.geometry("540x360")
        self.resizable(False, False)
        self.grab_set()
        self.user = user
        self.after(10, self._center)
        self._build_ui()

    def _center(self):
        self.update_idletasks()
        try:
            pw = self.master.winfo_rootx() + self.master.winfo_width() // 2
            ph = self.master.winfo_rooty() + self.master.winfo_height() // 2
            self.geometry(f"540x360+{pw - 270}+{ph - 180}")
        except Exception:
            pass

    def _build_ui(self):
        ctk.CTkLabel(
            self,
            text="⚙️  Ajustes del Sistema",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(pady=(22, 4))
        ctk.CTkLabel(
            self,
            text="Selecciona una opción para configurar",
            font=ctk.CTkFont(size=12), text_color="gray60",
        ).pack(pady=(0, 18))

        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=30)

        for i, (icon, label, fg_col, bg_col, key) in enumerate(self.CARDS):
            col = i % 3
            row = i // 3

            card = ctk.CTkButton(
                grid,
                text=f"{icon}\n\n{label}",
                width=148, height=130,
                fg_color=bg_col,
                hover_color="#E0E7FF" if "26" in fg_col else "#F0FDF4" if "A3" in fg_col else "#EDE9FE",
                text_color=fg_col,
                font=ctk.CTkFont(size=13, weight="bold"),
                corner_radius=14,
                border_width=2,
                border_color=fg_col,
                command=lambda k=key: self._open(k),
            )
            card.grid(row=row, column=col, padx=8, pady=6, sticky="nsew")

        ctk.CTkButton(
            self, text="Cerrar", height=34, width=120,
            fg_color="transparent", border_width=1, border_color="#CBD5E1",
            command=self.destroy,
        ).pack(pady=18)

    def _open(self, key: str):
        if key == "impresora":
            ImpresoraDialog(self)
        elif key == "ticket":
            TicketEditorDialog(self)
        elif key == "bascula":
            BásculaDialog(self)


# ─── Configurar impresora ─────────────────────────────────────────────────────

class ImpresoraDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("🖨️ Configurar Impresora")
        self.geometry("500x420")
        self.resizable(False, False)
        self.grab_set()
        self._build_ui()
        self._cargar()

    def _build_ui(self):
        ctk.CTkLabel(self, text="🖨️  Configurar Impresora",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(18, 4))

        frm = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        frm.pack(fill="x", padx=20, pady=8)
        frm.grid_columnconfigure(1, weight=1)

        # Tipo
        ctk.CTkLabel(frm, text="Tipo:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(14, 8), pady=8, sticky="e")
        self.opt_tipo = ctk.CTkOptionMenu(
            frm, values=["windows", "usb", "serial", "network"],
            command=self._on_tipo)
        self.opt_tipo.grid(row=0, column=1, padx=(0, 14), pady=8, sticky="ew")

        # Papel
        ctk.CTkLabel(frm, text="Papel:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=1, column=0, padx=(14, 8), pady=8, sticky="e")
        self.opt_papel = ctk.CTkOptionMenu(
            frm, values=["50mm  (26 col)", "58mm  (32 col)", "80mm  (48 col)"])
        self.opt_papel.grid(row=1, column=1, padx=(0, 14), pady=8, sticky="ew")

        # Impresora Windows
        self._row_win = ctk.CTkFrame(frm, fg_color="transparent")
        self._row_win.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 4))
        self._row_win.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._row_win, text="Impresora:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 8), sticky="e")
        self.opt_win = ctk.CTkOptionMenu(self._row_win, values=["(cargando...)"])
        self.opt_win.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(self._row_win, text="↺", width=34, height=32,
                      command=self._refresh_printers).grid(row=0, column=2, padx=(6, 0))

        # Puerto manual
        self._row_port = ctk.CTkFrame(frm, fg_color="transparent")
        self._row_port.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 4))
        self._row_port.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self._row_port, text="Puerto/IP:", anchor="e",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, padx=(0, 8), sticky="e")
        self.entry_port = ctk.CTkEntry(self._row_port, height=32,
                                        placeholder_text="COM1 ó 192.168.1.x:9100")
        self.entry_port.grid(row=0, column=1, sticky="ew")

        # Botones
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=10)
        ctk.CTkButton(btn_row, text="💾 Guardar", height=36, fg_color="#4CAF50",
                      hover_color="#388E3C", command=self._guardar).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="🔌 Probar", height=36,
                      fg_color="#2196F3", hover_color="#1976D2",
                      command=self._probar).pack(side="left", padx=6)

        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12))
        self.lbl_status.pack()

    def _cargar(self):
        cfg_data = _get_config(["impresora_tipo", "impresora_puerto",
                                  "impresora_nombre", "impresora_ancho"])
        tipo = cfg_data.get("impresora_tipo", "windows")
        self.opt_tipo.set(tipo)
        ancho = cfg_data.get("impresora_ancho", "32")
        self.opt_papel.set(
            "80mm  (48 col)" if ancho == "48" else
            "50mm  (26 col)" if ancho == "26" else "58mm  (32 col)")
        self._refresh_printers()
        saved = cfg_data.get("impresora_nombre", "")
        printers = PrinterService.list_windows_printers()
        if saved in printers:
            self.opt_win.set(saved)
        port = cfg_data.get("impresora_puerto", "")
        if port:
            self.entry_port.insert(0, port)
        self._on_tipo(tipo)

    def _refresh_printers(self):
        printers = PrinterService.list_windows_printers()
        self.opt_win.configure(values=printers or ["(sin impresoras)"])
        if printers:
            self.opt_win.set(printers[0])

    def _on_tipo(self, tipo: str):
        if tipo == "windows":
            self._row_win.grid()
            self._row_port.grid_remove()
        else:
            self._row_win.grid_remove()
            self._row_port.grid()

    def _guardar(self):
        tipo = self.opt_tipo.get()
        sel_papel = self.opt_papel.get()
        ancho = "48" if "80mm" in sel_papel else "26" if "50mm" in sel_papel else "32"
        if tipo == "windows":
            nombre = self.opt_win.get()
            puerto = nombre
        else:
            nombre = ""
            puerto = self.entry_port.get().strip()
        try:
            _save_config({
                "impresora_tipo": tipo, "impresora_puerto": puerto,
                "impresora_nombre": nombre, "impresora_ancho": ancho,
            })
            self.lbl_status.configure(text="✅ Guardado", text_color="#4CAF50")
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

    def _probar(self):
        from app.services.printer_service import printer_service
        tipo = self.opt_tipo.get()
        puerto = self.opt_win.get() if tipo == "windows" else self.entry_port.get().strip()
        connected = printer_service.connect(tipo, puerto)
        if connected and printer_service.test_printer():
            self.lbl_status.configure(text="✅ Impresora OK", text_color="#4CAF50")
        else:
            self.lbl_status.configure(text="❌ No se pudo conectar", text_color="#DC2626")


# ─── Configurar Báscula ───────────────────────────────────────────────────────

class BásculaDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("⚖️ Configurar Báscula")
        self.geometry("460x360")
        self.resizable(False, False)
        self.grab_set()
        self._build_ui()
        self._cargar()

    def _build_ui(self):
        ctk.CTkLabel(self, text="⚖️  Configurar Báscula / Balanza",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(18, 4))
        ctk.CTkLabel(
            self,
            text="La báscula envía el peso vía puerto COM (RS-232 o USB-CDC).",
            font=ctk.CTkFont(size=11), text_color="gray60", wraplength=400,
        ).pack(pady=(0, 10))

        frm = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        frm.pack(fill="x", padx=20, pady=4)
        frm.grid_columnconfigure(1, weight=1)

        fields = [
            ("Puerto COM:", "bascula_puerto",     "COM1"),
            ("Baudrate:",   "bascula_baud",       "9600"),
            ("Protocolo:",  "bascula_protocolo",  "toledo"),
        ]
        self._entries: dict[str, ctk.CTkEntry] = {}
        for i, (lbl, key, ph) in enumerate(fields):
            ctk.CTkLabel(frm, text=lbl, anchor="e",
                         font=ctk.CTkFont(size=12)).grid(
                row=i, column=0, padx=(14, 8), pady=8, sticky="e")
            e = ctk.CTkEntry(frm, height=32, placeholder_text=ph)
            e.grid(row=i, column=1, padx=(0, 14), pady=8, sticky="ew")
            self._entries[key] = e

        ctk.CTkLabel(
            self,
            text="Protocolo: 'toledo' (Toledo/Mettler), 'cas' (CAS), 'generic'",
            font=ctk.CTkFont(size=10), text_color="gray60",
        ).pack(pady=(2, 0))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=14)
        ctk.CTkButton(btn_row, text="💾 Guardar", height=36, fg_color="#4CAF50",
                      hover_color="#388E3C", command=self._guardar).pack(side="left", padx=6)
        ctk.CTkButton(btn_row, text="Cancelar", height=36, width=100,
                      fg_color="transparent", border_width=1, border_color="#ccc",
                      command=self.destroy).pack(side="left")

        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12))
        self.lbl_status.pack()

    def _cargar(self):
        keys = list(self._entries.keys())
        data = _get_config(keys)
        for key, e in self._entries.items():
            val = data.get(key, "")
            if val:
                e.insert(0, val)

    def _guardar(self):
        data = {k: e.get().strip() for k, e in self._entries.items()}
        try:
            _save_config(data)
            self.lbl_status.configure(text="✅ Guardado", text_color="#4CAF50")
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)


# ─── Editor de ticket ─────────────────────────────────────────────────────────

_TICKET_KEYS = [
    "ticket_fuente_titulo",
    "ticket_fuente_contenido",
    "ticket_logo_activo",
    "ticket_logo_tipo",
    "ticket_logo_custom",
    "ticket_custom_activo",
    "ticket_custom_texto",
    "ticket_dato_nombre",
    "ticket_dato_fiscal",
    "ticket_dato_direccion",
    "ticket_dato_email",
    "ticket_dato_telefono",
    "farmacia_nombre",
    "farmacia_direccion",
    "farmacia_telefono",
    "farmacia_rfc",
]

_FUENTES = ["HELVETICA", "HELVETICA_BOLD", "COURIER", "COURIER_BOLD", "TIMES"]


class TicketEditorDialog(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("🖊️ Editor de Ticket de Venta")
        self.geometry("980x680")
        self.minsize(820, 560)
        self.grab_set()
        self._cfg: dict = {}
        self._logo_path: str = ""
        self._build_ui()
        self._cargar()
        self._refresh_preview()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=5)
        self.grid_columnconfigure(1, weight=4)
        self.grid_rowconfigure(0, weight=1)

        # ── Left: preview ─────────────────────────────────────────────────────
        left = ctk.CTkFrame(self, corner_radius=0, fg_color="#E5E7EB")
        left.grid(row=0, column=0, sticky="nsew")
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Vista previa del ticket",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#4B5563").grid(row=0, column=0, pady=(10, 4))

        # Ticket preview canvas (simulated receipt)
        preview_container = ctk.CTkScrollableFrame(
            left, corner_radius=0, fg_color="#E5E7EB")
        preview_container.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 10))
        preview_container.grid_columnconfigure(0, weight=1)

        self._ticket_frame = ctk.CTkFrame(
            preview_container, corner_radius=4,
            fg_color="white",
            border_width=1, border_color="#D1D5DB")
        self._ticket_frame.grid(row=0, column=0, sticky="ew", pady=8)
        self._ticket_frame.grid_columnconfigure(0, weight=1)

        self._ticket_widgets: list = []

        # ── Right: settings ───────────────────────────────────────────────────
        right = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="white",
                                        border_width=1, border_color="#E2E8F0")
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        # Header
        ctk.CTkLabel(right, text="⚙️  Configuración del ticket",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, padx=14, pady=(14, 4), sticky="w")

        # Top buttons
        top_btns = ctk.CTkFrame(right, fg_color="transparent")
        top_btns.grid(row=1, column=0, padx=14, pady=(0, 10), sticky="w")
        ctk.CTkButton(top_btns, text="🖨 Testear resultado", height=32,
                      fg_color="#2196F3", hover_color="#1976D2",
                      command=self._test_print).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top_btns, text="💾 Guardar formato", height=32,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._guardar).pack(side="left")

        row = 2

        # ── Fuentes ───────────────────────────────────────────────────────────
        self._sep(right, "Fuente y tamaño", row)
        row += 1
        font_frm = self._card(right, row)
        row += 1
        font_frm.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(font_frm, text="Fuente títulos:",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(12, 6), pady=6, sticky="e")
        self.opt_f_titulo = ctk.CTkOptionMenu(font_frm, values=_FUENTES,
                                               command=lambda v: self._refresh_preview())
        self.opt_f_titulo.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="ew")

        ctk.CTkLabel(font_frm, text="Fuente contenido:",
                     font=ctk.CTkFont(size=11)).grid(row=1, column=0, padx=(12, 6), pady=6, sticky="e")
        self.opt_f_cont = ctk.CTkOptionMenu(font_frm, values=_FUENTES,
                                             command=lambda v: self._refresh_preview())
        self.opt_f_cont.grid(row=1, column=1, padx=(0, 12), pady=6, sticky="ew")

        # ── Logo ──────────────────────────────────────────────────────────────
        self._sep(right, "Imprimir logo", row)
        row += 1
        logo_frm = self._card(right, row)
        row += 1

        logo_top = ctk.CTkFrame(logo_frm, fg_color="transparent")
        logo_top.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(logo_top, text="Imprimir logo:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 8))
        self.chk_logo = ctk.CTkCheckBox(logo_top, text="",
                                         command=self._refresh_preview)
        self.chk_logo.pack(side="left")

        logo_tipo = ctk.CTkFrame(logo_frm, fg_color="transparent")
        logo_tipo.pack(fill="x", padx=12, pady=2)
        self._logo_tipo_var = tk.StringVar(value="empresa")
        ctk.CTkRadioButton(logo_tipo, text="Logo de empresa",
                            variable=self._logo_tipo_var, value="empresa",
                            command=self._refresh_preview,
                            font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 12))
        ctk.CTkRadioButton(logo_tipo, text="Usar otra imagen",
                            variable=self._logo_tipo_var, value="custom",
                            command=self._refresh_preview,
                            font=ctk.CTkFont(size=11)).pack(side="left")

        logo_custom_row = ctk.CTkFrame(logo_frm, fg_color="transparent")
        logo_custom_row.pack(fill="x", padx=12, pady=(4, 8))
        logo_custom_row.grid_columnconfigure(0, weight=1)
        self.entry_logo_path = ctk.CTkEntry(logo_custom_row, height=30,
                                             placeholder_text="Ruta de la imagen...")
        self.entry_logo_path.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkButton(logo_custom_row, text="📂", width=34, height=30,
                      command=self._seleccionar_logo).grid(row=0, column=1)

        # ── Apartado personalizado ────────────────────────────────────────────
        self._sep(right, "Apartado personalizado", row)
        row += 1
        custom_frm = self._card(right, row)
        row += 1

        custom_top = ctk.CTkFrame(custom_frm, fg_color="transparent")
        custom_top.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(custom_top, text="Incluir apartado personalizado:",
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 8))
        self.chk_custom = ctk.CTkCheckBox(custom_top, text="",
                                           command=self._refresh_preview)
        self.chk_custom.pack(side="left")

        self.txt_custom = ctk.CTkTextbox(custom_frm, height=70,
                                          font=ctk.CTkFont(size=11, family="Courier"))
        self.txt_custom.pack(fill="x", padx=12, pady=(0, 8))
        self.txt_custom.bind("<KeyRelease>", lambda e: self._refresh_preview())

        # ── Datos de negocio ──────────────────────────────────────────────────
        self._sep(right, "Incluir datos de negocio", row)
        row += 1
        datos_frm = self._card(right, row)
        row += 1

        self._chk_vars = {}
        dato_labels = [
            ("ticket_dato_nombre",    "Nombre de empresa"),
            ("ticket_dato_fiscal",    "Identificación fiscal"),
            ("ticket_dato_direccion", "Dirección"),
            ("ticket_dato_email",     "Email"),
            ("ticket_dato_telefono",  "Teléfono"),
        ]
        for dk, dl in dato_labels:
            v = tk.BooleanVar(value=True)
            self._chk_vars[dk] = v
            ctk.CTkCheckBox(datos_frm, text=dl, variable=v,
                             command=self._refresh_preview,
                             font=ctk.CTkFont(size=11)).pack(
                anchor="w", padx=12, pady=3)
        datos_frm.pack_configure(pady=(0, 14))

    def _sep(self, parent, text, row):
        ctk.CTkLabel(parent, text=text,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#374151").grid(
            row=row, column=0, padx=14, pady=(10, 2), sticky="w")

    def _card(self, parent, row) -> ctk.CTkFrame:
        frm = ctk.CTkFrame(parent, corner_radius=8,
                            fg_color=("#F8FAFF", "#1e1e1e"),
                            border_width=1, border_color="#E2E8F0")
        frm.grid(row=row, column=0, padx=12, pady=(0, 6), sticky="ew")
        return frm

    # ── Data ─────────────────────────────────────────────────────────────────

    def _cargar(self):
        self._cfg = _get_config(_TICKET_KEYS)

        self.opt_f_titulo.set(self._cfg.get("ticket_fuente_titulo", "HELVETICA_BOLD") or "HELVETICA_BOLD")
        self.opt_f_cont.set(self._cfg.get("ticket_fuente_contenido", "HELVETICA") or "HELVETICA")

        if self._cfg.get("ticket_logo_activo", "true") != "false":
            self.chk_logo.select()
        else:
            self.chk_logo.deselect()

        self._logo_tipo_var.set(self._cfg.get("ticket_logo_tipo", "empresa") or "empresa")

        lp = self._cfg.get("ticket_logo_custom", "")
        if lp:
            self.entry_logo_path.insert(0, lp)
        self._logo_path = lp

        if self._cfg.get("ticket_custom_activo", "false") == "true":
            self.chk_custom.select()
        else:
            self.chk_custom.deselect()

        texto = self._cfg.get("ticket_custom_texto", "")
        if texto:
            self.txt_custom.insert("1.0", texto)

        for dk, var in self._chk_vars.items():
            var.set(self._cfg.get(dk, "true") != "false")

    def _seleccionar_logo(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar logo",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp"), ("Todos", "*.*")])
        if path:
            self.entry_logo_path.delete(0, "end")
            self.entry_logo_path.insert(0, path)
            self._logo_path = path
            self._logo_tipo_var.set("custom")
            self._refresh_preview()

    # ── Preview ───────────────────────────────────────────────────────────────

    def _refresh_preview(self):
        for w in self._ticket_frame.winfo_children():
            w.destroy()

        cfg_data = self._cfg.copy()
        farmacia_nombre    = cfg_data.get("farmacia_nombre", "Mi Farmacia") or "Mi Farmacia"
        farmacia_direccion = cfg_data.get("farmacia_direccion", "Calle Principal #1") or ""
        farmacia_telefono  = cfg_data.get("farmacia_telefono", "") or ""
        farmacia_rfc       = cfg_data.get("farmacia_rfc", "") or ""

        show_logo    = self.chk_logo.get()
        logo_tipo    = self._logo_tipo_var.get()
        show_custom  = self.chk_custom.get()
        custom_text  = self.txt_custom.get("1.0", "end").strip()
        f_titulo     = self.opt_f_titulo.get()
        bold_titulo  = "bold" in f_titulo.lower()

        ticket_w = 260

        def row(text, size=9, bold=False, center=False, sep=False, gap=False):
            if gap:
                ctk.CTkFrame(self._ticket_frame, height=4, fg_color="transparent").pack()
                return
            if sep:
                ctk.CTkFrame(self._ticket_frame, height=1, fg_color="#D1D5DB").pack(
                    fill="x", padx=8, pady=2)
                return
            ctk.CTkLabel(
                self._ticket_frame,
                text=text,
                font=ctk.CTkFont(size=size, weight="bold" if bold else "normal",
                                  family="Courier"),
                text_color="#111827",
                justify="center" if center else "left",
                anchor="center" if center else "w",
                wraplength=ticket_w - 20,
            ).pack(fill="x", padx=10, pady=0)

        row("", gap=True)

        # Logo placeholder
        if show_logo:
            if logo_tipo == "custom" and self.entry_logo_path.get().strip():
                try:
                    from PIL import Image
                    img = Image.open(self.entry_logo_path.get().strip())
                    img.thumbnail((140, 60), Image.LANCZOS)
                    ctk_img = ctk.CTkImage(light_image=img, size=(img.width, img.height))
                    ctk.CTkLabel(self._ticket_frame, image=ctk_img, text="").pack(pady=4)
                except Exception:
                    row("[LOGO PERSONALIZADO]", size=9, center=True)
            else:
                logo_lbl = ctk.CTkFrame(
                    self._ticket_frame, height=48, corner_radius=4,
                    fg_color="#EFF6FF", border_width=1, border_color="#BFDBFE")
                logo_lbl.pack(fill="x", padx=20, pady=4)
                ctk.CTkLabel(logo_lbl,
                             text="[ Logo de empresa ]",
                             font=ctk.CTkFont(size=10), text_color="#3B82F6").pack(expand=True)

        # Business data
        if self._chk_vars["ticket_dato_nombre"].get():
            row(farmacia_nombre, size=11, bold=bold_titulo, center=True)
        if self._chk_vars["ticket_dato_direccion"].get() and farmacia_direccion:
            row(farmacia_direccion, size=8, center=True)
        if self._chk_vars["ticket_dato_fiscal"].get() and farmacia_rfc:
            row(f"RFC: {farmacia_rfc}", size=8, center=True)
        if self._chk_vars["ticket_dato_email"].get():
            row("info@farmacia.com", size=8, center=True)
        if self._chk_vars["ticket_dato_telefono"].get() and farmacia_telefono:
            row(f"Tel: {farmacia_telefono}", size=8, center=True)

        row("", sep=True)
        row("Ticket: T000-0001", size=9, center=True)
        row("Fecha: 26/06/2026  12:00:00", size=8, center=True)
        row("Cajero: Admin", size=8, center=True)

        row("", sep=True)

        # Table header
        hdr = ctk.CTkFrame(self._ticket_frame, fg_color="transparent")
        hdr.pack(fill="x", padx=10, pady=1)
        hdr.grid_columnconfigure(0, weight=1)
        for col, txt, wd in [("Cant", 35), ("Prod.", 130), ("Total", 55)]:
            ctk.CTkLabel(hdr, text=col,
                         font=ctk.CTkFont(size=8, weight="bold", family="Courier"),
                         text_color="#374151", width=wd, anchor="w").pack(side="left")

        # Sample items
        for qty, prod, total in [("1", "Paracetamol 500mg", "$15.00"),
                                   ("2", "Amoxicilina 250ml", "$45.00")]:
            item = ctk.CTkFrame(self._ticket_frame, fg_color="transparent")
            item.pack(fill="x", padx=10, pady=0)
            ctk.CTkLabel(item, text=qty,
                         font=ctk.CTkFont(size=8, family="Courier"),
                         width=35, anchor="w").pack(side="left")
            ctk.CTkLabel(item, text=prod,
                         font=ctk.CTkFont(size=8, family="Courier"),
                         width=130, anchor="w", wraplength=120).pack(side="left")
            ctk.CTkLabel(item, text=total,
                         font=ctk.CTkFont(size=8, family="Courier"),
                         width=55, anchor="e").pack(side="left")

        row("", sep=True)
        row("Subtotal:      $60.00", size=9)
        row("IVA (0%):       $0.00", size=9)
        row("TOTAL:         $60.00", size=10, bold=True)
        row("Pago:  EFECTIVO", size=9)
        row("Recibido:      $70.00", size=9)
        row("Cambio:        $10.00", size=9)
        row("", sep=True)

        # Custom section
        if show_custom and custom_text:
            row(custom_text, size=8, center=True)
            row("", sep=True)

        row("¡Gracias por su compra!", size=9, center=True, bold=bold_titulo)
        row("", gap=True)

    # ── Save & Test ───────────────────────────────────────────────────────────

    def _guardar(self):
        data = {
            "ticket_fuente_titulo":     self.opt_f_titulo.get(),
            "ticket_fuente_contenido":  self.opt_f_cont.get(),
            "ticket_logo_activo":       "true" if self.chk_logo.get() else "false",
            "ticket_logo_tipo":         self._logo_tipo_var.get(),
            "ticket_logo_custom":       self.entry_logo_path.get().strip(),
            "ticket_custom_activo":     "true" if self.chk_custom.get() else "false",
            "ticket_custom_texto":      self.txt_custom.get("1.0", "end").strip(),
        }
        for dk, var in self._chk_vars.items():
            data[dk] = "true" if var.get() else "false"
        try:
            _save_config(data)
            messagebox.showinfo("Guardado", "Formato de ticket guardado correctamente", parent=self)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _test_print(self):
        from app.services.printer_service import printer_service
        if not printer_service.is_connected:
            messagebox.showwarning("Impresora",
                "Impresora no conectada. Conéctala en Configurar Impresora primero.", parent=self)
            return
        try:
            printer_service.test_printer()
            messagebox.showinfo("OK", "Ticket de prueba enviado a la impresora", parent=self)
        except Exception as exc:
            messagebox.showerror("Error al imprimir", str(exc), parent=self)
