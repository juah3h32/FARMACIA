import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime, date
from app.database.connection import get_db_session
from app.database.models import (
    Producto, Proveedor, Compra, ItemCompra, Lote,
    MovimientoStock, TipoMovimiento, Categoria, RolUsuario
)
from app.auth.auth_service import registrar_accion

BLUE   = "#2563EB"
GREEN  = "#16A34A"
RED    = "#DC2626"
WHITE  = "#FFFFFF"
GRAY   = "#F0F4F8"
BORDER = "#E2E8F0"
TEXT   = "#0F172A"
MUTED  = "#64748B"


def _estilo_tabla():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Compra.Treeview", background="#2b2b2b", foreground="white",
                    rowheight=30, fieldbackground="#2b2b2b", borderwidth=0,
                    font=("Segoe UI", 11))
    style.configure("Compra.Treeview.Heading", background="#1e1e1e", foreground="white",
                    relief="flat", font=("Segoe UI", 11, "bold"))
    style.map("Compra.Treeview", background=[("selected", BLUE)])

    style.configure("Hist.Treeview", background="#2b2b2b", foreground="white",
                    rowheight=28, fieldbackground="#2b2b2b", borderwidth=0,
                    font=("Segoe UI", 11))
    style.configure("Hist.Treeview.Heading", background="#1e1e1e", foreground="white",
                    relief="flat", font=("Segoe UI", 11, "bold"))
    style.map("Hist.Treeview", background=[("selected", BLUE)])

    style.configure("Det.Treeview", background="#1e1e1e", foreground="white",
                    rowheight=26, fieldbackground="#1e1e1e", borderwidth=0,
                    font=("Segoe UI", 10))
    style.configure("Det.Treeview.Heading", background="#111827", foreground="#94A3B8",
                    relief="flat", font=("Segoe UI", 10, "bold"))
    style.map("Det.Treeview", background=[("selected", "#1D4ED8")])


class ComprasScreen(ctk.CTkFrame):
    def __init__(self, parent, user):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.user = user
        self._items: list[dict] = []
        self._producto_actual = None
        _estilo_tabla()
        self._build_ui()

    # ── Layout principal ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        tabs = ctk.CTkTabview(self, corner_radius=10)
        tabs.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)

        tabs.add("🛒  Registrar Compra")
        tabs.add("📋  Historial")

        self._tab_registro = tabs.tab("🛒  Registrar Compra")
        self._tab_historial = tabs.tab("📋  Historial")

        self._tab_registro.grid_columnconfigure(0, weight=1)
        self._tab_registro.grid_rowconfigure(2, weight=1)

        self._tab_historial.grid_columnconfigure(0, weight=1)
        self._tab_historial.grid_rowconfigure(1, weight=3)
        self._tab_historial.grid_rowconfigure(2, weight=2)

        self._build_registro(self._tab_registro)
        self._build_historial(self._tab_historial)

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 1 — REGISTRAR COMPRA
    # ═════════════════════════════════════════════════════════════════════════

    def _build_registro(self, parent):
        self._build_header(parent)
        self._build_entrada_producto(parent)
        self._build_tabla_registro(parent)
        self._build_footer(parent)

    def _build_header(self, parent):
        hdr = ctk.CTkFrame(parent, corner_radius=10, fg_color=WHITE)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        hdr.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(hdr, text="Proveedor:", font=ctk.CTkFont(size=12),
                     text_color=MUTED).grid(row=0, column=0, padx=(14, 4), pady=10)

        db = get_db_session()
        try:
            provs = db.query(Proveedor).filter(Proveedor.activo == True).order_by(Proveedor.nombre).all()
            self._prov_map = {p.nombre: p.id for p in provs}
            prov_nombres = list(self._prov_map.keys()) or ["Sin proveedores"]
        finally:
            db.close()

        self.opt_proveedor = ctk.CTkOptionMenu(hdr, values=prov_nombres, width=180,
                                               fg_color="#F1F5F9", button_color=BLUE,
                                               text_color=TEXT)
        self.opt_proveedor.grid(row=0, column=1, pady=10)

        ctk.CTkLabel(hdr, text="# Factura:", font=ctk.CTkFont(size=12),
                     text_color=MUTED).grid(row=0, column=2, padx=(16, 4), pady=10, sticky="e")
        self.entry_factura = ctk.CTkEntry(hdr, placeholder_text="Opcional", width=130, height=32)
        self.entry_factura.grid(row=0, column=3, pady=10)

        ctk.CTkButton(hdr, text="🗑 Limpiar", width=90, height=32,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=MUTED, hover_color="#FEE2E2",
                      command=self._limpiar).grid(row=0, column=4, padx=14, pady=10)

    def _build_entrada_producto(self, parent):
        ent = ctk.CTkFrame(parent, corner_radius=10, fg_color=WHITE)
        ent.grid(row=1, column=0, sticky="ew", pady=4)

        top = ctk.CTkFrame(ent, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(top, text="Código:", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(side="left")

        self.entry_codigo = ctk.CTkEntry(
            top, placeholder_text="Escanear o escribir código...",
            height=36, font=ctk.CTkFont(size=13), width=260)
        self.entry_codigo.pack(side="left", padx=(6, 4))
        self.entry_codigo.bind("<Return>", lambda e: self._buscar_producto())
        self.entry_codigo.focus_set()

        ctk.CTkButton(top, text="[F3] Buscar", width=90, height=36,
                      fg_color=BLUE, hover_color="#1D4ED8",
                      command=self._buscar_producto).pack(side="left", padx=4)

        self.lbl_producto = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=12, weight="bold"),
                                          text_color=GREEN, wraplength=280)
        self.lbl_producto.pack(side="left", padx=12)

        bot = ctk.CTkFrame(ent, fg_color="transparent")
        bot.pack(fill="x", padx=12, pady=(0, 10))

        def _lbl(t):
            ctk.CTkLabel(bot, text=t, font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left")

        _lbl("Costo unit.:")
        self.entry_costo = ctk.CTkEntry(bot, placeholder_text="0.00", width=90, height=34)
        self.entry_costo.pack(side="left", padx=(4, 10))
        self.entry_costo.bind("<Return>", lambda e: self.entry_pventa.focus_set())

        _lbl("Precio venta:")
        self.entry_pventa = ctk.CTkEntry(bot, placeholder_text="0.00", width=90, height=34)
        self.entry_pventa.pack(side="left", padx=(4, 10))
        self.entry_pventa.bind("<Return>", lambda e: self.entry_cantidad.focus_set())

        _lbl("Cantidad:")
        self.entry_cantidad = ctk.CTkEntry(bot, placeholder_text="1", width=70, height=34)
        self.entry_cantidad.pack(side="left", padx=(4, 10))
        self.entry_cantidad.bind("<Return>", lambda e: self.entry_lote.focus_set())

        _lbl("N° Lote:")
        self.entry_lote = ctk.CTkEntry(bot, placeholder_text="Opcional", width=100, height=34)
        self.entry_lote.pack(side="left", padx=(4, 10))
        self.entry_lote.bind("<Return>", lambda e: self.entry_venc.focus_set())

        _lbl("Vencimiento:")
        self.entry_venc = ctk.CTkEntry(bot, placeholder_text="DD/MM/AAAA", width=110, height=34)
        self.entry_venc.pack(side="left", padx=(4, 10))
        self.entry_venc.bind("<Return>", lambda e: self._agregar_item())

        ctk.CTkButton(bot, text="✔ Agregar", width=90, height=36,
                      fg_color=GREEN, hover_color="#15803D",
                      command=self._agregar_item).pack(side="left", padx=6)

    def _build_tabla_registro(self, parent):
        frame = ctk.CTkFrame(parent, corner_radius=10, fg_color="#2b2b2b")
        frame.grid(row=2, column=0, sticky="nsew", pady=4)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        cols = ("codigo", "producto", "costo", "pventa", "cantidad", "subtotal", "lote", "vencimiento")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                  style="Compra.Treeview", selectmode="browse")
        hdrs = {
            "codigo":      ("Código",        100),
            "producto":    ("Producto",       210),
            "costo":       ("Costo Unit.",     80),
            "pventa":      ("Precio Venta",    90),
            "cantidad":    ("Cant.",           60),
            "subtotal":    ("Subtotal",         80),
            "lote":        ("N° Lote",          80),
            "vencimiento": ("Vencimiento",     90),
        }
        for col, (heading, width) in hdrs.items():
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, minwidth=width,
                             anchor="w" if col == "producto" else "center",
                             stretch=True if col == "producto" else False)

        sy = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", lambda e: self._quitar_item())

        ctk.CTkLabel(frame, text="** Doble clic para quitar artículo",
                     font=ctk.CTkFont(size=10), text_color="gray50"
                     ).grid(row=2, column=0, sticky="w", padx=8, pady=(2, 4))

    def _build_footer(self, parent):
        foot = ctk.CTkFrame(parent, corner_radius=10, fg_color=WHITE)
        foot.grid(row=3, column=0, sticky="ew", pady=(4, 0))

        inner = ctk.CTkFrame(foot, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=10)

        tots = ctk.CTkFrame(inner, fg_color="transparent")
        tots.pack(side="left")
        self.lbl_subtotal = ctk.CTkLabel(tots, text="Subtotal: $0.00",
                                          font=ctk.CTkFont(size=13), text_color=MUTED)
        self.lbl_subtotal.pack(anchor="w")
        self.lbl_total = ctk.CTkLabel(tots, text="Total: $0.00",
                                       font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT)
        self.lbl_total.pack(anchor="w")

        btns = ctk.CTkFrame(inner, fg_color="transparent")
        btns.pack(side="right")
        ctk.CTkButton(btns, text="[ESC] Cancelar", width=120, height=40,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=MUTED, hover_color="#FEE2E2",
                      command=self._limpiar).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="[F4] Registrar Compra", width=165, height=40,
                      fg_color=GREEN, hover_color="#15803D",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._registrar_compra).pack(side="left", padx=6)

        self.bind_all("<F4>", lambda e: self._registrar_compra())
        self.bind_all("<F3>", lambda e: self._buscar_producto())
        self.bind_all("<Escape>", lambda e: self._limpiar())

    # ═════════════════════════════════════════════════════════════════════════
    # TAB 2 — HISTORIAL
    # ═════════════════════════════════════════════════════════════════════════

    def _build_historial(self, parent):
        # Filtros
        filt = ctk.CTkFrame(parent, corner_radius=10, fg_color=WHITE)
        filt.grid(row=0, column=0, sticky="ew", pady=(0, 4))

        fi = ctk.CTkFrame(filt, fg_color="transparent")
        fi.pack(fill="x", padx=12, pady=8)

        ctk.CTkLabel(fi, text="Buscar:", font=ctk.CTkFont(size=12),
                     text_color=MUTED).pack(side="left")
        self.entry_hist_search = ctk.CTkEntry(fi, placeholder_text="Folio o proveedor...",
                                               width=220, height=32)
        self.entry_hist_search.pack(side="left", padx=(6, 12))
        self.entry_hist_search.bind("<KeyRelease>", lambda e: self._load_historial())

        ctk.CTkButton(fi, text="🔄 Actualizar", width=100, height=32,
                      fg_color=BLUE, hover_color="#1D4ED8",
                      command=self._load_historial).pack(side="left", padx=4)

        self.lbl_hist_total = ctk.CTkLabel(fi, text="", font=ctk.CTkFont(size=11),
                                            text_color=MUTED)
        self.lbl_hist_total.pack(side="right", padx=12)

        # Tabla compras
        top_frame = ctk.CTkFrame(parent, corner_radius=10, fg_color="#2b2b2b")
        top_frame.grid(row=1, column=0, sticky="nsew", pady=4)
        top_frame.grid_columnconfigure(0, weight=1)
        top_frame.grid_rowconfigure(0, weight=1)

        hcols = ("folio", "fecha", "proveedor", "articulos", "total", "usuario", "factura")
        self.tree_hist = ttk.Treeview(top_frame, columns=hcols, show="headings",
                                       style="Hist.Treeview", selectmode="browse")
        hhdrs = {
            "folio":     ("Folio",       80),
            "fecha":     ("Fecha",       110),
            "proveedor": ("Proveedor",   160),
            "articulos": ("Arts.",        60),
            "total":     ("Total",        80),
            "usuario":   ("Registró",    100),
            "factura":   ("Factura/Notas",140),
        }
        for col, (heading, width) in hhdrs.items():
            self.tree_hist.heading(col, text=heading)
            self.tree_hist.column(col, width=width, minwidth=width,
                                   anchor="w" if col in ("proveedor", "factura", "usuario") else "center",
                                   stretch=True if col == "proveedor" else False)

        shy = ttk.Scrollbar(top_frame, orient="vertical", command=self.tree_hist.yview)
        self.tree_hist.configure(yscrollcommand=shy.set)
        self.tree_hist.grid(row=0, column=0, sticky="nsew")
        shy.grid(row=0, column=1, sticky="ns")
        self.tree_hist.bind("<<TreeviewSelect>>", lambda e: self._load_detalle())

        # Tabla detalle de la compra seleccionada
        bot_frame = ctk.CTkFrame(parent, corner_radius=10, fg_color="#1e1e1e")
        bot_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 0))
        bot_frame.grid_columnconfigure(0, weight=1)
        bot_frame.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(bot_frame, text="Detalle de compra seleccionada",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=0, column=0, sticky="w", padx=10, pady=(6, 2))

        dcols = ("codigo", "producto", "costo", "pventa", "cantidad", "subtotal", "lote", "vencimiento")
        self.tree_det = ttk.Treeview(bot_frame, columns=dcols, show="headings",
                                      style="Det.Treeview", selectmode="none")
        dhdrs = {
            "codigo":      ("Código",        110),
            "producto":    ("Producto",       240),
            "costo":       ("Costo Unit.",     85),
            "pventa":      ("Precio Venta",    90),
            "cantidad":    ("Cantidad",         70),
            "subtotal":    ("Subtotal",         85),
            "lote":        ("N° Lote",          85),
            "vencimiento": ("Vencimiento",      95),
        }
        for col, (heading, width) in dhdrs.items():
            self.tree_det.heading(col, text=heading)
            self.tree_det.column(col, width=width, anchor="w" if col == "producto" else "center")

        dsy = ttk.Scrollbar(bot_frame, orient="vertical", command=self.tree_det.yview)
        self.tree_det.configure(yscrollcommand=dsy.set)
        self.tree_det.grid(row=1, column=0, sticky="nsew")
        dsy.grid(row=1, column=1, sticky="ns")

        self._load_historial()

    def _load_historial(self):
        for row in self.tree_hist.get_children():
            self.tree_hist.delete(row)
        for row in self.tree_det.get_children():
            self.tree_det.delete(row)

        busq = self.entry_hist_search.get().strip().lower()

        db = get_db_session()
        try:
            from app.database.models import Usuario
            compras = (db.query(Compra)
                       .order_by(Compra.creado_en.desc())
                       .limit(300)
                       .all())

            mostradas = 0
            for c in compras:
                prov_nombre = c.proveedor.nombre if c.proveedor else "—"
                usr_nombre  = c.usuario.nombre   if c.usuario   else "—"
                num_items   = len(c.items)
                notas       = c.notas or ""

                if busq and busq not in (c.folio or "").lower() and busq not in prov_nombre.lower():
                    continue

                fecha_str = c.creado_en.strftime("%d/%m/%Y %H:%M") if c.creado_en else ""
                self.tree_hist.insert("", "end", iid=str(c.id), values=(
                    c.folio or "",
                    fecha_str,
                    prov_nombre,
                    num_items,
                    f"${c.total:,.2f}",
                    usr_nombre,
                    notas,
                ))
                mostradas += 1

            self.lbl_hist_total.configure(text=f"{mostradas} compras")
        finally:
            db.close()

    def _load_detalle(self):
        for row in self.tree_det.get_children():
            self.tree_det.delete(row)

        sel = self.tree_hist.selection()
        if not sel:
            return
        compra_id = int(sel[0])

        db = get_db_session()
        try:
            items = db.query(ItemCompra).filter(ItemCompra.compra_id == compra_id).all()
            for it in items:
                prod = it.producto
                lote = it.lote
                cod   = prod.codigo_barras or "" if prod else ""
                nom   = prod.nombre         if prod else "?"
                pventa = prod.precio_venta  if prod else 0.0
                lote_n = lote.numero_lote   if lote else ""
                venc   = ""
                if lote and lote.fecha_vencimiento:
                    venc = lote.fecha_vencimiento.strftime("%d/%m/%Y")

                self.tree_det.insert("", "end", values=(
                    cod, nom,
                    f"${it.precio_unitario:.2f}",
                    f"${pventa:.2f}",
                    it.cantidad,
                    f"${it.subtotal:.2f}",
                    lote_n, venc,
                ))
        finally:
            db.close()

    # ═════════════════════════════════════════════════════════════════════════
    # LÓGICA REGISTRO
    # ═════════════════════════════════════════════════════════════════════════

    def _buscar_producto(self):
        codigo = self.entry_codigo.get().strip()
        if not codigo:
            self.entry_codigo.focus_set()
            return

        db = get_db_session()
        try:
            prod = db.query(Producto).filter(
                (Producto.codigo_barras == codigo) | Producto.nombre.ilike(f"%{codigo}%")
            ).filter(Producto.activo == True).first()

            if prod:
                self._producto_actual = {
                    "id":            prod.id,
                    "codigo":        prod.codigo_barras or codigo,
                    "nombre":        prod.nombre,
                    "precio_compra": prod.precio_compra,
                    "precio_venta":  prod.precio_venta,
                    "stock":         prod.stock,
                }
                self.lbl_producto.configure(
                    text=f"✓ {prod.nombre}  (Stock: {prod.stock})",
                    text_color=GREEN,
                )
                self.entry_costo.delete(0, "end")
                self.entry_costo.insert(0, f"{prod.precio_compra:.2f}")
                self.entry_pventa.delete(0, "end")
                self.entry_pventa.insert(0, f"{prod.precio_venta:.2f}")
                CantidadDialog(self, prod.nombre, prod.stock,
                               on_confirm=self._on_cantidad_confirmada)
            else:
                self._producto_actual = None
                self.lbl_producto.configure(text=f"✗ '{codigo}' no encontrado", text_color=RED)
                if self.user.rol == RolUsuario.admin:
                    self._crear_producto_nuevo(codigo)
                else:
                    messagebox.showwarning("No encontrado",
                                           f"'{codigo}' no existe.\nContacta al administrador.")
        finally:
            db.close()

    def _on_cantidad_confirmada(self, cantidad, lote, vencimiento):
        if cantidad is None:
            self._limpiar_entrada()
            return
        self.entry_cantidad.delete(0, "end")
        self.entry_cantidad.insert(0, str(cantidad))
        self.entry_lote.delete(0, "end")
        if lote:
            self.entry_lote.insert(0, lote)
        self.entry_venc.delete(0, "end")
        if vencimiento:
            self.entry_venc.insert(0, vencimiento)
        self._agregar_item()

    def _crear_producto_nuevo(self, codigo_barras: str):
        from app.ui.inventory_screen import ProductoDialog
        ProductoDialog(self, title="Nuevo Producto",
                       data={"codigo_barras": codigo_barras},
                       on_save=lambda: self._buscar_producto())

    def _agregar_item(self):
        if not self._producto_actual:
            messagebox.showwarning("Sin producto", "Primero busca o escanea un producto")
            return
        try:
            cantidad = int(self.entry_cantidad.get().strip() or "1")
            if cantidad <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Cantidad", "Cantidad debe ser número entero positivo")
            return
        try:
            costo = float(self.entry_costo.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Costo", "Costo inválido")
            return
        try:
            pventa = float(self.entry_pventa.get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Precio venta", "Precio venta inválido")
            return

        lote_num = self.entry_lote.get().strip() or None
        venc_str = self.entry_venc.get().strip()
        fecha_venc = None
        if venc_str:
            try:
                fecha_venc = datetime.strptime(venc_str, "%d/%m/%Y").date()
            except ValueError:
                messagebox.showwarning("Fecha", "Formato incorrecto (DD/MM/AAAA)")
                return

        subtotal = costo * cantidad
        item = {
            "producto_id": self._producto_actual["id"],
            "codigo":      self._producto_actual["codigo"],
            "nombre":      self._producto_actual["nombre"],
            "costo":       costo,
            "pventa":      pventa,
            "cantidad":    cantidad,
            "subtotal":    subtotal,
            "lote":        lote_num or "",
            "vencimiento": fecha_venc.strftime("%d/%m/%Y") if fecha_venc else "",
            "fecha_venc":  fecha_venc,
        }
        self._items.append(item)
        self.tree.insert("", "end", values=(
            item["codigo"], item["nombre"],
            f"${costo:.2f}", f"${pventa:.2f}",
            cantidad, f"${subtotal:.2f}",
            item["lote"], item["vencimiento"],
        ))
        self._actualizar_totales()
        self._limpiar_entrada()

    def _quitar_item(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        self.tree.delete(sel[0])
        self._items.pop(idx)
        self._actualizar_totales()

    def _actualizar_totales(self):
        total = sum(i["subtotal"] for i in self._items)
        self.lbl_subtotal.configure(text=f"Subtotal: ${total:,.2f}")
        self.lbl_total.configure(text=f"Total: ${total:,.2f}")

    def _limpiar_entrada(self):
        self.entry_codigo.delete(0, "end")
        self.entry_costo.delete(0, "end")
        self.entry_pventa.delete(0, "end")
        self.entry_cantidad.delete(0, "end")
        self.entry_lote.delete(0, "end")
        self.entry_venc.delete(0, "end")
        self.lbl_producto.configure(text="")
        self._producto_actual = None
        self.entry_codigo.focus_set()

    def _limpiar(self):
        if self._items:
            if not messagebox.askyesno("Limpiar", "¿Borrar todos los artículos?"):
                return
        for row in self.tree.get_children():
            self.tree.delete(row)
        self._items.clear()
        self._actualizar_totales()
        self._limpiar_entrada()
        self.entry_factura.delete(0, "end")

    def _registrar_compra(self):
        if not self._items:
            messagebox.showwarning("Sin artículos", "Agrega al menos un artículo")
            return

        prov_nombre = self.opt_proveedor.get()
        prov_id     = self._prov_map.get(prov_nombre)
        factura     = self.entry_factura.get().strip() or None
        total       = sum(i["subtotal"] for i in self._items)

        if not messagebox.askyesno("Confirmar",
                                   f"Registrar compra:\n"
                                   f"Proveedor: {prov_nombre}\n"
                                   f"Artículos: {len(self._items)}\n"
                                   f"Total: ${total:,.2f}\n\n¿Continuar?"):
            return

        db = get_db_session()
        try:
            folio = f"C{datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}"
            compra = Compra(
                folio=folio,
                proveedor_id=prov_id,
                usuario_id=self.user.id,
                total=total,
                notas=f"Factura: {factura}" if factura else None,
            )
            db.add(compra)
            db.flush()

            for item in self._items:
                prod = db.query(Producto).filter(Producto.id == item["producto_id"]).first()
                if not prod:
                    continue
                prod.precio_compra = item["costo"]
                if item["pventa"] > 0:
                    prod.precio_venta = item["pventa"]
                stock_ant   = prod.stock
                prod.stock += item["cantidad"]

                lote = Lote(
                    producto_id=prod.id,
                    numero_lote=item["lote"] or None,
                    fecha_vencimiento=item["fecha_venc"],
                    cantidad=item["cantidad"],
                    precio_compra=item["costo"],
                )
                db.add(lote)
                db.flush()

                db.add(ItemCompra(
                    compra_id=compra.id,
                    producto_id=prod.id,
                    lote_id=lote.id,
                    cantidad=item["cantidad"],
                    precio_unitario=item["costo"],
                    subtotal=item["subtotal"],
                ))
                db.add(MovimientoStock(
                    producto_id=prod.id,
                    tipo=TipoMovimiento.entrada,
                    cantidad=item["cantidad"],
                    stock_anterior=stock_ant,
                    stock_nuevo=prod.stock,
                    referencia_id=compra.id,
                    referencia_tipo="compra",
                    usuario_id=self.user.id,
                    notas=f"Compra {folio} | Lote:{item['lote'] or 'S/N'}",
                ))

            db.commit()
            registrar_accion("REGISTRAR_COMPRA", "compras", compra.id,
                             f"Folio:{folio} Total:${total:.2f} Items:{len(self._items)}")
            messagebox.showinfo("Registrada",
                                f"Compra {folio} registrada.\n"
                                f"Stock actualizado: {len(self._items)} producto(s).")
            self._limpiar()
            self._load_historial()

        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()

    def on_show(self):
        db = get_db_session()
        try:
            provs = db.query(Proveedor).filter(Proveedor.activo == True).order_by(Proveedor.nombre).all()
            self._prov_map = {p.nombre: p.id for p in provs}
            nombres = list(self._prov_map.keys()) or ["Sin proveedores"]
            self.opt_proveedor.configure(values=nombres)
            if nombres:
                self.opt_proveedor.set(nombres[0])
        finally:
            db.close()
        self._load_historial()
        self.entry_codigo.focus_set()


# ─────────────────────────────────────────────────────────────────────────────

class CantidadDialog(ctk.CTkToplevel):
    """Popup rápido: producto encontrado → pedir cantidad."""

    def __init__(self, parent, nombre: str, stock_actual: int, on_confirm):
        super().__init__(parent)
        self.on_confirm = on_confirm
        self.title("Cantidad a ingresar")
        self.geometry("380x280")
        self.resizable(False, False)
        self.grab_set()
        self._build(nombre, stock_actual)
        self.after(100, lambda: self.entry_cant.focus_set())

    def _build(self, nombre: str, stock_actual: int):
        ctk.CTkLabel(self, text="Producto encontrado",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=GREEN).pack(pady=(20, 4))
        ctk.CTkLabel(self, text=nombre, font=ctk.CTkFont(size=12),
                     text_color=TEXT, wraplength=340).pack(padx=20)
        ctk.CTkLabel(self, text=f"Stock actual: {stock_actual}",
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(pady=(4, 12))

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=24)
        frame.grid_columnconfigure(1, weight=1)

        def _row(r, label, widget_factory):
            ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=12)).grid(
                row=r, column=0, sticky="e", padx=(0, 8), pady=4)
            w = widget_factory()
            w.grid(row=r, column=1, sticky="ew", pady=4)
            return w

        self.entry_cant = _row(0, "Cantidad:", lambda: ctk.CTkEntry(frame, height=36,
                                                                      font=ctk.CTkFont(size=14)))
        self.entry_cant.insert(0, "1")
        self.entry_cant.bind("<Return>", lambda e: self.entry_lote.focus_set())

        self.entry_lote = _row(1, "N° Lote:", lambda: ctk.CTkEntry(frame, placeholder_text="Opcional", height=34))
        self.entry_lote.bind("<Return>", lambda e: self.entry_venc.focus_set())

        self.entry_venc = _row(2, "Vencimiento:", lambda: ctk.CTkEntry(frame, placeholder_text="DD/MM/AAAA", height=34))
        self.entry_venc.bind("<Return>", lambda e: self._confirmar())

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=24, pady=16)
        ctk.CTkButton(btns, text="Cancelar", width=100, height=36,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=MUTED, hover_color="#FEE2E2",
                      command=self._cancelar).pack(side="left")
        ctk.CTkButton(btns, text="✔ Agregar", width=140, height=36,
                      fg_color=GREEN, hover_color="#15803D",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=self._confirmar).pack(side="right")

    def _confirmar(self):
        try:
            cant = int(self.entry_cant.get().strip() or "1")
            if cant <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Cantidad", "Ingresa número entero positivo", parent=self)
            return
        lote = self.entry_lote.get().strip()
        venc = self.entry_venc.get().strip()
        self.destroy()
        self.on_confirm(cant, lote, venc)

    def _cancelar(self):
        self.destroy()
        self.on_confirm(None, None, None)
