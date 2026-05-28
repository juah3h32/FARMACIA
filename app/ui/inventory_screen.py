import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
from datetime import date, timedelta
from app.database.connection import get_db_session
from app.database.models import (
    Producto, Categoria, Proveedor, Lote,
    MovimientoStock, TipoMovimiento
)
from app.auth.auth_service import registrar_accion
import app.config as cfg


class InventoryScreen(ctk.CTkFrame):
    def __init__(self, parent, user):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.user = user
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        hdr.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(hdr, text="📦 Inventario", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=14, pady=10, sticky="w"
        )

        self.entry_search = ctk.CTkEntry(hdr, placeholder_text="🔍 Buscar o escanear código...", height=36, width=300)
        self.entry_search.grid(row=0, column=1, padx=8, pady=10)
        self.entry_search.bind("<KeyRelease>", lambda e: self._load_products())
        for event in ("<Return>", "<KP_Enter>", "<Tab>"):
            self.entry_search.bind(event, lambda e: self._on_scan_enter())
            try:
                self.entry_search._entry.bind(event, lambda e: self._on_scan_enter())
            except Exception:
                pass

        self.var_filter = tk.StringVar(value="todos")
        ctk.CTkSegmentedButton(
            hdr, values=["Todos", "Stock Bajo", "Por Vencer"],
            variable=self.var_filter, command=lambda v: self._load_products()
        ).grid(row=0, column=2, padx=8)

        # Botones accion
        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.grid(row=0, column=3, padx=14, pady=10)

        ctk.CTkButton(btns, text="+ Agregar", width=90, height=34,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._agregar_producto).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="✏️ Editar", width=80, height=34,
                      command=self._editar_producto).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="📥 Entrada", width=90, height=34,
                      fg_color="#2196F3", hover_color="#1976D2",
                      command=self._entrada_stock).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="🗑 Eliminar", width=80, height=34,
                      fg_color="#e74c3c", hover_color="#c0392b",
                      command=self._eliminar_producto).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="🗓 Lotes", width=80, height=34,
                      fg_color="#9C27B0", hover_color="#7B1FA2",
                      command=self._ver_lotes).pack(side="left", padx=3)

        # Tabla
        table_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        table_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Inv.Treeview",
                        background="#FFFFFF", foreground="#0F172A",
                        rowheight=30, fieldbackground="#FFFFFF",
                        borderwidth=0, font=("Segoe UI", 11))
        style.configure("Inv.Treeview.Heading",
                        background="#F1F5F9", foreground="#64748B",
                        relief="flat", font=("Segoe UI", 11, "bold"), padding=(6, 6))
        style.map("Inv.Treeview",
                  background=[("selected", "#EFF6FF")],
                  foreground=[("selected", "#2563EB")])
        style.layout("Inv.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        cols = ("id", "barcode", "nombre", "categoria", "precio", "stock", "minimo", "vencimiento", "estado")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                  style="Inv.Treeview", selectmode="browse")

        headers = {
            "id": ("ID", 40), "barcode": ("Código", 110), "nombre": ("Producto", 230),
            "categoria": ("Categoría", 130), "precio": ("Precio", 80),
            "stock": ("Stock", 65), "minimo": ("Mínimo", 65),
            "vencimiento": ("Próx. Vencim.", 120), "estado": ("Estado", 100),
        }
        for col, (heading, width) in headers.items():
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, anchor="center" if col not in ("nombre",) else "w")

        self.tree.tag_configure("low_stock", foreground="#D97706", background="#FFFBEB")
        self.tree.tag_configure("expiring",  foreground="#DC2626", background="#FEF2F2")
        self.tree.tag_configure("ok",        foreground="#16A34A")

        scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        self.tree.bind("<Double-1>", lambda e: self._editar_producto())

        # Status bar
        self.lbl_status = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                        text_color="gray60")
        self.lbl_status.grid(row=2, column=0, padx=12, pady=(0, 4), sticky="w")

        self._load_products()

    def _load_products(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        db = get_db_session()
        try:
            q = db.query(Producto).filter(Producto.activo == True)

            search = self.entry_search.get().strip()
            if search:
                q = q.filter(
                    Producto.nombre.ilike(f"%{search}%") |
                    Producto.codigo_barras.ilike(f"%{search}%") |
                    Producto.nombre_generico.ilike(f"%{search}%") |
                    Producto.id.in_(
                        db.query(Lote.producto_id).filter(Lote.numero_lote.ilike(f"%{search}%"))
                    )
                )

            filtro = self.var_filter.get()
            if filtro == "Stock Bajo":
                q = q.filter(Producto.stock <= Producto.stock_minimo)

            productos = q.order_by(Producto.nombre).all()

            hoy = date.today()
            alerta_dias = hoy + timedelta(days=cfg.EXPIRY_ALERT_DAYS)

            for p in productos:
                # Lote con vencimiento mas proximo
                lote_prox = None
                if p.lotes:
                    lotes_validos = [l for l in p.lotes if l.fecha_vencimiento and l.cantidad > 0]
                    if lotes_validos:
                        lote_prox = min(lotes_validos, key=lambda l: l.fecha_vencimiento)

                vencim_str = ""
                tag = "ok"

                if lote_prox:
                    vencim_str = lote_prox.fecha_vencimiento.strftime("%d/%m/%Y")
                    if lote_prox.fecha_vencimiento <= hoy:
                        tag = "expiring"
                        vencim_str = f"⚠ {vencim_str}"
                    elif lote_prox.fecha_vencimiento <= alerta_dias:
                        tag = "expiring"

                if p.stock <= p.stock_minimo:
                    tag = "low_stock"

                # Skip si filtro por vencer
                if filtro == "Por Vencer":
                    if not lote_prox or lote_prox.fecha_vencimiento > alerta_dias:
                        continue

                estado = "OK"
                if p.stock <= 0:
                    estado = "⛔ Sin stock"
                elif p.stock <= p.stock_minimo:
                    estado = "⚠ Stock bajo"
                elif lote_prox and lote_prox.fecha_vencimiento <= alerta_dias:
                    estado = "⚠ Por vencer"

                self.tree.insert("", "end", iid=str(p.id), values=(
                    p.id,
                    p.codigo_barras or "",
                    p.nombre,
                    p.categoria.nombre if p.categoria else "",
                    f"${p.precio_venta:.2f}",
                    p.stock,
                    p.stock_minimo,
                    vencim_str,
                    estado,
                ), tags=(tag,))

            total = len(productos)
            low = sum(1 for p in productos if p.stock <= p.stock_minimo)
            self.lbl_status.configure(text=f"Total: {total} productos  |  Stock bajo: {low}")

        finally:
            db.close()

    def _get_selected_id(self) -> int | None:
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def _agregar_producto(self):
        ProductoDialog(self, title="Agregar Producto", on_save=self._load_products)

    def _editar_producto(self):
        pid = self._get_selected_id()
        if not pid:
            messagebox.showwarning("Seleccionar", "Selecciona un producto")
            return
        db = get_db_session()
        try:
            prod = db.query(Producto).filter(Producto.id == pid).first()
            if prod:
                data = {
                    "id": prod.id, "codigo_barras": prod.codigo_barras or "",
                    "nombre": prod.nombre, "nombre_generico": prod.nombre_generico or "",
                    "marca": prod.marca or "", "precio_venta": prod.precio_venta,
                    "precio_compra": prod.precio_compra, "stock": prod.stock,
                    "stock_minimo": prod.stock_minimo, "aplica_iva": prod.aplica_iva,
                    "requiere_receta": prod.requiere_receta,
                    "sustancia_controlada": prod.sustancia_controlada,
                    "descripcion": prod.descripcion or "",
                    "categoria_id": prod.categoria_id,
                    "proveedor_id": prod.proveedor_id,
                }
                ProductoDialog(self, title="Editar Producto", data=data, on_save=self._load_products)
        finally:
            db.close()

    def _entrada_stock(self):
        pid = self._get_selected_id()
        if not pid:
            messagebox.showwarning("Seleccionar", "Selecciona un producto para agregar stock")
            return
        EntradaStockDialog(self, producto_id=pid, usuario_id=self.user.id, on_save=self._load_products)

    def _eliminar_producto(self):
        pid = self._get_selected_id()
        if not pid:
            messagebox.showwarning("Seleccionar", "Selecciona un producto")
            return
        if not messagebox.askyesno("Confirmar", "¿Eliminar este producto?\n(Se desactivará, no se borrará)"):
            return
        db = get_db_session()
        try:
            prod = db.query(Producto).filter(Producto.id == pid).first()
            if prod:
                prod.activo = False
                db.commit()
                registrar_accion("ELIMINAR_PRODUCTO", "productos", pid, prod.nombre)
                self._load_products()
        finally:
            db.close()

    def _ver_lotes(self):
        pid = self._get_selected_id()
        if not pid:
            messagebox.showwarning("Seleccionar", "Selecciona un producto para ver sus lotes")
            return
        LotesDialog(self, producto_id=pid)

    def _on_scan_enter(self):
        barcode = self.entry_search.get().strip()
        if barcode:
            self.entry_search.delete(0, "end")
            self._load_products()
            self._scan_barcode(barcode)

    def _scan_barcode(self, barcode: str):
        try:
            db = get_db_session()
            try:
                prod = db.query(Producto).filter(
                    Producto.codigo_barras == barcode,
                    Producto.activo == True
                ).first()
            finally:
                db.close()

            if prod:
                d = EntradaStockDialog(self, producto_id=prod.id,
                                       usuario_id=self.user.id,
                                       on_save=self._load_products)
                d.lift()
                d.focus_force()
            else:
                d = ProductoDialog(self, title="Nuevo Producto",
                                   data={"codigo_barras": barcode},
                                   on_save=self._load_products)
                d.lift()
                d.focus_force()
        except Exception as e:
            messagebox.showerror("Error escáner", str(e))

    def on_show(self):
        self._load_products()


class ProductoDialog(ctk.CTkToplevel):
    def __init__(self, parent, title: str, data: dict = None, on_save=None):
        super().__init__(parent)
        self.title(title)
        self.geometry("560x700")
        self.grab_set()
        self.data = data or {}
        self.on_save = on_save
        self._build_ui()
        # <Map> fires once the window is fully visible and CTkToplevel has completed
        # all internal initialization (appearance-mode passes, scaling callbacks, etc.)
        # that otherwise clear CTkEntry contents. A fixed after() delay is unreliable.
        self.bind("<Map>", self._on_first_map)

    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=16, pady=16)
        scroll.grid_columnconfigure(1, weight=1)

        fields = [
            ("Código de Barras:", "codigo_barras", "entry"),
            ("Nombre del Producto:*", "nombre", "entry"),
            ("Nombre Genérico:", "nombre_generico", "entry"),
            ("Marca:", "marca", "entry"),
            ("Precio de Venta:*", "precio_venta", "entry"),
            ("Precio de Compra:", "precio_compra", "entry"),
            ("Stock Actual:", "stock", "entry"),
            ("Stock Mínimo:", "stock_minimo", "entry"),
        ]

        self.entries = {}
        for i, (label, key, ftype) in enumerate(fields):
            ctk.CTkLabel(scroll, text=label, font=ctk.CTkFont(size=12), anchor="e").grid(
                row=i, column=0, padx=(0, 8), pady=5, sticky="e"
            )
            e = ctk.CTkEntry(scroll, height=34)
            e.grid(row=i, column=1, pady=5, sticky="ew")
            self.entries[key] = e

        # Barcode auto-fill on Enter
        self.entries["codigo_barras"].bind("<Return>", self._on_barcode_scan)

        # Categoria + Proveedor (single DB session)
        row = len(fields)
        db = get_db_session()
        try:
            cats = db.query(Categoria).all()
            cat_names = [c.nombre for c in cats]
            self._cat_map = {c.nombre: c.id for c in cats}
            provs = db.query(Proveedor).filter(Proveedor.activo == True).all()
            prov_names = [p.nombre for p in provs]
            self._prov_map = {p.nombre: p.id for p in provs}
        finally:
            db.close()

        ctk.CTkLabel(scroll, text="Categoría:", anchor="e").grid(row=row, column=0, padx=(0, 8), pady=5, sticky="e")
        self.opt_cat = ctk.CTkOptionMenu(scroll, values=cat_names if cat_names else ["Sin categorías"])
        self.opt_cat.grid(row=row, column=1, pady=5, sticky="ew")

        row += 1
        ctk.CTkLabel(scroll, text="Proveedor:", anchor="e").grid(row=row, column=0, padx=(0, 8), pady=5, sticky="e")
        self.opt_prov = ctk.CTkOptionMenu(scroll, values=prov_names if prov_names else ["Sin proveedores"])
        self.opt_prov.grid(row=row, column=1, pady=5, sticky="ew")

        # Checkboxes
        row += 1
        checks_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        checks_frame.grid(row=row, column=0, columnspan=2, pady=8, sticky="w")
        self.var_iva = tk.BooleanVar(value=False)
        self.var_receta = tk.BooleanVar(value=False)
        self.var_controlada = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(checks_frame, text="Aplica IVA (16%)", variable=self.var_iva).pack(side="left", padx=8)
        ctk.CTkCheckBox(checks_frame, text="Requiere Receta", variable=self.var_receta).pack(side="left", padx=8)
        ctk.CTkCheckBox(checks_frame, text="Sust. Controlada", variable=self.var_controlada).pack(side="left", padx=8)

        # Descripcion
        row += 1
        ctk.CTkLabel(scroll, text="Descripción:", anchor="e").grid(row=row, column=0, padx=(0, 8), pady=5, sticky="ne")
        self.txt_desc = ctk.CTkTextbox(scroll, height=70)
        self.txt_desc.grid(row=row, column=1, pady=5, sticky="ew")

        # Boton guardar
        ctk.CTkButton(
            self, text="💾 Guardar", height=42, fg_color="#4CAF50", hover_color="#388E3C",
            command=self._guardar
        ).pack(fill="x", padx=16, pady=(0, 16))

    def _on_first_map(self, event=None):
        self.unbind("<Map>")
        self.after(30, self._populate_fields)

    def _populate_fields(self):
        """Populate entry widgets with self.data AFTER CTkToplevel fully renders."""
        for key, e in self.entries.items():
            val = self.data.get(key)
            if val is not None:
                e.delete(0, "end")
                e.insert(0, str(val))

        if self.data.get("categoria_id"):
            for name, cid in self._cat_map.items():
                if cid == self.data["categoria_id"]:
                    self.opt_cat.set(name)
                    break

        if self.data.get("proveedor_id"):
            for name, pid in self._prov_map.items():
                if pid == self.data["proveedor_id"]:
                    self.opt_prov.set(name)
                    break

        self.var_iva.set(self.data.get("aplica_iva", False))
        self.var_receta.set(self.data.get("requiere_receta", False))
        self.var_controlada.set(self.data.get("sustancia_controlada", False))

        if self.data.get("descripcion"):
            self.txt_desc.delete("1.0", "end")
            self.txt_desc.insert("1.0", self.data["descripcion"])

    def _guardar(self):
        nombre = self.entries["nombre"].get().strip()
        if not nombre:
            messagebox.showwarning("Error", "El nombre es obligatorio")
            return
        try:
            precio_venta = float(self.entries["precio_venta"].get().strip() or "0")
        except ValueError:
            messagebox.showwarning("Error", "Precio de venta inválido")
            return

        db = get_db_session()
        try:
            if self.data.get("id"):
                prod = db.query(Producto).filter(Producto.id == self.data["id"]).first()
            else:
                prod = Producto()
                db.add(prod)

            prod.nombre = nombre
            prod.codigo_barras = self.entries["codigo_barras"].get().strip() or None
            prod.nombre_generico = self.entries["nombre_generico"].get().strip() or None
            prod.marca = self.entries["marca"].get().strip() or None
            prod.precio_venta = precio_venta
            prod.precio_compra = float(self.entries["precio_compra"].get().strip() or "0")
            prod.stock = int(self.entries["stock"].get().strip() or "0")
            prod.stock_minimo = int(self.entries["stock_minimo"].get().strip() or "10")
            prod.aplica_iva = self.var_iva.get()
            prod.requiere_receta = self.var_receta.get()
            prod.sustancia_controlada = self.var_controlada.get()
            prod.descripcion = self.txt_desc.get("1.0", "end").strip() or None
            prod.categoria_id = self._cat_map.get(self.opt_cat.get())
            prod.proveedor_id = self._prov_map.get(self.opt_prov.get())

            db.commit()
            registrar_accion("GUARDAR_PRODUCTO", "productos", prod.id, prod.nombre)
            if self.on_save:
                self.on_save()
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()


    def _on_barcode_scan(self, event=None):
        barcode = self.entries["codigo_barras"].get().strip()
        if not barcode:
            return
        db = get_db_session()
        try:
            prod = db.query(Producto).filter(Producto.codigo_barras == barcode).first()
            if not prod:
                return
            if self.data.get("id") == prod.id:
                return
            if not messagebox.askyesno("Producto encontrado",
                                        f"Encontrado: {prod.nombre}\n¿Cargar sus datos?"):
                return
            for key, val in [
                ("nombre", prod.nombre), ("nombre_generico", prod.nombre_generico or ""),
                ("marca", prod.marca or ""), ("precio_venta", prod.precio_venta),
                ("precio_compra", prod.precio_compra), ("stock", prod.stock),
                ("stock_minimo", prod.stock_minimo),
            ]:
                e = self.entries[key]
                e.delete(0, "end")
                e.insert(0, str(val) if val is not None else "")
            self.var_iva.set(prod.aplica_iva)
            self.var_receta.set(prod.requiere_receta)
            self.var_controlada.set(prod.sustancia_controlada)
            if prod.descripcion:
                self.txt_desc.delete("1.0", "end")
                self.txt_desc.insert("1.0", prod.descripcion)
            if prod.categoria:
                self.opt_cat.set(prod.categoria.nombre)
            if prod.proveedor:
                self.opt_prov.set(prod.proveedor.nombre)
        finally:
            db.close()


class EntradaStockDialog(ctk.CTkToplevel):
    """Dialogo para registrar entrada de mercancia"""
    def __init__(self, parent, producto_id: int, usuario_id: int, on_save=None):
        super().__init__(parent)
        self.producto_id = producto_id
        self.usuario_id = usuario_id
        self.on_save = on_save
        self.title("Entrada de Stock")
        self.geometry("420x420")
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        db = get_db_session()
        try:
            from sqlalchemy.orm import joinedload
            prod = db.query(Producto).options(
                joinedload(Producto.categoria)
            ).filter(Producto.id == self.producto_id).first()
            nombre          = prod.nombre if prod else "?"
            nombre_generico = (prod.nombre_generico or "") if prod else ""
            marca           = (prod.marca or "") if prod else ""
            stock_actual    = prod.stock if prod else 0
            precio_venta    = prod.precio_venta if prod else 0.0
            categoria       = prod.categoria.nombre if (prod and prod.categoria) else ""
            partes = [x for x in (
                getattr(prod, "presentacion", None),
                getattr(prod, "concentracion", None),
                getattr(prod, "contenido", None),
            ) if x] if prod else []
            presentacion    = "  ·  ".join(partes)
            req_receta      = prod.requiere_receta if prod else False
            controlada      = prod.sustancia_controlada if prod else False
        finally:
            db.close()

        ctk.CTkLabel(self, text="📥 Entrada de Stock",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(16, 4))

        # ── Tarjeta del producto ──────────────────────────────────────────────
        card = ctk.CTkFrame(self, corner_radius=10, fg_color="#F0F4F8",
                            border_width=1, border_color="#E2E8F0")
        card.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(card, text=nombre,
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color="#0F172A", anchor="w", wraplength=360,
                     ).pack(anchor="w", padx=12, pady=(10, 2))

        if nombre_generico or marca:
            sub = "  ·  ".join(x for x in (nombre_generico, marca) if x)
            ctk.CTkLabel(card, text=sub, font=ctk.CTkFont(size=11),
                         text_color="#64748B", anchor="w",
                         ).pack(anchor="w", padx=12, pady=(0, 2))

        if presentacion:
            ctk.CTkLabel(card, text=presentacion, font=ctk.CTkFont(size=10),
                         text_color="#94A3B8", anchor="w",
                         ).pack(anchor="w", padx=12, pady=(0, 2))

        # Fila: precio · categoría · stock · badges
        bot = ctk.CTkFrame(card, fg_color="transparent")
        bot.pack(fill="x", padx=12, pady=(2, 10))

        ctk.CTkLabel(bot, text=f"${precio_venta:.2f}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color="#2563EB").pack(side="left")

        if categoria:
            ctk.CTkLabel(bot, text=f"  {categoria}",
                         font=ctk.CTkFont(size=10), text_color="#64748B").pack(side="left")

        stock_color = "#DC2626" if stock_actual <= 0 else ("#F59E0B" if stock_actual <= 5 else "#16A34A")
        stock_bg    = "#FEE2E2" if stock_actual <= 0 else ("#FEF9C3" if stock_actual <= 5 else "#DCFCE7")
        sb = ctk.CTkFrame(bot, corner_radius=6, fg_color=stock_bg)
        sb.pack(side="left", padx=(8, 0))
        ctk.CTkLabel(sb, text=f"  Stock: {stock_actual}  ",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=stock_color).pack()

        if req_receta:
            rb = ctk.CTkFrame(bot, corner_radius=6, fg_color="#FEF3C7")
            rb.pack(side="left", padx=(4, 0))
            ctk.CTkLabel(rb, text="  Receta  ",
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color="#B45309").pack()

        if controlada:
            cb = ctk.CTkFrame(bot, corner_radius=6, fg_color="#FEE2E2")
            cb.pack(side="left", padx=(4, 0))
            ctk.CTkLabel(cb, text="  Controlada  ",
                         font=ctk.CTkFont(size=9, weight="bold"),
                         text_color="#DC2626").pack()

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="x", padx=24, pady=12)
        frame.grid_columnconfigure(1, weight=1)

        fields = [
            ("Cantidad a ingresar:*", "cantidad"),
            ("N° de Lote:", "numero_lote"),
            ("Vencimiento (MM/AAAA):", "fecha_vencimiento"),
            ("Precio de Compra:", "precio_compra"),
        ]
        _placeholders = {"fecha_vencimiento": "06/2027"}
        self.entries = {}
        for i, (label, key) in enumerate(fields):
            ctk.CTkLabel(frame, text=label, font=ctk.CTkFont(size=12), anchor="e").grid(
                row=i, column=0, padx=(0, 8), pady=6, sticky="e")
            e = ctk.CTkEntry(frame, height=34, placeholder_text=_placeholders.get(key, ""))
            e.grid(row=i, column=1, pady=6, sticky="ew")
            self.entries[key] = e

        ctk.CTkButton(self, text="✅ Registrar Entrada", height=42,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._guardar).pack(fill="x", padx=24, pady=12)

    def _guardar(self):
        try:
            cantidad = int(self.entries["cantidad"].get().strip())
            if cantidad <= 0:
                raise ValueError("Cantidad debe ser positiva")
        except ValueError as e:
            messagebox.showwarning("Error", f"Cantidad inválida: {e}")
            return

        fecha_str = self.entries["fecha_vencimiento"].get().strip()
        fecha_venc = None
        if fecha_str:
            import calendar as _cal
            from datetime import datetime as _dt
            parsed = None
            for fmt in ("%m/%Y", "%d/%m/%Y", "%Y-%m-%d"):
                try:
                    parsed = _dt.strptime(fecha_str, fmt)
                    break
                except ValueError:
                    continue
            if not parsed:
                messagebox.showwarning("Error", "Formato de fecha incorrecto (MM/AAAA, ej: 06/2027)")
                return
            if fmt == "%m/%Y":
                last = _cal.monthrange(parsed.year, parsed.month)[1]
                fecha_venc = date(parsed.year, parsed.month, last)
            else:
                fecha_venc = parsed.date()

        db = get_db_session()
        try:
            prod = db.query(Producto).filter(Producto.id == self.producto_id).first()
            stock_ant = prod.stock
            prod.stock += cantidad

            lote = Lote(
                producto_id=self.producto_id,
                numero_lote=self.entries["numero_lote"].get().strip() or None,
                fecha_vencimiento=fecha_venc,
                cantidad=cantidad,
                precio_compra=float(self.entries["precio_compra"].get().strip() or "0"),
            )
            db.add(lote)

            mov = MovimientoStock(
                producto_id=self.producto_id,
                tipo=TipoMovimiento.entrada,
                cantidad=cantidad,
                stock_anterior=stock_ant,
                stock_nuevo=prod.stock,
                usuario_id=self.usuario_id,
                notas=f"Lote: {lote.numero_lote or 'S/N'}",
            )
            db.add(mov)
            db.commit()

            registrar_accion("ENTRADA_STOCK", "productos", self.producto_id,
                             f"Cantidad:{cantidad} Lote:{lote.numero_lote}")
            if self.on_save:
                self.on_save()
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()


class LotesDialog(ctk.CTkToplevel):
    """Lotes de un producto — número, fecha vencimiento, cantidad, días restantes"""
    def __init__(self, parent, producto_id: int):
        super().__init__(parent)
        self.producto_id = producto_id
        self.title("Lotes del Producto")
        self.geometry("660x480")
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        db = get_db_session()
        try:
            prod = db.query(Producto).filter(Producto.id == self.producto_id).first()
            nombre = prod.nombre if prod else "?"
        finally:
            db.close()

        ctk.CTkLabel(self, text=f"🗓 Lotes: {nombre}",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     wraplength=620).pack(pady=(16, 10), padx=16)

        frame = ctk.CTkFrame(self, corner_radius=8)
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        cols = ("lote", "vencimiento", "cantidad", "dias", "estado")
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", style="Inv.Treeview")
        for col, heading, width in [
            ("lote",        "Nº Lote",          150),
            ("vencimiento", "Fecha Vencimiento", 145),
            ("cantidad",    "Cantidad",           90),
            ("dias",        "Días Restantes",    120),
            ("estado",      "Estado",            120),
        ]:
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, anchor="center")

        self.tree.tag_configure("vencido",    foreground="#DC2626", background="#FEF2F2")
        self.tree.tag_configure("por_vencer", foreground="#D97706", background="#FFFBEB")
        self.tree.tag_configure("ok",         foreground="#16A34A")

        scroll_y = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")

        self._load()

    def _load(self):
        hoy = date.today()
        alerta = hoy + timedelta(days=cfg.EXPIRY_ALERT_DAYS)

        db = get_db_session()
        try:
            lotes = (db.query(Lote)
                     .filter(Lote.producto_id == self.producto_id)
                     .order_by(Lote.fecha_vencimiento)
                     .all())
            for lote in lotes:
                fv = lote.fecha_vencimiento
                if fv:
                    dias = (fv - hoy).days
                    fv_str = fv.strftime("%d/%m/%Y")
                    dias_str = str(dias) if dias >= 0 else f"Hace {-dias}"
                    if fv <= hoy:
                        tag = "vencido";    estado = "⛔ Vencido"
                    elif fv <= alerta:
                        tag = "por_vencer"; estado = "⚠ Por vencer"
                    else:
                        tag = "ok";         estado = "✓ Vigente"
                else:
                    fv_str = "Sin fecha"; dias_str = "-"; tag = "ok"; estado = "Sin fecha"

                self.tree.insert("", "end", values=(
                    lote.numero_lote or "S/N",
                    fv_str,
                    lote.cantidad,
                    dias_str,
                    estado,
                ), tags=(tag,))
        finally:
            db.close()

