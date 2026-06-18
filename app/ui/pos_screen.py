import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
from datetime import datetime
from app.database.connection import get_db_session
from app.database.models import (
    Producto, Venta, ItemVenta, Cliente, CortesCaja,
    MovimientoStock, TipoMovimiento, MetodoPago, EstadoVenta
)
from app.services.printer_service import printer_service
from app.auth.auth_service import registrar_accion
import app.config as cfg

# ── Paleta ────────────────────────────────────────────────────────────────────
BLUE      = "#2563EB"
BLUE_D    = "#1D4ED8"
BLUE_L    = "#EFF6FF"
GREEN     = "#16A34A"
GREEN_D   = "#15803D"
GREEN_L   = "#DCFCE7"
RED       = "#DC2626"
RED_L     = "#FEE2E2"
WHITE     = "#FFFFFF"
SURF      = "#F8FAFF"
CONT      = "#F0F4F8"
BORDER    = "#E2E8F0"
TEXT      = "#0F172A"
MUTED     = "#64748B"
MUTED_L   = "#94A3B8"


def _style_tree():
    style = ttk.Style()
    style.theme_use("clam")
    style.configure("Cart.Treeview",
                    background=WHITE, foreground=TEXT,
                    rowheight=34, fieldbackground=WHITE,
                    borderwidth=0, font=("Segoe UI", 11))
    style.configure("Cart.Treeview.Heading",
                    background="#F1F5F9", foreground=MUTED,
                    relief="flat", font=("Segoe UI", 11, "bold"), padding=(6, 6))
    style.map("Cart.Treeview",
              background=[("selected", BLUE_L)],
              foreground=[("selected", BLUE)])
    style.layout("Cart.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])


class PosScreen(ctk.CTkFrame):
    def __init__(self, parent, user, on_unknown_barcode=None):
        super().__init__(parent, corner_radius=0, fg_color=CONT)
        self.user = user
        self.on_unknown_barcode = on_unknown_barcode
        self.cart: list[dict] = []
        self.descuento_total = 0.0
        self.cliente_seleccionado = None
        _style_tree()
        self._build_ui()
        self._check_corte_caja()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=6)
        self.grid_columnconfigure(1, weight=4)
        self.grid_rowconfigure(0, weight=1)
        self._build_left_panel()
        self._build_right_panel()

    # ── Panel Izquierdo ───────────────────────────────────────────────────────

    def _build_left_panel(self):
        left = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        # Barra de búsqueda
        hdr = ctk.CTkFrame(left, corner_radius=12, fg_color=WHITE,
                           border_width=1, border_color=BORDER)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hdr.grid_columnconfigure(1, weight=1)

        # Icono + título
        title_box = ctk.CTkFrame(hdr, fg_color="transparent")
        title_box.grid(row=0, column=0, padx=(14, 8), pady=12)
        ctk.CTkLabel(title_box, text="🛒",
                     font=ctk.CTkFont(size=20)).pack(side="left")
        ctk.CTkLabel(title_box, text="Punto de Venta",
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=TEXT).pack(side="left", padx=(6, 0))

        self.entry_barcode = ctk.CTkEntry(
            hdr,
            placeholder_text="[F2] Escanear código o buscar producto...",
            height=40, font=ctk.CTkFont(size=13),
            corner_radius=10, border_color=BORDER,
        )
        self.entry_barcode.grid(row=0, column=1, padx=8, pady=12, sticky="ew")
        for event in ("<Return>", "<KP_Enter>", "<Tab>"):
            self.entry_barcode.bind(event, lambda e: self._buscar_producto())
            try:
                self.entry_barcode._entry.bind(event, lambda e: self._buscar_producto())
            except Exception:
                pass

        ctk.CTkButton(
            hdr, text="Buscar F2", width=96, height=40, corner_radius=10,
            fg_color=BLUE, hover_color=BLUE_D,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._buscar_producto,
        ).grid(row=0, column=2, padx=(0, 14), pady=12)

        # Área de resultados
        self.search_frame = ctk.CTkScrollableFrame(
            left, corner_radius=12, fg_color=WHITE,
            border_width=1, border_color=BORDER, label_text=""
        )
        self.search_frame.grid(row=1, column=0, sticky="nsew")
        self.search_frame.grid_columnconfigure(0, weight=1)

        self._hint = ctk.CTkLabel(
            self.search_frame,
            text="Escanea un producto o escribe para buscar",
            text_color=MUTED_L, font=ctk.CTkFont(size=13),
        )
        self._hint.pack(pady=40)

    # ── Panel Derecho ─────────────────────────────────────────────────────────

    def _build_right_panel(self):
        right = ctk.CTkFrame(self, corner_radius=12, fg_color=WHITE,
                             border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.grid_rowconfigure(2, weight=1)   # carrito se expande
        right.grid_columnconfigure(0, weight=1)

        # ── Cabecera carrito ──────────────────────────────────────────────────
        hdr = ctk.CTkFrame(right, corner_radius=0, fg_color=BLUE, height=48)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)
        hdr.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(hdr, text="🧾  Carrito de Venta",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=WHITE).grid(row=0, column=0, padx=14, sticky="w")

        ctk.CTkButton(hdr, text="🗑", width=36, height=30,
                      fg_color="transparent", hover_color=BLUE_D, text_color=WHITE,
                      font=ctk.CTkFont(size=14),
                      command=self._limpiar_carrito,
                      ).grid(row=0, column=1, padx=(0, 10))

        # ── Cliente ───────────────────────────────────────────────────────────
        cli = ctk.CTkFrame(right, fg_color=SURF, height=38)
        cli.grid(row=1, column=0, sticky="ew")
        cli.grid_propagate(False)
        cli.grid_columnconfigure(1, weight=1)
        cli.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(cli, text="👤", font=ctk.CTkFont(size=13)).grid(
            row=0, column=0, padx=(12, 4))
        self.lbl_cliente = ctk.CTkLabel(cli, text="Público General",
                                         font=ctk.CTkFont(size=12, weight="bold"),
                                         text_color=BLUE, anchor="w")
        self.lbl_cliente.grid(row=0, column=1, sticky="w")
        ctk.CTkButton(cli, text="Cambiar F3", width=88, height=26,
                      fg_color=BLUE_L, hover_color=BORDER, text_color=BLUE,
                      font=ctk.CTkFont(size=11),
                      command=self._seleccionar_cliente,
                      ).grid(row=0, column=2, padx=(0, 10))

        # ── Tabla carrito ─────────────────────────────────────────────────────
        tree_frame = ctk.CTkFrame(right, fg_color="transparent")
        tree_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(6, 0))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        cols = ("producto", "cant", "precio", "subtotal")
        self.cart_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                       style="Cart.Treeview", selectmode="browse")
        self.cart_tree.heading("producto", text="Producto")
        self.cart_tree.heading("cant",     text="Cant.")
        self.cart_tree.heading("precio",   text="Precio")
        self.cart_tree.heading("subtotal", text="Subtotal")
        self.cart_tree.column("producto", width=160, anchor="w")
        self.cart_tree.column("cant",     width=44,  anchor="center")
        self.cart_tree.column("precio",   width=75,  anchor="e")
        self.cart_tree.column("subtotal", width=80,  anchor="e")

        self.cart_tree.tag_configure("even", background="#F8FAFF")
        self.cart_tree.tag_configure("odd",  background=WHITE)

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.cart_tree.yview)
        self.cart_tree.configure(yscrollcommand=scroll.set)
        self.cart_tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        self.cart_tree.bind("<Delete>",    lambda e: self._eliminar_item_seleccionado())
        self.cart_tree.bind("<Double-1>",  lambda e: self._editar_cantidad())
        self.cart_tree.bind("<plus>",      lambda e: self._cambiar_cantidad(+1))
        self.cart_tree.bind("<KP_Add>",    lambda e: self._cambiar_cantidad(+1))
        self.cart_tree.bind("<minus>",     lambda e: self._cambiar_cantidad(-1))
        self.cart_tree.bind("<KP_Subtract>", lambda e: self._cambiar_cantidad(-1))

        # Mini-barra acciones carrito
        act = ctk.CTkFrame(right, fg_color="transparent", height=32)
        act.grid(row=3, column=0, sticky="ew", padx=8, pady=(2, 0))
        act.grid_propagate(False)
        ctk.CTkButton(act, text="✏️ Editar cant. F4", height=28, width=148,
                      fg_color=SURF, hover_color=BORDER, text_color=MUTED,
                      font=ctk.CTkFont(size=11),
                      command=self._editar_cantidad).pack(side="left", padx=(0, 4))
        ctk.CTkButton(act, text="🗑 Quitar", height=28, width=90,
                      fg_color=RED_L, hover_color="#FECACA", text_color=RED,
                      font=ctk.CTkFont(size=11),
                      command=self._eliminar_item_seleccionado).pack(side="left")

        # ── Panel fijo inferior (totales + cobro) ─────────────────────────────
        bottom = ctk.CTkFrame(right, corner_radius=0, fg_color=SURF,
                              border_width=0)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)

        # Separador
        ctk.CTkFrame(bottom, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=0, column=0, sticky="ew")

        # Totales
        tots = ctk.CTkFrame(bottom, fg_color="transparent")
        tots.grid(row=1, column=0, sticky="ew", padx=12, pady=(10, 6))
        tots.grid_columnconfigure(1, weight=1)

        def _row_total(parent, r, label, attr, size=12, bold=False, color=TEXT):
            ctk.CTkLabel(parent, text=label,
                         font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"),
                         text_color=MUTED).grid(row=r, column=0, sticky="w", pady=1)
            lbl = ctk.CTkLabel(parent, text="$0.00",
                               font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"),
                               text_color=color, anchor="e")
            lbl.grid(row=r, column=1, sticky="e", pady=1)
            setattr(self, attr, lbl)

        _row_total(tots, 0, "Subtotal",   "lbl_subtotal")
        _row_total(tots, 1, "Descuento",  "lbl_descuento", color="#F59E0B")
        _row_total(tots, 2, "IVA (16%)", "lbl_iva")

        ctk.CTkFrame(tots, height=1, fg_color=BORDER).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=6)

        _row_total(tots, 4, "TOTAL", "lbl_total", size=17, bold=True, color=BLUE)

        # Descuento input
        desc = ctk.CTkFrame(bottom, fg_color="transparent")
        desc.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))

        ctk.CTkLabel(desc, text="Descuento $:",
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left")
        self.entry_descuento = ctk.CTkEntry(desc, width=80, height=28,
                                             placeholder_text="0.00",
                                             corner_radius=8)
        self.entry_descuento.pack(side="left", padx=6)
        self.entry_descuento.bind("<Return>", lambda e: self._actualizar_totales())
        ctk.CTkButton(desc, text="Aplicar", width=62, height=28,
                      fg_color=BORDER, hover_color="#CBD5E1", text_color=TEXT,
                      font=ctk.CTkFont(size=11),
                      command=self._actualizar_totales).pack(side="left")

        # Separador
        ctk.CTkFrame(bottom, height=1, fg_color=BORDER, corner_radius=0).grid(
            row=3, column=0, sticky="ew", padx=12)

        # Método de pago
        pago = ctk.CTkFrame(bottom, fg_color="transparent")
        pago.grid(row=4, column=0, sticky="ew", padx=12, pady=(8, 6))
        pago.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(pago, text="Método:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=0, column=0, padx=(0, 10), sticky="w")

        self._pago_map = {"💵 Efectivo": "efectivo", "💳 Tarjeta": "tarjeta"}
        self.seg_pago = ctk.CTkSegmentedButton(
            pago,
            values=list(self._pago_map.keys()),
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=BORDER,
            selected_color=BLUE,
            selected_hover_color=BLUE_D,
            unselected_color=BORDER,
            unselected_hover_color="#CBD5E1",
            text_color=WHITE,
            text_color_disabled=MUTED,
        )
        self.seg_pago.set("💵 Efectivo")
        self.seg_pago.grid(row=0, column=1, sticky="ew")

        # Monto recibido + cambio
        monto = ctk.CTkFrame(bottom, fg_color="transparent")
        monto.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 8))

        ctk.CTkLabel(monto, text="Recibido $:",
                     font=ctk.CTkFont(size=11), text_color=MUTED).pack(side="left")
        self.entry_monto = ctk.CTkEntry(monto, width=96, height=30,
                                         placeholder_text="0.00", corner_radius=8)
        self.entry_monto.pack(side="left", padx=6)
        self.entry_monto.bind("<Return>", lambda e: self._cobrar())
        self.lbl_cambio = ctk.CTkLabel(monto, text="Cambio: $0.00",
                                        font=ctk.CTkFont(size=11, weight="bold"),
                                        text_color=GREEN)
        self.lbl_cambio.pack(side="left", padx=8)

        # Botón cobrar
        ctk.CTkButton(
            bottom, text="💰   COBRAR  [F10]", height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=GREEN, hover_color=GREEN_D, corner_radius=0,
            command=self._cobrar,
        ).grid(row=6, column=0, sticky="ew")

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _buscar_producto(self):
        from app.database.models import RolUsuario
        from sqlalchemy.orm import joinedload
        query = self.entry_barcode.get().strip()
        if not query:
            return

        db = get_db_session()
        try:
            prod = db.query(Producto).options(
                joinedload(Producto.categoria)
            ).filter(
                Producto.codigo_barras == query,
                Producto.activo == True
            ).first()

            if prod:
                self._agregar_al_carrito(prod.id, prod.nombre, prod.precio_venta, prod.aplica_iva)
                self.entry_barcode.delete(0, "end")
                self._mostrar_resultados([self._prod_to_dict(prod)], agregado=True)
                return

            productos = db.query(Producto).options(
                joinedload(Producto.categoria)
            ).filter(
                Producto.activo == True,
                Producto.nombre.ilike(f"%{query}%") |
                Producto.nombre_generico.ilike(f"%{query}%")
            ).limit(20).all()

            # Admin escanea código desconocido → redirigir a inventario
            if (not productos and self.on_unknown_barcode
                    and self.user.rol == RolUsuario.admin
                    and query.replace("-", "").isdigit()):
                self.entry_barcode.delete(0, "end")
                self._limpiar_resultados()
                self.on_unknown_barcode(query)
                return

            self._mostrar_resultados([self._prod_to_dict(p) for p in productos])
        finally:
            db.close()

    def _prod_to_dict(self, p) -> dict:
        parts = [x for x in (p.presentacion, p.concentracion, p.contenido) if x]
        return {
            "id": p.id,
            "nombre": p.nombre,
            "nombre_generico": p.nombre_generico or "",
            "marca": p.marca or "",
            "precio": p.precio_venta,
            "stock": p.stock,
            "aplica_iva": p.aplica_iva,
            "presentacion": "  ·  ".join(parts),
            "categoria": p.categoria.nombre if p.categoria else "",
            "requiere_receta": p.requiere_receta,
            "sustancia_controlada": p.sustancia_controlada,
        }

    def _mostrar_resultados(self, productos: list, agregado: bool = False):
        for w in self.search_frame.winfo_children():
            w.destroy()

        if not productos:
            ctk.CTkLabel(self.search_frame, text="Sin resultados",
                         text_color=MUTED_L, font=ctk.CTkFont(size=13)).pack(pady=20)
            return

        self.search_frame.grid_columnconfigure(0, weight=1)
        for d in productos:
            pid, nombre, precio, stock, aplica_iva = (
                d["id"], d["nombre"], d["precio"], d["stock"], d["aplica_iva"]
            )
            stock_color = RED if stock <= 0 else ("#F59E0B" if stock <= 5 else GREEN)
            stock_bg    = GREEN_L if stock > 5 else ("#FEF9C3" if stock > 0 else RED_L)

            border_col = "#22C55E" if agregado else BORDER
            card = ctk.CTkFrame(self.search_frame, corner_radius=10,
                                fg_color=SURF, border_width=1,
                                border_color=border_col,
                                cursor="hand2" if not agregado else "arrow")
            card.pack(fill="x", padx=4, pady=3)
            card.grid_columnconfigure(0, weight=1)

            # ── Fila 0: nombre + badge "✓ Agregado" ──────────────────────────
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))
            top.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(top, text=nombre,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=TEXT, anchor="w",
                         ).grid(row=0, column=0, sticky="w")

            if agregado:
                badge = ctk.CTkFrame(top, corner_radius=6, fg_color=GREEN_L)
                badge.grid(row=0, column=1, padx=(8, 0), sticky="e")
                ctk.CTkLabel(badge, text="  ✓ Agregado  ",
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=GREEN).pack()

            # ── Fila 1: nombre genérico + marca ──────────────────────────────
            sub_parts = [x for x in (d["nombre_generico"], d["marca"]) if x]
            if sub_parts:
                ctk.CTkLabel(card, text="  ·  ".join(sub_parts),
                             font=ctk.CTkFont(size=11),
                             text_color=MUTED, anchor="w",
                             ).grid(row=1, column=0, padx=12, pady=(0, 2), sticky="w")

            # ── Fila 2: presentación / concentración / contenido ──────────────
            if d["presentacion"]:
                ctk.CTkLabel(card, text=d["presentacion"],
                             font=ctk.CTkFont(size=10),
                             text_color=MUTED_L, anchor="w",
                             ).grid(row=2, column=0, padx=12, pady=(0, 2), sticky="w")

            # ── Fila 3: precio · categoría · badges receta/controlada ─────────
            bot = ctk.CTkFrame(card, fg_color="transparent")
            bot.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 8))

            precio_txt = f"${precio:.2f}" + ("  +IVA" if aplica_iva else "")
            ctk.CTkLabel(bot, text=precio_txt,
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=BLUE).pack(side="left")

            if d["categoria"]:
                ctk.CTkLabel(bot, text=f"  {d['categoria']}",
                             font=ctk.CTkFont(size=10),
                             text_color=MUTED).pack(side="left")

            if d["requiere_receta"]:
                rb = ctk.CTkFrame(bot, corner_radius=6, fg_color="#FEF3C7")
                rb.pack(side="left", padx=(6, 0))
                ctk.CTkLabel(rb, text="  Receta  ",
                             font=ctk.CTkFont(size=9, weight="bold"),
                             text_color="#B45309").pack()

            if d["sustancia_controlada"]:
                cb = ctk.CTkFrame(bot, corner_radius=6, fg_color=RED_L)
                cb.pack(side="left", padx=(4, 0))
                ctk.CTkLabel(cb, text="  Controlada  ",
                             font=ctk.CTkFont(size=9, weight="bold"),
                             text_color=RED).pack()

            # stock badge (derecha)
            stock_badge = ctk.CTkFrame(bot, corner_radius=8, fg_color=stock_bg)
            stock_badge.pack(side="right")
            ctk.CTkLabel(stock_badge, text=f"  Stock: {stock}  ",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=stock_color).pack()

            if not agregado:
                def _add(p=pid, n=nombre, pr=precio, iv=aplica_iva):
                    self._agregar_al_carrito(p, n, pr, iv)
                    self._limpiar_resultados()
                    self.entry_barcode.delete(0, "end")

                card.bind("<Button-1>", lambda e, fn=_add: fn())
                for child in card.winfo_children():
                    child.bind("<Button-1>", lambda e, fn=_add: fn())
                    for grandchild in child.winfo_children():
                        grandchild.bind("<Button-1>", lambda e, fn=_add: fn())

    def _limpiar_resultados(self):
        for w in self.search_frame.winfo_children():
            w.destroy()

    def _agregar_al_carrito(self, producto_id: int, nombre: str, precio: float, aplica_iva: bool):
        for item in self.cart:
            if item["producto_id"] == producto_id:
                item["cantidad"] += 1
                item["subtotal"] = item["cantidad"] * item["precio"]
                self._refresh_cart_tree()
                self._actualizar_totales()
                self.after(50, self.entry_barcode.focus_set)
                return

        self.cart.append({
            "producto_id": producto_id,
            "nombre": nombre,
            "precio": precio,
            "aplica_iva": aplica_iva,
            "cantidad": 1,
            "subtotal": precio,
        })
        self._refresh_cart_tree()
        self._actualizar_totales()
        self.after(50, self.entry_barcode.focus_set)

    def _refresh_cart_tree(self):
        for row in self.cart_tree.get_children():
            self.cart_tree.delete(row)
        for idx, item in enumerate(self.cart):
            tag = "even" if idx % 2 == 0 else "odd"
            self.cart_tree.insert("", "end", tags=(tag,), values=(
                item["nombre"][:26],
                item["cantidad"],
                f"${item['precio']:.2f}",
                f"${item['subtotal']:.2f}",
            ))

    def _actualizar_totales(self):
        subtotal = sum(i["subtotal"] for i in self.cart)
        desc_str = self.entry_descuento.get().strip()
        try:
            self.descuento_total = float(desc_str) if desc_str else 0.0
        except ValueError:
            self.descuento_total = 0.0

        iva = sum(i["subtotal"] * cfg.TAX_RATE for i in self.cart if i["aplica_iva"])
        total = subtotal - self.descuento_total + iva

        self.lbl_subtotal.configure(text=f"${subtotal:.2f}")
        self.lbl_descuento.configure(text=f"${self.descuento_total:.2f}")
        self.lbl_iva.configure(text=f"${iva:.2f}")
        self.lbl_total.configure(text=f"${total:.2f}")

        try:
            monto = float(self.entry_monto.get().strip() or "0")
            cambio = monto - total
            self.lbl_cambio.configure(
                text=f"Cambio: ${cambio:.2f}",
                text_color=GREEN if cambio >= 0 else RED,
            )
        except ValueError:
            pass

        return subtotal, self.descuento_total, iva, total

    def _editar_cantidad(self):
        sel = self.cart_tree.selection()
        if not sel:
            return
        idx = self.cart_tree.index(sel[0])
        if idx >= len(self.cart):
            return
        item = self.cart[idx]
        dialog = ctk.CTkInputDialog(text=f"Nueva cantidad para:\n{item['nombre']}",
                                     title="Editar Cantidad")
        val = dialog.get_input()
        if val:
            try:
                qty = int(val)
                if qty <= 0:
                    self.cart.pop(idx)
                else:
                    item["cantidad"] = qty
                    item["subtotal"] = qty * item["precio"]
                self._refresh_cart_tree()
                self._actualizar_totales()
            except ValueError:
                pass

    def _cambiar_cantidad(self, delta: int):
        sel = self.cart_tree.selection()
        if not sel:
            return
        idx = self.cart_tree.index(sel[0])
        if idx >= len(self.cart):
            return
        item = self.cart[idx]
        nueva = item["cantidad"] + delta
        if nueva <= 0:
            self.cart.pop(idx)
        else:
            item["cantidad"] = nueva
            item["subtotal"] = nueva * item["precio"]
        self._refresh_cart_tree()
        self._actualizar_totales()

    def _eliminar_item_seleccionado(self):
        sel = self.cart_tree.selection()
        if not sel:
            return
        idx = self.cart_tree.index(sel[0])
        if idx < len(self.cart):
            self.cart.pop(idx)
            self._refresh_cart_tree()
            self._actualizar_totales()

    def _limpiar_carrito(self):
        if self.cart and not messagebox.askyesno("Confirmar", "¿Limpiar el carrito?"):
            return
        self.cart = []
        self.descuento_total = 0.0
        self.entry_descuento.delete(0, "end")
        self.entry_monto.delete(0, "end")
        self.cliente_seleccionado = None
        self.lbl_cliente.configure(text="Público General")
        self._refresh_cart_tree()
        self._actualizar_totales()

    def _seleccionar_cliente(self):
        win = ctk.CTkToplevel(self)
        win.title("Seleccionar Cliente")
        win.geometry("400x460")
        win.grab_set()

        ctk.CTkLabel(win, text="Buscar cliente:",
                     font=ctk.CTkFont(size=13)).pack(padx=20, pady=(16, 4), anchor="w")
        entry = ctk.CTkEntry(win, placeholder_text="Nombre o teléfono...", height=36)
        entry.pack(fill="x", padx=20, pady=(0, 10))

        frame_list = ctk.CTkScrollableFrame(win)
        frame_list.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        def buscar(event=None):
            for w in frame_list.winfo_children():
                w.destroy()
            q = entry.get().strip()
            db = get_db_session()
            try:
                clientes = db.query(Cliente).filter(
                    Cliente.activo == True,
                    Cliente.nombre.ilike(f"%{q}%") | Cliente.telefono.ilike(f"%{q}%")
                ).limit(30).all()
                for c in clientes:
                    def select(cliente=c):
                        self.cliente_seleccionado = {"id": cliente.id, "nombre": cliente.nombre}
                        self.lbl_cliente.configure(text=cliente.nombre)
                        win.destroy()
                    ctk.CTkButton(
                        frame_list,
                        text=f"{c.nombre}  |  {c.telefono or ''}",
                        anchor="w", fg_color="transparent",
                        text_color=TEXT, hover_color=BLUE_L,
                        command=select,
                    ).pack(fill="x", pady=2)
            finally:
                db.close()

        entry.bind("<KeyRelease>", buscar)
        buscar()

        ctk.CTkButton(
            win, text="Público General",
            fg_color=SURF, border_width=1, border_color=BORDER,
            text_color=MUTED, hover_color=BORDER,
            command=lambda: (
                setattr(self, "cliente_seleccionado", None),
                self.lbl_cliente.configure(text="Público General"),
                win.destroy()
            ),
        ).pack(padx=20, pady=(0, 16), fill="x")

    def _cobrar(self):
        if not self.cart:
            messagebox.showwarning("Carrito vacío", "Agrega productos antes de cobrar")
            return

        subtotal, descuento, iva, total = self._actualizar_totales()

        try:
            monto_pagado = float(self.entry_monto.get().strip() or "0")
        except ValueError:
            monto_pagado = 0.0

        metodo = self._pago_map.get(self.seg_pago.get(), "efectivo")
        if metodo == "efectivo" and monto_pagado < total:
            messagebox.showwarning("Monto insuficiente",
                                    f"Recibido (${monto_pagado:.2f}) < Total (${total:.2f})")
            return

        cambio = max(0, monto_pagado - total)
        msg = f"Total: ${total:.2f}\nMétodo: {metodo.upper()}"
        if metodo == "efectivo":
            msg += f"\nCambio: ${cambio:.2f}"
        if not messagebox.askyesno("Confirmar venta", msg):
            return

        db = get_db_session()
        try:
            now = datetime.now()
            folio = f"V{now.strftime('%Y%m%d%H%M%S%f')[:-3]}"
            venta = Venta(
                folio=folio,
                usuario_id=self.user.id,
                cliente_id=self.cliente_seleccionado["id"] if self.cliente_seleccionado else None,
                subtotal=subtotal,
                descuento=descuento,
                iva=iva,
                total=total,
                metodo_pago=MetodoPago(metodo),
                monto_pagado=monto_pagado,
                cambio=cambio,
                estado=EstadoVenta.completada,
                creado_en=now,
            )
            db.add(venta)
            db.flush()

            for item in self.cart:
                db.add(ItemVenta(
                    venta_id=venta.id,
                    producto_id=item["producto_id"],
                    cantidad=item["cantidad"],
                    precio_unitario=item["precio"],
                    subtotal=item["subtotal"],
                ))
                prod = db.query(Producto).filter(Producto.id == item["producto_id"]).first()
                if prod:
                    stock_ant = prod.stock
                    prod.stock = max(0, prod.stock - item["cantidad"])
                    db.add(MovimientoStock(
                        producto_id=prod.id,
                        tipo=TipoMovimiento.salida,
                        cantidad=item["cantidad"],
                        stock_anterior=stock_ant,
                        stock_nuevo=prod.stock,
                        referencia_id=venta.id,
                        referencia_tipo="venta",
                        usuario_id=self.user.id,
                    ))

            db.commit()

            printed = printer_service.print_receipt({
                "folio": folio, "cajero": self.user.nombre,
                "cliente": self.cliente_seleccionado["nombre"] if self.cliente_seleccionado else None,
                "items": [{"nombre": i["nombre"], "cantidad": i["cantidad"], "subtotal": i["subtotal"]} for i in self.cart],
                "subtotal": subtotal, "descuento": descuento,
                "iva": iva, "total": total,
                "metodo_pago": metodo, "monto_pagado": monto_pagado, "cambio": cambio,
            })
            registrar_accion("VENTA", "ventas", venta.id, f"Folio:{folio} Total:${total:.2f}")
            msg = f"Folio: {folio}\nCambio: ${cambio:.2f}"
            if not printed:
                msg += "\n\n⚠ Ticket no imprimió — revisa la impresora en Configuración"
            messagebox.showinfo("Venta exitosa", msg)
            self._limpiar_carrito()

        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", f"Error al procesar venta:\n{e}")
        finally:
            db.close()

    def _check_corte_caja(self):
        from datetime import date
        db = get_db_session()
        try:
            abierto = db.query(CortesCaja).filter(
                CortesCaja.usuario_id == self.user.id,
                CortesCaja.cerrado_en == None,
            ).first()
            if not abierto:
                self._abrir_corte_caja()
            elif abierto.abierto_en and abierto.abierto_en.date() < date.today():
                # Corte de día anterior sin cerrar — cierre automático silencioso
                self._auto_cerrar_corte_anterior(abierto, db)
                self._abrir_corte_caja()
        finally:
            db.close()

    def _auto_cerrar_corte_anterior(self, corte, db):
        """Cierra un corte de un día previo sin interacción del usuario."""
        try:
            ventas = (
                db.query(Venta)
                .filter(
                    Venta.usuario_id == self.user.id,
                    Venta.creado_en >= corte.abierto_en,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True),
                )
                .all()
            )
            ef = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.efectivo)
            tj = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.tarjeta)
            tr = sum(v.total for v in ventas if v.metodo_pago == MetodoPago.transferencia)
            tv = ef + tj + tr

            venta_ids = [v.id for v in ventas]
            if venta_ids:
                cost_rows = (
                    db.query(ItemVenta.cantidad, Producto.precio_compra)
                    .join(Producto, ItemVenta.producto_id == Producto.id)
                    .filter(ItemVenta.venta_id.in_(venta_ids))
                    .all()
                )
                total_costo = sum(r.cantidad * (r.precio_compra or 0.0) for r in cost_rows)
            else:
                total_costo = 0.0

            corte.cerrado_en          = corte.abierto_en.replace(hour=23, minute=59, second=59)
            corte.total_ventas        = tv
            corte.total_efectivo      = ef
            corte.total_tarjeta       = tj
            corte.total_transferencia = tr
            corte.total_costo         = total_costo
            corte.num_ventas          = len(ventas)
            corte.monto_cierre        = corte.monto_apertura + ef
            notas_prev = (corte.notas or "").strip()
            corte.notas = (notas_prev + " [Cierre automático — turno anterior]").strip()
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[Caja] Error al cerrar corte anterior: {e}")

    def _abrir_corte_caja(self):
        win = ctk.CTkToplevel(self)
        win.title("Apertura de Caja")
        win.geometry("360x270")
        win.grab_set()

        ctk.CTkLabel(win, text="💰 Apertura de Turno",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(24, 4))
        ctk.CTkLabel(win, text="Monto inicial en caja:",
                     font=ctk.CTkFont(size=13), text_color=MUTED).pack()
        entry = ctk.CTkEntry(win, placeholder_text="0.00", height=42, width=200,
                              font=ctk.CTkFont(size=14), corner_radius=10)
        entry.pack(pady=12)
        entry.insert(0, "0.00")

        def confirmar():
            try:
                monto = float(entry.get().strip())
            except ValueError:
                monto = 0.0
            db2 = get_db_session()
            try:
                db2.add(CortesCaja(usuario_id=self.user.id, monto_apertura=monto))
                db2.commit()
            finally:
                db2.close()
            win.destroy()

        ctk.CTkButton(win, text="Abrir Caja", height=44,
                      fg_color=GREEN, hover_color=GREEN_D, corner_radius=10,
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=confirmar).pack(pady=12, fill="x", padx=30)

    def on_show(self):
        self.entry_barcode.focus()
