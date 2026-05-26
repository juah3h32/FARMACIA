import sys
import threading
import tkinter as tk
import customtkinter as ctk
from datetime import datetime
from app.auth.auth_service import logout
from app.database.models import RolUsuario
import app.config as cfg
from app.ui import toast
from app.services.scanner_service import scanner_service
from app.services import updater_service

# ── Palette ───────────────────────────────────────────────────────────────────
SB_BG       = "#FFFFFF"
SB_BRAND    = "#F8FAFF"
SB_ACTIVE   = "#2563EB"
SB_ACTIVE_T = "#FFFFFF"
SB_HOVER    = "#F1F5F9"
SB_TEXT     = "#64748B"
SB_MUTED    = "#94A3B8"
HDR_BG      = "#FFFFFF"
CONT_BG     = "#F0F4F8"
CARD_BG     = "#FFFFFF"
BORDER      = "#E2E8F0"
BLUE        = "#2563EB"
GREEN       = "#16A34A"
GREEN_L     = "#DCFCE7"
TEXT        = "#0F172A"
MUTED       = "#64748B"

NAV_ITEMS = [
    ("🛒",  "Ventas",        "pos",       None),
    ("📦",  "Inventario",    "inventory", None),
    ("🧾",  "Compras",       "compras",   None),
    ("👥",  "Clientes",      "customers", None),
    ("🚚",  "Proveedores",   "suppliers", None),
    ("👤",  "Empleados",     "employees", [RolUsuario.admin]),
    ("📊",  "Reportes",      "reports",   None),
    ("⚙️",  "Configuración", "settings",  [RolUsuario.admin]),
]

SCREEN_TITLES = {
    "pos":       "Punto de Venta",
    "inventory": "Inventario",
    "compras":   "Registrar Compra",
    "customers": "Clientes",
    "suppliers": "Proveedores",
    "employees": "Empleados",
    "reports":   "Reportes",
    "settings":  "Configuración",
}

# Stat card definitions: (icon, label, attr_name, circle_color, circle_bg)
STAT_DEFS = [
    ("🛒", "Ventas hoy",   "_sv_sales",   "#3B82F6", "#EFF6FF"),
    ("💰", "Ingresos hoy", "_sv_revenue", "#22C55E", "#F0FDF4"),
    ("⚠",  "Stock bajo",   "_sv_low",     "#F59E0B", "#FFFBEB"),
    ("📦", "Productos",    "_sv_total",   "#8B5CF6", "#F5F3FF"),
]


class MainWindow(ctk.CTkToplevel):
    def __init__(self, user, on_logout=None):
        super().__init__()
        self.user      = user
        self.on_logout = on_logout
        self.screens   = {}
        self.current_screen = None
        self._nav_btns = {}

        self._scan_buf   = ""
        self._scan_timer = None

        self.configure(fg_color=CONT_BG)
        self.title("Farmacia Eben-Ezer — POS")
        self.geometry(f"{cfg.WINDOW_WIDTH}x{cfg.WINDOW_HEIGHT}")
        self.minsize(1000, 680)
        self._center_window()
        self._build_layout()
        self._show_screen("pos")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        toast.init(self)
        self._load_stats()
        self._bind_shortcuts()
        self._init_scanner_service()
        updater_service.check_for_update_async(self._on_update_check)

    def _center_window(self):
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(
            f"{cfg.WINDOW_WIDTH}x{cfg.WINDOW_HEIGHT}"
            f"+{(sw - cfg.WINDOW_WIDTH) // 2}+{(sh - cfg.WINDOW_HEIGHT) // 2}"
        )

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        self.grid_columnconfigure(0, weight=0, minsize=cfg.SIDEBAR_WIDTH)
        self.grid_columnconfigure(1, weight=0, minsize=1)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()

        # 1-px sidebar border
        ctk.CTkFrame(self, width=1, corner_radius=0,
                     fg_color=BORDER).grid(row=0, column=1, sticky="nsew")

        self._build_right()

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, corner_radius=0, fg_color=SB_BG)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.pack_propagate(False)

        # Brand
        bw = ctk.CTkFrame(sb, fg_color=SB_BRAND, corner_radius=0)
        bw.pack(fill="x")

        bi = ctk.CTkFrame(bw, fg_color="transparent")
        bi.pack(pady=(20, 16))

        ring = ctk.CTkFrame(bi, width=56, height=56,
                            corner_radius=28, fg_color=GREEN_L)
        ring.pack()
        ring.pack_propagate(False)
        ctk.CTkLabel(ring, text="✚",
                     font=ctk.CTkFont(size=28, weight="bold"),
                     text_color=GREEN,
                     ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(bi, text="FARMACIA",
                     font=ctk.CTkFont(size=8, weight="bold"),
                     text_color=GREEN).pack(pady=(8, 0))
        ctk.CTkLabel(bi, text="EBEN-EZER",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(pady=(1, 0))
        ctk.CTkLabel(bi, text="Sistema POS",
                     font=ctk.CTkFont(size=10),
                     text_color=SB_MUTED).pack(pady=(2, 0))

        ctk.CTkFrame(sb, height=1, fg_color=BORDER).pack(fill="x")

        # Nav
        ctk.CTkLabel(sb, text="  MENÚ",
                     font=ctk.CTkFont(size=8, weight="bold"),
                     text_color=SB_MUTED, anchor="w",
                     ).pack(fill="x", padx=14, pady=(10, 4))

        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.pack(fill="both", expand=True, padx=8, pady=2)

        for icon, label, key, roles in NAV_ITEMS:
            if roles and self.user.rol not in roles:
                continue
            btn = ctk.CTkButton(
                nav,
                text=f"  {icon}   {label}",
                anchor="w",
                height=42, corner_radius=8,
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                text_color=SB_TEXT, hover_color=SB_HOVER,
                command=lambda k=key: self._show_screen(k),
            )
            btn.pack(fill="x", pady=2)
            self._nav_btns[key] = btn

        # User card
        ctk.CTkFrame(sb, height=1, fg_color=BORDER).pack(fill="x", padx=8, pady=6)

        uc = ctk.CTkFrame(sb, fg_color="#F8FAFF", corner_radius=10,
                          border_width=1, border_color=BORDER)
        uc.pack(fill="x", padx=8, pady=(0, 10))

        row = ctk.CTkFrame(uc, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(10, 6))

        av = ctk.CTkFrame(row, width=36, height=36,
                          corner_radius=18, fg_color=BLUE)
        av.pack(side="left")
        av.pack_propagate(False)
        ctk.CTkLabel(
            av,
            text=(self.user.nombre[0].upper() if self.user.nombre else "U"),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        nc = ctk.CTkFrame(row, fg_color="transparent")
        nc.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(nc, text=self.user.nombre,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(nc, text=self.user.rol.value.capitalize(),
                     font=ctk.CTkFont(size=10),
                     text_color=SB_MUTED, anchor="w").pack(anchor="w")

        ctk.CTkButton(
            uc, text="Cerrar Sesión",
            height=30, corner_radius=7,
            fg_color="transparent", border_width=1, border_color=BORDER,
            text_color=SB_MUTED, hover_color="#FEE2E2",
            font=ctk.CTkFont(size=11),
            command=self._logout,
        ).pack(fill="x", padx=10, pady=(4, 10))

    # ── Right panel ───────────────────────────────────────────────────────────

    def _build_right(self):
        right = ctk.CTkFrame(self, corner_radius=0, fg_color=CONT_BG)
        right.grid(row=0, column=2, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(right, height=58, corner_radius=0, fg_color=HDR_BG)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_rowconfigure(0, weight=1)

        self.lbl_section = ctk.CTkLabel(
            hdr, text="Punto de Venta",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT, anchor="w",
        )
        self.lbl_section.grid(row=0, column=0, padx=(22, 0), sticky="w")

        rh = ctk.CTkFrame(hdr, fg_color="transparent")
        rh.grid(row=0, column=2, padx=(0, 18), sticky="e")

        self._update_btn = ctk.CTkButton(
            rh, text="⟳ Actualizar",
            width=110, height=28, corner_radius=6,
            fg_color="transparent", hover_color=SB_HOVER,
            border_width=1, border_color=BORDER,
            text_color=MUTED, font=ctk.CTkFont(size=11),
            command=self._show_update_dialog,
        )
        self._update_btn.pack(side="left", padx=(0, 12))

        self.lbl_clock = ctk.CTkLabel(rh, text="",
                                      font=ctk.CTkFont(size=11),
                                      text_color=MUTED)
        self.lbl_clock.pack(side="left", padx=(0, 14))

        badge = ctk.CTkFrame(rh, width=30, height=30,
                             corner_radius=15, fg_color=GREEN_L)
        badge.pack(side="left")
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="FE",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color=GREEN,
                     ).place(relx=0.5, rely=0.5, anchor="center")

        # Header separator
        ctk.CTkFrame(right, height=1, corner_radius=0,
                     fg_color=BORDER).grid(row=1, column=0, sticky="ew")

        self._tick_clock()

        # ── Stats bar ─────────────────────────────────────────────────────────
        stats = ctk.CTkFrame(right, corner_radius=0, fg_color=CONT_BG)
        stats.grid(row=2, column=0, sticky="ew")
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1)
        stats.grid_rowconfigure(0, weight=1)

        for col, (icon, label, attr, ccolor, cbg) in enumerate(STAT_DEFS):
            px_l = 14 if col == 0 else 5
            px_r = 5  if col < 3  else 14

            card = ctk.CTkFrame(stats, corner_radius=12,
                                fg_color=CARD_BG,
                                border_width=1, border_color=BORDER)
            card.grid(row=0, column=col,
                      padx=(px_l, px_r), pady=10, sticky="nsew")
            card.grid_columnconfigure(0, weight=1)

            # Accent bar izquierda
            accent = ctk.CTkFrame(card, width=4, corner_radius=2, fg_color=ccolor)
            accent.place(relx=0, rely=0.15, relheight=0.7, x=6)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=(18, 12), pady=12)

            # Icono arriba derecha
            ic = ctk.CTkFrame(inner, width=38, height=38,
                              corner_radius=10, fg_color=cbg)
            ic.pack(side="right", anchor="n")
            ic.pack_propagate(False)
            ctk.CTkLabel(ic, text=icon,
                         font=ctk.CTkFont(size=16),
                         ).place(relx=0.5, rely=0.5, anchor="center")

            # Textos izquierda
            tf = ctk.CTkFrame(inner, fg_color="transparent")
            tf.pack(side="left", fill="both", expand=True)

            val = ctk.CTkLabel(tf, text="—",
                               font=ctk.CTkFont(size=22, weight="bold"),
                               text_color=ccolor, anchor="w")
            val.pack(anchor="w")
            ctk.CTkLabel(tf, text=label,
                         font=ctk.CTkFont(size=10),
                         text_color=MUTED, anchor="w").pack(anchor="w")

            setattr(self, attr, val)

        # ── Content area ──────────────────────────────────────────────────────
        self.content = ctk.CTkFrame(right, corner_radius=0, fg_color=CONT_BG)
        self.content.grid(row=3, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

    # ── Stats loader (runs in background thread) ──────────────────────────────

    def _load_stats(self):
        def fetch():
            try:
                from app.database.connection import get_db
                from app.database.models import Venta, Producto, EstadoVenta
                from sqlalchemy import func
                now = datetime.now()
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end   = now.replace(hour=23, minute=59, second=59)

                with get_db() as db:
                    sales = db.query(func.count(Venta.id)).filter(
                        Venta.creado_en >= day_start,
                        Venta.creado_en <= day_end,
                        Venta.estado == EstadoVenta.completada,
                    ).scalar() or 0

                    revenue = db.query(func.sum(Venta.total)).filter(
                        Venta.creado_en >= day_start,
                        Venta.creado_en <= day_end,
                        Venta.estado == EstadoVenta.completada,
                    ).scalar() or 0.0

                    low = db.query(func.count(Producto.id)).filter(
                        Producto.stock <= Producto.stock_minimo,
                        Producto.activo.is_(True),
                    ).scalar() or 0

                    total_p = db.query(func.count(Producto.id)).filter(
                        Producto.activo.is_(True),
                    ).scalar() or 0

                return sales, revenue, low, total_p
            except Exception:
                return 0, 0.0, 0, 0

        def apply(data):
            sales, revenue, low, total_p = data
            self._sv_sales.configure(text=str(sales))
            self._sv_revenue.configure(text=f"${revenue:,.0f}")
            self._sv_low.configure(
                text=str(low),
                text_color="#F59E0B" if low > 0 else TEXT,
            )
            self._sv_total.configure(text=str(total_p))

        def run():
            data = fetch()
            try:
                self.after(0, lambda: apply(data))
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    # ── Clock ─────────────────────────────────────────────────────────────────

    def _tick_clock(self):
        n = datetime.now()
        d = ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"]
        m = ["ene","feb","mar","abr","may","jun",
             "jul","ago","sep","oct","nov","dic"]
        self.lbl_clock.configure(
            text=f"{d[n.weekday()]} {n.day} {m[n.month-1]} {n.year}"
                 f"   {n.strftime('%H:%M:%S')}"
        )
        self.after(1000, self._tick_clock)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _show_screen(self, key: str):
        for k, btn in self._nav_btns.items():
            if k == key:
                btn.configure(fg_color=SB_ACTIVE, text_color=SB_ACTIVE_T)
            else:
                btn.configure(fg_color="transparent", text_color=SB_TEXT)

        self.lbl_section.configure(text=SCREEN_TITLES.get(key, key.capitalize()))

        if key not in self.screens:
            self.screens[key] = self._create_screen(key)

        if self.current_screen:
            self.current_screen.grid_remove()
        self.current_screen = self.screens[key]
        self.current_screen.grid(row=0, column=0, sticky="nsew")

        if hasattr(self.current_screen, "on_show"):
            self.current_screen.on_show()

        # Refresh stats on every screen switch
        self._load_stats()

    def _create_screen(self, key: str):
        p = self.content
        if key == "pos":
            from app.ui.pos_screen import PosScreen
            return PosScreen(p, self.user, on_unknown_barcode=self._handle_global_scan)
        elif key == "inventory":
            from app.ui.inventory_screen import InventoryScreen
            return InventoryScreen(p, self.user)
        elif key == "compras":
            from app.ui.compras_screen import ComprasScreen
            return ComprasScreen(p, self.user)
        elif key == "customers":
            from app.ui.customers_screen import CustomersScreen
            return CustomersScreen(p, self.user)
        elif key == "suppliers":
            from app.ui.suppliers_screen import SuppliersScreen
            return SuppliersScreen(p, self.user)
        elif key == "employees":
            from app.ui.employees_screen import EmployeesScreen
            return EmployeesScreen(p, self.user)
        elif key == "reports":
            from app.ui.reports_screen import ReportsScreen
            return ReportsScreen(p, self.user)
        elif key == "settings":
            from app.ui.settings_screen import SettingsScreen
            return SettingsScreen(p, self.user)

    # ── Session ───────────────────────────────────────────────────────────────

    # ── Shortcuts ─────────────────────────────────────────────────────────────

    def _bind_shortcuts(self):
        self.bind_all("<F1>",  lambda e: self._show_screen("pos"))
        self.bind_all("<F2>",  lambda e: self._sc_pos_search())
        self.bind_all("<F3>",  lambda e: self._sc_pos_cliente())
        self.bind_all("<F4>",  lambda e: self._sc_pos_edit_qty())
        self.bind_all("<F5>",  lambda e: self._sc_pos_clear())
        self.bind_all("<F6>",  lambda e: self._show_screen("inventory"))
        self.bind_all("<F7>",  lambda e: self._show_screen("reports"))
        self.bind_all("<F8>",  lambda e: self._sc_pos_discount())
        self.bind_all("<F10>", lambda e: self._sc_pos_cobrar())
        self.bind_all("<Key>", self._scanner_key_handler)

    def _get_pos(self):
        return self.screens.get("pos")

    def _sc_pos_search(self):
        if self.current_screen is not self.screens.get("pos"):
            self._show_screen("pos")
        pos = self._get_pos()
        if pos:
            pos.entry_barcode.focus()
            pos.entry_barcode.select_range(0, "end")

    def _sc_pos_cliente(self):
        pos = self._get_pos()
        if pos and self.current_screen is pos:
            pos._seleccionar_cliente()

    def _sc_pos_edit_qty(self):
        pos = self._get_pos()
        if pos and self.current_screen is pos:
            pos._editar_cantidad()

    def _sc_pos_clear(self):
        pos = self._get_pos()
        if pos and self.current_screen is pos:
            pos._limpiar_carrito()

    def _sc_pos_discount(self):
        pos = self._get_pos()
        if pos and self.current_screen is pos:
            pos.entry_descuento.focus()
            pos.entry_descuento.select_range(0, "end")

    def _sc_pos_cobrar(self):
        pos = self._get_pos()
        if pos and self.current_screen is pos:
            pos._cobrar()

    def _scanner_key_handler(self, event):
        # ── Ignorar si diálogo hijo tiene foco ───────────────────────────────
        focused = self.focus_get()
        w = focused
        while w is not None:
            if isinstance(w, tk.Toplevel) and w is not self:
                return
            w = getattr(w, "master", None)

        # ── Si foco está en entry manual legítimo → no interferir ─────────────
        # (usuario escribiendo a mano en POS, compras o inventario)
        live = set()
        for screen_key, attrs in [
            ("pos",       ("entry_barcode", "entry_descuento", "entry_monto")),
            ("compras",   ("entry_codigo",)),
            ("inventory", ("entry_search",)),
        ]:
            scr = self.screens.get(screen_key)
            if scr:
                for attr in attrs:
                    try:
                        live.add(getattr(scr, attr)._entry)
                    except AttributeError:
                        pass
        if focused in live:
            return

        # ── Acumular buffer escáner ───────────────────────────────────────────
        if event.char and event.char.isprintable():
            self._scan_buf += event.char
            if self._scan_timer:
                self.after_cancel(self._scan_timer)
            self._scan_timer = self.after(300, self._reset_scan_buf)
        elif event.keysym in ("Return", "KP_Enter", "Tab") and self._scan_buf:
            barcode = self._scan_buf
            self._scan_buf = ""
            if self._scan_timer:
                self.after_cancel(self._scan_timer)
                self._scan_timer = None
            self.after_idle(lambda b=barcode: self._handle_global_scan(b))

    def _reset_scan_buf(self):
        buf = self._scan_buf
        self._scan_buf   = ""
        self._scan_timer = None
        # Scanner didn't send Enter — dispatch anyway if buffer looks like a barcode
        if len(buf) >= 4:
            self.after_idle(lambda b=buf: self._handle_global_scan(b))

    def _handle_global_scan(self, barcode: str):
        from app.database.models import RolUsuario
        try:
            if self.user.rol == RolUsuario.admin:
                # Admin → inventario: agregar stock o crear producto
                self._show_screen("inventory")
                inv = self.screens.get("inventory")
                if inv:
                    self.after_idle(lambda: inv._scan_barcode(barcode))
            else:
                # Cajero → POS: agregar al carrito para cobrar
                self._show_screen("pos")
                pos = self.screens.get("pos")
                if pos:
                    def _trigger():
                        pos.entry_barcode.delete(0, "end")
                        pos.entry_barcode.insert(0, barcode)
                        pos._buscar_producto()
                    self.after_idle(_trigger)
        except Exception as e:
            from tkinter import messagebox
            messagebox.showerror("Error escáner", str(e))

    # ── Scanner service (serial/SPP mode) ─────────────────────────────────────

    def _init_scanner_service(self):
        # Re-wire singleton callback to this window's handler
        scanner_service.on_barcode = self._serial_barcode_received

        # Always start HID hook (OS-level keyboard capture) — works for USB + BT HID
        threading.Thread(
            target=scanner_service.start_hid_hook, daemon=True
        ).start()

        # Load saved serial config and auto-start if configured
        try:
            from app.database.connection import get_db_session
            from app.database.models import Configuracion
            db = get_db_session()
            try:
                configs = {c.clave: c.valor for c in db.query(Configuracion).all()}
            finally:
                db.close()
            mode  = configs.get("scanner_modo", "hid")
            port  = configs.get("scanner_puerto", "")
            baud  = int(configs.get("scanner_baud", "9600") or "9600")
            if mode == "serial" and port:
                threading.Thread(
                    target=lambda: scanner_service.start_serial(port, baud),
                    daemon=True,
                ).start()
        except Exception as e:
            print(f"[Scanner] Init error: {e}")

    def _serial_barcode_received(self, barcode: str):
        # Called from scanner thread → schedule on UI thread
        self.after(0, lambda b=barcode: self._route_scanner_barcode(b))

    def _route_scanner_barcode(self, barcode: str):
        """
        Central router for HID hook and serial scanner barcodes.
        If a manual entry has focus and the barcode matches what's typed → skip
        (user typing by hand, not a scan burst). Otherwise → handle global scan.
        """
        focused = self.focus_get()

        # Check each manual-entry widget: if focused AND already contains this exact text → skip
        for screen_key, attrs in [
            ("pos",       ("entry_barcode",)),
            ("compras",   ("entry_codigo",)),
            ("inventory", ("entry_search",)),
        ]:
            scr = self.screens.get(screen_key)
            if not scr:
                continue
            for attr in attrs:
                try:
                    widget = getattr(scr, attr)
                    inner = getattr(widget, "_entry", widget)
                    if focused in (widget, inner):
                        # Focus is on a manual entry — let the entry handle it
                        # The entry's <Return>/<Tab> binding will fire separately
                        return
                except AttributeError:
                    pass

        # No manual entry focused → handle as scanner
        self._handle_global_scan(barcode)

    def restart_scanner(self, mode: str, port: str = "", baud: int = 9600):
        """Called by SettingsScreen after saving scanner config."""
        scanner_service.stop_serial()
        if mode == "serial" and port:
            ok = scanner_service.start_serial(port, baud)
            return ok
        return True  # HID mode needs no action here

    # ── Auto-update ───────────────────────────────────────────────────────────

    def _on_update_check(self, available: bool, version: str):
        if available:
            self.after(0, lambda: self._update_btn.configure(
                text=f"⬆ v{version} disponible",
                fg_color="#F59E0B", hover_color="#D97706",
                border_width=0, text_color="white",
                font=ctk.CTkFont(size=11, weight="bold"),
            ))
            if getattr(sys, "frozen", False):
                self.after(0, self._auto_install_update)

    def _auto_install_update(self):
        """Descarga e instala la actualización sin intervención del usuario."""
        st = updater_service.get_status()
        if not st.get("available"):
            return
        version = st.get("version", "")
        toast.show(f"Descargando actualización v{version}…", kind="warning", duration=60000)

        def _do():
            ok, err = updater_service.download_and_install()
            if ok:
                self.after(0, self._on_close)
            else:
                self.after(0, lambda: toast.show(
                    f"Error al actualizar: {err}", kind="error", duration=6000))

        threading.Thread(target=_do, daemon=True, name="AutoUpdater").start()

    def _show_update_dialog(self):
        st = updater_service.get_status()
        available = st.get("available")
        version = st.get("version")

        # Si aún no se chequeó → checar ahora y mostrar "buscando"
        if not st.get("checked"):
            self._update_btn.configure(state="disabled", text="Buscando...")
            def _recheck():
                updater_service.check_for_update_async(self._on_recheck_done)
            threading.Thread(target=_recheck, daemon=True).start()
            return

        # Sin update disponible
        if not available:
            dlg = ctk.CTkToplevel(self)
            dlg.title("Actualizaciones")
            dlg.geometry("360x160")
            dlg.resizable(False, False)
            dlg.grab_set()
            dlg.update_idletasks()
            x = self.winfo_x() + (self.winfo_width() - 360) // 2
            y = self.winfo_y() + (self.winfo_height() - 160) // 2
            dlg.geometry(f"360x160+{x}+{y}")
            ctk.CTkLabel(dlg, text="✓  Tienes la versión más reciente",
                         font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=GREEN).pack(pady=(30, 6))
            ctk.CTkLabel(dlg, text=f"Versión actual: v{cfg.VERSION}",
                         font=ctk.CTkFont(size=12), text_color=MUTED).pack()
            ctk.CTkButton(dlg, text="Cerrar", width=100, height=32,
                          corner_radius=8, fg_color=BLUE, text_color="white",
                          command=dlg.destroy).pack(pady=16)
            return

        # Update disponible → diálogo de descarga
        dlg = ctk.CTkToplevel(self)
        dlg.title("Actualización disponible")
        dlg.geometry("420x290")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 420) // 2
        y = self.winfo_y() + (self.winfo_height() - 290) // 2
        dlg.geometry(f"420x290+{x}+{y}")

        ctk.CTkLabel(dlg, text="⬆  Nueva versión disponible",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=TEXT).pack(pady=(28, 4))
        ctk.CTkLabel(dlg, text=f"v{cfg.VERSION}  →  v{version}",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack(pady=(0, 18))

        lbl_status = ctk.CTkLabel(dlg, text="",
                                  font=ctk.CTkFont(size=11), text_color=MUTED)
        lbl_status.pack(pady=(0, 2))

        prog = ctk.CTkProgressBar(dlg, width=360, mode="determinate")
        prog.set(0)

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack(pady=10)

        btn_cancel = ctk.CTkButton(
            btn_frame, text="Cancelar",
            width=120, height=34, corner_radius=8,
            fg_color="transparent", border_width=1,
            border_color=BORDER, text_color=MUTED,
            hover_color="#FEE2E2", command=dlg.destroy,
        )
        btn_cancel.pack(side="left", padx=8)

        btn_install = ctk.CTkButton(
            btn_frame, text="Descargar e instalar",
            width=170, height=34, corner_radius=8,
            fg_color=BLUE, text_color="white", hover_color="#1D4ED8",
            command=lambda: _start_download(),
        )
        btn_install.pack(side="left", padx=8)

        if not getattr(sys, "frozen", False):
            lbl_status.configure(
                text="Modo desarrollo: solo funciona en EXE instalado",
                text_color="#F59E0B")
            btn_install.configure(state="disabled")

        def _start_download():
            btn_install.configure(state="disabled")
            btn_cancel.configure(state="disabled")
            prog.pack(pady=(4, 0))
            lbl_status.configure(text="Descargando...", text_color=MUTED)

            def on_progress(pct):
                self.after(0, lambda p=pct: prog.set(p))
                self.after(0, lambda p=pct: lbl_status.configure(
                    text=f"Descargando... {p*100:.0f}%"))

            def do_install():
                ok, err = updater_service.download_and_install(on_progress)
                if ok:
                    self.after(0, _finish)
                else:
                    self.after(0, lambda: lbl_status.configure(
                        text=f"Error: {err}", text_color="#EF4444"))
                    self.after(0, lambda: btn_cancel.configure(state="normal"))

            threading.Thread(target=do_install, daemon=True).start()

        def _finish():
            dlg.destroy()
            self._on_close()

    def _on_recheck_done(self, available: bool, version: str):
        self.after(0, lambda: self._update_btn.configure(state="normal"))
        self._on_update_check(available, version)
        if not available:
            self.after(0, lambda: self._update_btn.configure(text="⟳ Actualizar"))
        self.after(0, self._show_update_dialog)

    # ── Session ───────────────────────────────────────────────────────────────

    def _logout(self):
        logout()
        self.destroy()
        if self.on_logout:
            self.on_logout()

    def _on_close(self):
        scanner_service.stop_hid_hook()
        scanner_service.stop_serial()
        logout()
        self.destroy()
        import sys
        sys.exit(0)
