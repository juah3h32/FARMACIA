"""
Marketing screen — PDF catálogo + Generador de imágenes promocionales
Acceso solo admin. Requiere Pillow y ReportLab.
"""
import io
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont, ImageFilter

import app.config as cfg

# ── Paleta ────────────────────────────────────────────────────────────────────
BLUE       = "#1d2140"
BLUE_D     = "#1d2140"
BLUE_L     = "#EFF6FF"
GREEN      = "#16A34A"
GREEN_L    = "#DCFCE7"
YELLOW     = "#F59E0B"
TEXT       = "#0F172A"
MUTED      = "#64748B"
BORDER     = "#E2E8F0"
CARD_BG    = "#FFFFFF"
BG         = "#F0F4F8"
WHITE      = "#FFFFFF"
RED        = "#EF4444"

# Rutas assets
_BASE            = Path(__file__).parent.parent.parent
_LOGOS           = _BASE / "assets" / "logos"
_PROMO           = _BASE / "assets" / "promo"
LOGO_PATH        = _LOGOS / "LOGO.png"
LOGO_BLANCO_PATH = _LOGOS / "BLANCO_LOGO.png"
LOGO_PROMO_PATH  = _PROMO / "espromo.webp"

# Fuentes — busca primero en carpeta bundled, luego sistema, fallback Arial
_SYS_FONTS      = Path("C:/Windows/Fonts")
_USER_FONTS     = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
_BUNDLED_FONTS  = _BASE / "Font Montserrat"

def _font_path(name: str, fallback: str) -> str | None:
    # Bundled fonts first — garantizan tipografía idéntica en cualquier PC
    p = _BUNDLED_FONTS / name
    if p.exists():
        return str(p)
    for base in (_USER_FONTS, _SYS_FONTS):
        p = base / name
        if p.exists():
            return str(p)
    for base in (_SYS_FONTS, _USER_FONTS):
        f = base / fallback
        if f.exists():
            return str(f)
    return None

FONT_BLACK  = _font_path("Montserrat-Black.ttf",     "arialbd.ttf")
FONT_BOLD   = _font_path("Montserrat-Bold.ttf",      "arialbd.ttf")
FONT_SEMI   = _font_path("Montserrat-SemiBold.ttf",  "arialbd.ttf")
FONT_REG    = _font_path("Montserrat-Regular.ttf",   "arial.ttf")
FONT_ITALIC = _font_path("Montserrat-Italic.ttf",    "ariali.ttf")


def _pil_font(path, size):
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


# ══════════════════════════════════════════════════════════════════════════════
#  MarketingScreen
# ══════════════════════════════════════════════════════════════════════════════
class MarketingScreen(ctk.CTkFrame):
    def __init__(self, parent, user):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.user = user
        self._productos = []
        self._selected_prod = None
        self._preview_img_tk = None
        self._build_ui()

    def on_show(self):
        self._cargar_productos()

    # ── Layout principal ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Tabs
        tab_bar = ctk.CTkFrame(self, fg_color=CARD_BG,
                               border_width=1, border_color=BORDER,
                               corner_radius=0)
        tab_bar.grid(row=0, column=0, sticky="ew")

        self._tab_btns = {}
        tabs = [("📄 Catálogo PDF", "pdf"), ("🎨 Imagen Promo", "promo")]
        for i, (lbl, key) in enumerate(tabs):
            b = ctk.CTkButton(
                tab_bar, text=lbl,
                width=180, height=38, corner_radius=0,
                fg_color="transparent", text_color=MUTED,
                hover_color=BLUE_L, font=ctk.CTkFont(size=13),
                command=lambda k=key: self._switch_tab(k),
            )
            b.pack(side="left", padx=(8 if i == 0 else 0, 0))
            self._tab_btns[key] = b

        self._content = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        self._content.grid(row=1, column=0, sticky="nsew")
        self._content.grid_columnconfigure(0, weight=1)
        self._content.grid_rowconfigure(0, weight=1)

        self._panels = {}
        self._panels["pdf"]   = self._build_pdf_panel(self._content)
        self._panels["promo"] = self._build_promo_panel(self._content)

        self._switch_tab("pdf")

    def _switch_tab(self, key: str):
        for k, btn in self._tab_btns.items():
            if k == key:
                btn.configure(fg_color=BLUE, text_color=WHITE)
            else:
                btn.configure(fg_color="transparent", text_color=MUTED)
        for k, panel in self._panels.items():
            if k == key:
                panel.grid(row=0, column=0, sticky="nsew")
            else:
                panel.grid_remove()

    # ══════════════════════════════════════════════════════════════════════════
    #  Panel PDF
    # ══════════════════════════════════════════════════════════════════════════

    def _build_pdf_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        # Toolbar
        tb = ctk.CTkFrame(frame, fg_color=CARD_BG,
                          border_width=1, border_color=BORDER, corner_radius=10)
        tb.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 6))
        tb.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(tb, text="Filtro:",
                     font=ctk.CTkFont(size=12), text_color=MUTED).grid(
            row=0, column=0, padx=(14, 4), pady=12)

        self._pdf_filtro = ctk.CTkOptionMenu(
            tb, values=["Todos los productos", "Solo activos", "Con stock disponible"],
            width=200, height=32, corner_radius=8,
            fg_color=BLUE_L, text_color=TEXT,
            button_color=BORDER, button_hover_color=BLUE_L,
        )
        self._pdf_filtro.grid(row=0, column=1, padx=4, pady=12)

        ctk.CTkLabel(tb, text="Ordenar:",
                     font=ctk.CTkFont(size=12), text_color=MUTED).grid(
            row=0, column=2, padx=(14, 4), pady=12)

        self._pdf_orden = ctk.CTkOptionMenu(
            tb, values=["Nombre A-Z", "Precio ↑", "Precio ↓", "Stock ↑", "Categoría"],
            width=160, height=32, corner_radius=8,
            fg_color=BLUE_L, text_color=TEXT,
            button_color=BORDER, button_hover_color=BLUE_L,
        )
        self._pdf_orden.grid(row=0, column=3, padx=4, pady=12)

        self._pdf_inc_stock   = tk.BooleanVar(value=True)
        self._pdf_inc_barcode = tk.BooleanVar(value=True)

        checks_f = ctk.CTkFrame(tb, fg_color="transparent")
        checks_f.grid(row=0, column=4, padx=14, pady=12)
        ctk.CTkCheckBox(checks_f, text="Stock", variable=self._pdf_inc_stock,
                        width=90, height=24, font=ctk.CTkFont(size=11)).pack(side="left", padx=4)
        ctk.CTkCheckBox(checks_f, text="Código", variable=self._pdf_inc_barcode,
                        width=90, height=24, font=ctk.CTkFont(size=11)).pack(side="left", padx=4)

        ctk.CTkButton(
            tb, text="📄 Generar y Guardar PDF",
            width=200, height=36, corner_radius=8,
            fg_color=BLUE, text_color=WHITE, hover_color=BLUE_D,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._generar_pdf,
        ).grid(row=0, column=5, padx=14, pady=12)

        # Preview table
        list_frame = ctk.CTkFrame(frame, fg_color=CARD_BG,
                                  border_width=1, border_color=BORDER, corner_radius=10)
        list_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        list_frame.grid_columnconfigure(0, weight=1)
        list_frame.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(list_frame, fg_color=BLUE, corner_radius=10, height=36)
        hdr.grid(row=0, column=0, sticky="ew", padx=2, pady=(2, 0))
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)
        for ci, txt in enumerate(["Nombre", "Categoría", "Precio", "Stock", "Código"]):
            ctk.CTkLabel(hdr, text=txt,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=WHITE).grid(row=0, column=ci, padx=8, pady=8, sticky="w")

        self._pdf_scroll = ctk.CTkScrollableFrame(list_frame, fg_color="transparent",
                                                   corner_radius=0)
        self._pdf_scroll.grid(row=1, column=0, sticky="nsew", padx=2, pady=2)
        self._pdf_scroll.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self._pdf_lbl_count = ctk.CTkLabel(list_frame, text="",
                                            font=ctk.CTkFont(size=10), text_color=MUTED)
        self._pdf_lbl_count.grid(row=2, column=0, padx=12, pady=4, sticky="e")

        return frame

    def _render_pdf_list(self):
        for w in self._pdf_scroll.winfo_children():
            w.destroy()

        prods = self._get_filtered_products()
        for i, p in enumerate(prods):
            bg = "#F8FAFF" if i % 2 == 0 else CARD_BG
            row_f = ctk.CTkFrame(self._pdf_scroll, fg_color=bg, corner_radius=4)
            row_f.grid(row=i, column=0, columnspan=5, sticky="ew", pady=1)
            row_f.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

            cat  = p.categoria.nombre if p.categoria else "—"
            code = p.codigo_barras or "—"
            vals = [p.nombre, cat, f"${p.precio_venta:,.2f}", str(p.stock), code]
            for ci, val in enumerate(vals):
                ctk.CTkLabel(row_f, text=val,
                             font=ctk.CTkFont(size=11), text_color=TEXT,
                             anchor="w").grid(row=0, column=ci, padx=8, pady=6, sticky="w")

        self._pdf_lbl_count.configure(text=f"{len(prods)} productos")

    def _get_filtered_products(self):
        filtro = self._pdf_filtro.get()
        orden  = self._pdf_orden.get()
        prods  = list(self._productos)
        if filtro == "Solo activos":
            prods = [p for p in prods if p.activo]
        elif filtro == "Con stock disponible":
            prods = [p for p in prods if p.activo and p.stock > 0]
        if orden == "Nombre A-Z":
            prods.sort(key=lambda p: p.nombre.lower())
        elif orden == "Precio ↑":
            prods.sort(key=lambda p: p.precio_venta)
        elif orden == "Precio ↓":
            prods.sort(key=lambda p: p.precio_venta, reverse=True)
        elif orden == "Stock ↑":
            prods.sort(key=lambda p: p.stock)
        elif orden == "Categoría":
            prods.sort(key=lambda p: (p.categoria.nombre if p.categoria else "").lower())
        return prods

    def _generar_pdf(self):
        prods = self._get_filtered_products()
        if not prods:
            messagebox.showwarning("Sin datos", "No hay productos para exportar.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            initialfile=f"Catalogo_Farmacia_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
            title="Guardar catálogo PDF",
        )
        if not path:
            return

        def _build():
            try:
                _generar_pdf_reportlab(prods, path,
                                       self._pdf_inc_stock.get(),
                                       self._pdf_inc_barcode.get())
                self.after(0, lambda: messagebox.showinfo(
                    "PDF generado", f"Catálogo guardado en:\n{path}"))
                self.after(0, lambda: os.startfile(path))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror(
                    "Error PDF", f"No se pudo generar el PDF:\n{err}"))

        threading.Thread(target=_build, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    #  Panel Promo
    # ══════════════════════════════════════════════════════════════════════════

    def _build_promo_panel(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        frame.grid_columnconfigure(0, weight=0, minsize=340)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        # ── Panel izquierdo ───────────────────────────────────────────────────
        left = ctk.CTkScrollableFrame(frame, fg_color=CARD_BG,
                                       corner_radius=10,
                                       border_width=1, border_color=BORDER,
                                       width=320)
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 6), pady=14)
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="🎨 Configurar Promoción",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=TEXT).grid(row=0, column=0, pady=(12, 4), padx=12, sticky="w")

        # Búsqueda
        ctk.CTkLabel(left, text="Buscar producto:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=1, column=0, padx=12, pady=(8, 2), sticky="w")

        self._promo_search = ctk.CTkEntry(left, placeholder_text="Nombre o código...",
                                           height=34)
        self._promo_search.grid(row=2, column=0, padx=12, pady=(0, 4), sticky="ew")
        self._promo_search.bind("<KeyRelease>", self._filtrar_lista_promo)

        self._promo_listbox_frame = ctk.CTkScrollableFrame(left, height=130,
                                                            fg_color="#F8FAFF",
                                                            corner_radius=8)
        self._promo_listbox_frame.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")
        self._promo_listbox_frame.grid_columnconfigure(0, weight=1)

        # Producto seleccionado
        self._promo_prod_lbl = ctk.CTkLabel(left, text="Ningún producto seleccionado",
                                             font=ctk.CTkFont(size=11),
                                             text_color=MUTED, wraplength=280)
        self._promo_prod_lbl.grid(row=4, column=0, padx=12, pady=4, sticky="w")

        # Estado imagen Cloudinary
        self._promo_img_status = ctk.CTkLabel(left, text="",
                                               font=ctk.CTkFont(size=10),
                                               text_color=MUTED)
        self._promo_img_status.grid(row=5, column=0, padx=12, pady=(0, 2), sticky="w")

        # Toggle layout
        self._usar_imagen_var = tk.BooleanVar(value=False)
        self._chk_usar_imagen = ctk.CTkCheckBox(
            left,
            text="Usar imagen del producto (fondo blanco)",
            variable=self._usar_imagen_var,
            width=280, height=28,
            font=ctk.CTkFont(size=11),
            state="disabled",
        )
        self._chk_usar_imagen.grid(row=6, column=0, padx=12, pady=(0, 4), sticky="w")

        # Separador
        ctk.CTkFrame(left, height=1, fg_color=BORDER).grid(
            row=7, column=0, sticky="ew", padx=12, pady=8)

        # Precio actual
        ctk.CTkLabel(left, text="Precio actual:",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=8, column=0, padx=12, pady=(4, 0), sticky="w")

        self._promo_precio_actual = ctk.CTkLabel(left, text="$0.00",
                                                  font=ctk.CTkFont(size=18, weight="bold"),
                                                  text_color=BLUE)
        self._promo_precio_actual.grid(row=9, column=0, padx=12, pady=(0, 8), sticky="w")

        # Precio promo
        ctk.CTkLabel(left, text="Precio PROMO (el que vendes):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=10, column=0, padx=12, pady=(4, 0), sticky="w")

        self._promo_precio_promo_var = tk.StringVar()
        ctk.CTkEntry(
            left, textvariable=self._promo_precio_promo_var,
            height=36, font=ctk.CTkFont(size=14, weight="bold"),
            placeholder_text="Ej: 18.00",
        ).grid(row=11, column=0, padx=12, pady=(0, 4), sticky="ew")
        self._promo_precio_promo_var.trace_add("write", self._auto_update_tachado)

        # Precio tachado
        ctk.CTkLabel(left, text="Precio tachado (precio 'antes'):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=12, column=0, padx=12, pady=(4, 0), sticky="w")

        hint_f = ctk.CTkFrame(left, fg_color="transparent")
        hint_f.grid(row=13, column=0, padx=12, pady=(0, 2), sticky="ew")
        hint_f.grid_columnconfigure(0, weight=1)

        self._promo_precio_tachado_var = tk.StringVar()
        ctk.CTkEntry(
            hint_f, textvariable=self._promo_precio_tachado_var,
            height=34, font=ctk.CTkFont(size=13),
            placeholder_text="Auto: precio promo + 5",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(hint_f, text="(auto = precio promo + $5)",
                     font=ctk.CTkFont(size=9), text_color=MUTED).grid(
            row=1, column=0, sticky="w")

        # Día del badge
        ctk.CTkLabel(left, text="Día del badge (opcional):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=14, column=0, padx=12, pady=(8, 0), sticky="w")

        self._dia_oferta_var = tk.StringVar(value="")
        ctk.CTkOptionMenu(
            left,
            values=["", "Lunes", "Martes", "Miércoles", "Jueves",
                    "Viernes", "Sábado", "Domingo"],
            variable=self._dia_oferta_var,
            width=180, height=30, corner_radius=8,
            fg_color=BLUE_L, text_color=TEXT,
            button_color=BORDER, button_hover_color=BLUE_L,
        ).grid(row=15, column=0, padx=12, pady=(2, 0), sticky="w")
        ctk.CTkLabel(left, text="Aparece en el badge rojo de la imagen",
                     font=ctk.CTkFont(size=9), text_color=MUTED).grid(
            row=16, column=0, padx=12, pady=(1, 4), sticky="w")

        # IA descripción
        self._desc_ia = ""
        ia_f = ctk.CTkFrame(left, fg_color="transparent")
        ia_f.grid(row=17, column=0, padx=12, pady=(4, 2), sticky="ew")
        ia_f.grid_columnconfigure(1, weight=1)
        self._btn_ia = ctk.CTkButton(
            ia_f, text="🤖 IA", width=64, height=30, corner_radius=8,
            fg_color=BLUE, text_color=WHITE, hover_color=BLUE_D,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self._generar_desc_ia,
        )
        self._btn_ia.grid(row=0, column=0, sticky="w")
        self._lbl_desc_ia = ctk.CTkLabel(
            ia_f, text="— sin descripción",
            font=ctk.CTkFont(size=10), text_color=MUTED,
            anchor="w", wraplength=210,
        )
        self._lbl_desc_ia.grid(row=0, column=1, padx=(8, 0), sticky="ew")

        # Texto extra
        ctk.CTkLabel(left, text="Texto adicional (opcional):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=18, column=0, padx=12, pady=(8, 0), sticky="w")

        self._promo_texto_extra = ctk.CTkEntry(left, height=34,
                                                placeholder_text="Ej: Por tiempo limitado")
        self._promo_texto_extra.grid(row=19, column=0, padx=12, pady=(0, 8), sticky="ew")

        # Separador
        ctk.CTkFrame(left, height=1, fg_color=BORDER).grid(
            row=20, column=0, sticky="ew", padx=12, pady=8)

        # Botones
        ctk.CTkButton(
            left, text="👁 Vista previa",
            height=36, corner_radius=8,
            fg_color=GREEN, text_color=WHITE, hover_color="#15803D",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._preview_promo,
        ).grid(row=21, column=0, padx=12, pady=(0, 6), sticky="ew")

        ctk.CTkButton(
            left, text="💾 Guardar imagen PNG",
            height=36, corner_radius=8,
            fg_color=BLUE, text_color=WHITE, hover_color=BLUE_D,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._guardar_promo,
        ).grid(row=22, column=0, padx=12, pady=(0, 12), sticky="ew")

        # ── Panel derecho (preview) ───────────────────────────────────────────
        right = ctk.CTkFrame(frame, fg_color=CARD_BG,
                              corner_radius=10,
                              border_width=1, border_color=BORDER)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 14), pady=14)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(right, text="Vista previa",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=MUTED).grid(row=0, column=0, pady=(12, 4))

        self._preview_lbl = ctk.CTkLabel(right, text="", image=None)
        self._preview_lbl.grid(row=1, column=0, padx=12, pady=12)

        self._preview_placeholder = ctk.CTkLabel(
            right,
            text="Selecciona un producto\ny pulsa Vista previa",
            font=ctk.CTkFont(size=13), text_color=MUTED,
        )
        self._preview_placeholder.grid(row=1, column=0)

        return frame

    # ── Lógica promo ──────────────────────────────────────────────────────────

    def _filtrar_lista_promo(self, *_):
        term = self._promo_search.get().lower().strip()
        for w in self._promo_listbox_frame.winfo_children():
            w.destroy()
        matches = [p for p in self._productos
                   if term in p.nombre.lower()
                   or term in (p.codigo_barras or "").lower()][:20]
        for i, p in enumerate(matches):
            has_img = bool(p.imagen_url)
            suffix  = " 🖼" if has_img else ""
            btn = ctk.CTkButton(
                self._promo_listbox_frame,
                text=f"{p.nombre}{suffix}  ${p.precio_venta:,.2f}",
                anchor="w", height=30, corner_radius=6,
                fg_color="transparent", text_color=TEXT,
                hover_color=BLUE_L, font=ctk.CTkFont(size=11),
                command=lambda prod=p: self._seleccionar_producto_promo(prod),
            )
            btn.grid(row=i, column=0, sticky="ew", pady=1)

    def _seleccionar_producto_promo(self, prod):
        self._selected_prod = prod
        cat = prod.categoria.nombre if prod.categoria else ""
        self._promo_prod_lbl.configure(
            text=f"✓ {prod.nombre}" + (f" | {cat}" if cat else ""),
            text_color=GREEN,
        )
        self._promo_precio_actual.configure(text=f"${prod.precio_venta:,.2f}")
        self._promo_precio_promo_var.set(f"{prod.precio_venta:.2f}")
        self._promo_precio_tachado_var.set(f"{prod.precio_venta + 5:.2f}")

        # Imagen Cloudinary
        if prod.imagen_url:
            self._promo_img_status.configure(
                text="🖼 Tiene imagen en Cloudinary", text_color=GREEN)
            self._chk_usar_imagen.configure(state="normal")
            self._usar_imagen_var.set(True)
        else:
            self._promo_img_status.configure(
                text="Sin imagen — solo diseño azul disponible", text_color=MUTED)
            self._chk_usar_imagen.configure(state="disabled")
            self._usar_imagen_var.set(False)

        self._desc_ia = ""
        if hasattr(self, "_lbl_desc_ia"):
            self._lbl_desc_ia.configure(text="— sin descripción", text_color=MUTED)
        self._promo_search.delete(0, "end")
        for w in self._promo_listbox_frame.winfo_children():
            w.destroy()

    def _auto_update_tachado(self, *_):
        try:
            promo = float(self._promo_precio_promo_var.get())
            if not self._promo_precio_tachado_var.get():
                self._promo_precio_tachado_var.set(f"{promo + 5:.2f}")
        except (ValueError, TypeError):
            pass

    def _get_promo_params(self):
        if not self._selected_prod:
            messagebox.showwarning("Sin producto", "Selecciona un producto primero.")
            return None
        try:
            precio_promo = float(self._promo_precio_promo_var.get() or 0)
        except ValueError:
            messagebox.showerror("Error", "Precio promo inválido.")
            return None
        try:
            t = self._promo_precio_tachado_var.get().strip()
            precio_tachado = float(t) if t else precio_promo + 5
        except ValueError:
            precio_tachado = precio_promo + 5

        return {
            "producto":          self._selected_prod,
            "precio_promo":      precio_promo,
            "precio_tachado":    precio_tachado,
            "texto_extra":       self._promo_texto_extra.get().strip(),
            "usar_imagen":       self._usar_imagen_var.get() and bool(self._selected_prod.imagen_url),
            "dia_oferta":        self._dia_oferta_var.get().strip() if hasattr(self, "_dia_oferta_var") else "",
            "descripcion_promo": self._desc_ia,
        }

    def _preview_promo(self):
        params = self._get_promo_params()
        if not params:
            return

        def _build():
            try:
                img = _generar_imagen_promo(**params)
                thumb = img.copy()
                thumb.thumbnail((460, 460), Image.LANCZOS)
                tk_img = ctk.CTkImage(light_image=thumb, dark_image=thumb,
                                       size=(thumb.width, thumb.height))
                def _apply():
                    self._preview_img_tk = tk_img
                    self._preview_placeholder.grid_remove()
                    self._preview_lbl.configure(image=tk_img)
                    self._preview_lbl.image = tk_img
                self.after(0, _apply)
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror(
                    "Error preview", err))

        threading.Thread(target=_build, daemon=True).start()

    def _guardar_promo(self):
        params = self._get_promo_params()
        if not params:
            return
        nombre = params["producto"].nombre[:30].replace(" ", "_")
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")],
            initialfile=f"Promo_{nombre}_{datetime.now().strftime('%Y%m%d_%H%M')}.png",
            title="Guardar imagen promo",
        )
        if not path:
            return

        def _build():
            try:
                img = _generar_imagen_promo(**params)
                img.save(path, "PNG", optimize=True)
                self.after(0, lambda: messagebox.showinfo(
                    "Imagen guardada", f"Imagen lista para compartir:\n{path}"))
                self.after(0, lambda: os.startfile(path))
            except Exception as e:
                self.after(0, lambda err=str(e): messagebox.showerror(
                    "Error imagen", f"No se pudo guardar:\n{err}"))

        threading.Thread(target=_build, daemon=True).start()

    # ── IA descripción ────────────────────────────────────────────────────────

    def _generar_desc_ia(self):
        if not self._selected_prod:
            messagebox.showwarning("Sin producto", "Selecciona un producto primero.")
            return
        import app.config as _cfg
        key = _cfg.OPENAI_API_KEY
        if not key:
            self._pedir_openai_key(on_key=self._generar_desc_ia)
            return

        prod = self._selected_prod
        self._btn_ia.configure(state="disabled", text="⏳")
        self._lbl_desc_ia.configure(text="Generando...", text_color=MUTED)

        def _run():
            try:
                from openai import OpenAI
                client = OpenAI(api_key=key)
                partes = [f"Medicamento: {prod.nombre}"]
                if getattr(prod, "nombre_generico", None):
                    partes.append(f"Genérico: {prod.nombre_generico}")
                if getattr(prod, "marca", None):
                    partes.append(f"Marca: {prod.marca}")
                if getattr(prod, "presentacion", None):
                    partes.append(f"Presentación: {prod.presentacion}")
                if getattr(prod, "concentracion", None):
                    partes.append(f"Concentración: {prod.concentracion}")
                prompt = (
                    "Genera descripción farmacéutica breve y precisa. "
                    "Incluye indicaciones principales y advertencia clave. "
                    "Español profesional. Máx 300 caracteres. Sin títulos, texto corrido, oración completa.\n\n"
                    + "\n".join(partes) + "\n\nDescripción:"
                )
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                texto = (resp.choices[0].message.content or "").strip()
                if len(texto) > 300:
                    chunk = texto[:300]
                    cut = max(chunk.rfind(". "), chunk.rfind("! "), chunk.rfind("? "))
                    texto = chunk[:cut + 1].strip() if cut > 80 else chunk.rsplit(" ", 1)[0] + "."
                self._desc_ia = texto
                preview = (texto[:55] + "…") if len(texto) > 55 else texto
                self.after(0, lambda: self._lbl_desc_ia.configure(text=preview, text_color="#16A34A"))
            except Exception as exc:
                msg = str(exc)
                if "429" in msg or "quota" in msg.lower() or "billing" in msg.lower():
                    err = "Sin créditos OpenAI. Recarga en platform.openai.com/billing"
                elif "api_key" in msg.lower() or "authentication" in msg.lower():
                    err = "Clave API inválida"
                else:
                    err = f"Error: {msg[:50]}"
                self._desc_ia = ""
                self.after(0, lambda e=err: self._lbl_desc_ia.configure(text=e, text_color="#EF4444"))
            finally:
                self.after(0, lambda: self._btn_ia.configure(state="normal", text="🤖 IA"))

        threading.Thread(target=_run, daemon=True, name="IADescGen").start()

    def _pedir_openai_key(self, on_key=None):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Configurar clave OpenAI")
        dlg.geometry("460x240")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width()  - 460) // 2
        y = self.winfo_rooty() + (self.winfo_height() - 240) // 2
        dlg.geometry(f"460x240+{x}+{y}")

        ctk.CTkLabel(dlg, text="🔑 Clave API de OpenAI",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(18, 4))
        ctk.CTkLabel(dlg,
                     text="Necesaria para generar descripciones con IA.\n"
                          "Obtén tu clave en platform.openai.com/api-keys",
                     font=ctk.CTkFont(size=11), text_color=MUTED,
                     justify="center").pack(pady=(0, 10))

        entry = ctk.CTkEntry(dlg, width=380, height=36, placeholder_text="sk-...")
        entry.pack(pady=(0, 4))
        entry.focus()

        lbl_err = ctk.CTkLabel(dlg, text="", text_color="#EF4444",
                               font=ctk.CTkFont(size=11))
        lbl_err.pack(pady=(0, 6))

        def _guardar(event=None):
            k = entry.get().strip()
            if not k.startswith("sk-") or len(k) < 20:
                lbl_err.configure(text="Clave inválida (debe empezar con sk-)")
                return
            import app.config as _cfg
            key_file = _cfg.DATA_DIR / "openai.key"
            key_file.write_text(k, encoding="utf-8")
            _cfg.OPENAI_API_KEY = k
            dlg.destroy()
            if on_key:
                self.after(100, on_key)

        entry.bind("<Return>", _guardar)
        bf = ctk.CTkFrame(dlg, fg_color="transparent")
        bf.pack()
        ctk.CTkButton(bf, text="Guardar", width=120, height=34,
                      fg_color="#2563EB", hover_color="#1D4ED8", text_color="white",
                      command=_guardar).pack(side="left", padx=4)
        ctk.CTkButton(bf, text="Cancelar", width=100, height=34,
                      fg_color="transparent", border_width=1, border_color=BORDER,
                      text_color=MUTED, command=dlg.destroy).pack(side="left", padx=4)

    # ── Carga de datos ─────────────────────────────────────────────────────────

    def _cargar_productos(self):
        def fetch():
            try:
                from app.database.connection import get_db
                from app.database.models import Producto
                with get_db() as db:
                    return db.query(Producto).filter(
                        Producto.activo.is_(True)
                    ).order_by(Producto.nombre).all()
            except Exception:
                return []

        def run():
            data = fetch()
            self.after(0, lambda: self._apply_productos(data))

        threading.Thread(target=run, daemon=True).start()

    def _apply_productos(self, prods):
        self._productos = prods
        self._render_pdf_list()


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers imagen
# ══════════════════════════════════════════════════════════════════════════════

def _hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _draw_rounded_rect(draw, x0, y0, x1, y1, radius=20, fill=None, outline=None, width=2):
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                            fill=fill, outline=outline, width=width)


def _fetch_cloudinary_image(url: str) -> Image.Image | None:
    try:
        import requests
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    """Recorta imagen en círculo y la escala al tamaño dado."""
    img = img.convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, (0, 0), mask)
    return result


def _rounded_crop(img: Image.Image, w: int, h: int, radius: int = 32) -> Image.Image:
    """Recorta imagen con esquinas redondeadas."""
    img = img.convert("RGBA")
    # Calcular crop cuadrado centrado antes de escalar
    iw, ih = img.size
    if iw / ih > w / h:
        new_w = int(ih * w / h)
        left = (iw - new_w) // 2
        img = img.crop((left, 0, left + new_w, ih))
    else:
        new_h = int(iw * h / w)
        top = (ih - new_h) // 2
        img = img.crop((0, top, iw, top + new_h))
    img = img.resize((w, h), Image.LANCZOS)

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(img, (0, 0), mask)
    return result


def _wrap_name(text: str, max_chars: int) -> list:
    """Wrap product name by char count (legacy — only used by layout_azul)."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= max_chars:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text[:max_chars]]


def _fit_name(draw, text: str, font_path, max_w: int,
              base_size: int = 58, min_size: int = 26, max_lines: int = 3):
    """Wrap text to fit max_w pixels, auto-shrink font until all lines fit."""
    for size in range(base_size, min_size - 1, -4):
        f = _pil_font(font_path, size)
        words = text.split()
        lines: list[str] = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip() if cur else w
            if draw.textlength(test, font=f) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        if (len(lines) <= max_lines
                and all(draw.textlength(ln, font=f) <= max_w for ln in lines)):
            return lines, f
    f = _pil_font(font_path, min_size)
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip() if cur else w
        if draw.textlength(test, font=f) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:max_lines], f


def _load_logo_pil() -> Image.Image | None:
    """Carga LOGO_PROMO.svg (via svglib) o fallback a PNGs."""
    for p in (LOGO_PROMO_PATH, LOGO_BLANCO_PATH, LOGO_PATH):
        if p.exists():
            try:
                return Image.open(p).convert("RGBA")
            except Exception:
                pass
    return None


def _paste_logo(img: Image.Image, draw: ImageDraw.ImageDraw,
                x1: int, y1: int, x2: int, y2: int,
                white: bool = True) -> int:
    """Paste logo centered inside (x1,y1)-(x2,y2). Returns bottom y of logo."""
    W_box, H_box = x2 - x1, y2 - y1
    logo_src = _load_logo_pil()
    if logo_src is not None:
        try:
            rw = (W_box * 0.82) / logo_src.width
            rh = (H_box * 0.82) / logo_src.height
            r  = min(rw, rh)
            logo = logo_src.resize((int(logo_src.width * r), int(logo_src.height * r)), Image.LANCZOS)
            lx = x1 + (W_box - logo.width) // 2
            ly = y1 + (H_box - logo.height) // 2
            img.paste(logo, (lx, ly), logo.split()[3])
            return ly + logo.height
        except Exception:
            pass
    fill = (255, 255, 255) if white else (37, 99, 235)
    draw.text(((x1 + x2) // 2, (y1 + y2) // 2), cfg.PHARMACY_NAME,
              font=_pil_font(FONT_BOLD, 28), fill=fill, anchor="mm")
    return y2


# ══════════════════════════════════════════════════════════════════════════════
#  Dispatcher principal
# ══════════════════════════════════════════════════════════════════════════════

def _generar_imagen_promo(producto, precio_promo: float,
                           precio_tachado: float, texto_extra: str = "",
                           usar_imagen: bool = False,
                           dia_oferta: str = "",
                           descripcion_promo: str = "") -> Image.Image:
    prod_img = None
    if usar_imagen and producto.imagen_url:
        prod_img = _fetch_cloudinary_image(producto.imagen_url)

    # Siempre usa layout blanco — con foto si hay, sin foto el lado derecho queda blanco
    return _layout_blanco(
        producto, precio_promo, precio_tachado, texto_extra,
        prod_img, dia_oferta, descripcion_promo,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  Layout A — Fondo AZUL (sin imagen producto)  ·  estilo farmacia moderno
# ══════════════════════════════════════════════════════════════════════════════

def _layout_azul(producto, precio_promo: float,
                  precio_tachado: float, texto_extra: str) -> Image.Image:
    W, H = 1080, 1080
    NAVY   = (8,  18, 65)
    BLUE   = (21, 74, 190)
    GOLD   = (252, 211, 77)
    AMBER  = (220, 165, 20)
    WHITE  = (255, 255, 255)
    SILVER = (160, 190, 230)
    RED    = (220, 55, 55)
    DARK   = (5,  12, 42)

    img  = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)

    # Background gradient: deep navy → brand blue
    for y in range(H):
        t = y / H
        r = int(NAVY[0] + (BLUE[0] - NAVY[0]) * t)
        g = int(NAVY[1] + (BLUE[1] - NAVY[1]) * t)
        b = int(NAVY[2] + (BLUE[2] - NAVY[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # ── Diagonal gold accent strip (right edge) ───────────────────────────────
    for dx, col in [
        (0,   (130, 95, 5)),
        (50,  (170, 125, 12)),
        (110, (210, 158, 18)),
        (180, AMBER),
        (260, GOLD),
        (340, (255, 232, 115)),
    ]:
        draw.polygon(
            [(W - 390 + dx, 0), (W, 0), (W, H), (W - 260 + dx, H)],
            fill=col,
        )

    # Pharmacy cross inside gold strip
    cx_, cy_ = W - 105, H // 2 - 30
    cs, ct = 48, 14
    draw.rounded_rectangle([cx_ - ct, cy_ - cs, cx_ + ct, cy_ + cs], radius=5, fill=WHITE)
    draw.rounded_rectangle([cx_ - cs, cy_ - ct, cx_ + cs, cy_ + ct], radius=5, fill=WHITE)

    # ── Decorative ring outlines ──────────────────────────────────────────────
    draw.ellipse([-150, -150, 330, 330], outline=(40, 75, 175), width=4)
    draw.ellipse([-75,  -75,  195, 195], outline=(50, 90, 190), width=2)
    draw.ellipse([40, H - 230, 188, H - 82], outline=(50, 90, 190), width=2)
    draw.ellipse([W - 650, H - 610, W + 30, H + 70], outline=(40, 75, 175), width=3)

    # ── Logo (centered in content zone x=0..W-390) ───────────────────────────
    CONTENT_W = W - 390
    _paste_logo(img, draw, 0, 44, CONTENT_W, 158, white=True)

    # Separator
    draw.line([(60, 163), (CONTENT_W - 60, 163)], fill=(50, 80, 160), width=1)

    # ── OFERTA badge ──────────────────────────────────────────────────────────
    bw, bh, badge_y = 238, 48, 190
    bx = (CONTENT_W - bw) // 2
    draw.rounded_rectangle([bx, badge_y, bx + bw, badge_y + bh], radius=24, fill=GOLD)
    draw.text((CONTENT_W // 2, badge_y + bh // 2), "OFERTA ESPECIAL",
              font=_pil_font(FONT_BOLD, 21), fill=NAVY, anchor="mm")

    # ── Product name (up to 2 wrapped lines) ──────────────────────────────────
    name_y = badge_y + bh + 52
    lines  = _wrap_name(producto.nombre.upper(), 20)
    f_name = _pil_font(FONT_BLACK, 60)
    for i, line in enumerate(lines[:2]):
        draw.text((CONTENT_W // 2, name_y + i * 72), line,
                  font=f_name, fill=WHITE, anchor="mm")
    cur_y = name_y + len(lines[:2]) * 72

    # Presentation / concentration
    sub = [x for x in [producto.presentacion, producto.concentracion, producto.contenido] if x]
    if sub:
        cur_y += 22
        draw.text((CONTENT_W // 2, cur_y), "  ·  ".join(sub),
                  font=_pil_font(FONT_SEMI, 24), fill=SILVER, anchor="mm")
        cur_y += 42

    # ── Price section ─────────────────────────────────────────────────────────
    cur_y += 38
    draw.text((CONTENT_W // 2, cur_y), "Precio regular:",
              font=_pil_font(FONT_REG, 24), fill=SILVER, anchor="mm")
    cur_y += 42

    f_tach   = _pil_font(FONT_SEMI, 40)
    txt_tach = f"${precio_tachado:,.2f}"
    draw.text((CONTENT_W // 2, cur_y), txt_tach, font=f_tach, fill=SILVER, anchor="mm")
    bbox  = draw.textbbox((CONTENT_W // 2, cur_y), txt_tach, font=f_tach, anchor="mm")
    mid_y = (bbox[1] + bbox[3]) // 2
    draw.line([(bbox[0] - 4, mid_y), (bbox[2] + 4, mid_y)], fill=RED, width=4)
    cur_y += 58

    draw.text((CONTENT_W // 2, cur_y), "▼  AHORA SOLO",
              font=_pil_font(FONT_BOLD, 26), fill=GOLD, anchor="mm")
    cur_y += 54

    # Big promo price — Montserrat Black
    draw.text((CONTENT_W // 2, cur_y), f"${precio_promo:,.2f}",
              font=_pil_font(FONT_BLACK, 104), fill=GOLD, anchor="mm")
    cur_y += 126

    if texto_extra:
        draw.text((CONTENT_W // 2, cur_y + 6), texto_extra,
                  font=_pil_font(FONT_ITALIC, 26), fill=WHITE, anchor="mm")

    # ── Footer ────────────────────────────────────────────────────────────────
    draw.rectangle([(0, H - 68), (W, H)], fill=DARK)
    draw.text((W // 2, H - 34),
              f"Farmacia Eben-Ezer  ·  {cfg.PHARMACY_ADDRESS}",
              font=_pil_font(FONT_BOLD, 22), fill=WHITE, anchor="mm")

    return img


# ══════════════════════════════════════════════════════════════════════════════
#  Layout B — Fondo BLANCO  ·  #3c73b9, imagen grande, spacing simétrico
# ══════════════════════════════════════════════════════════════════════════════

def _layout_blanco(producto, precio_promo: float,
                    precio_tachado: float, texto_extra: str,
                    prod_img: "Image.Image | None" = None, dia_oferta: str = "",
                    descripcion_promo: str = "") -> Image.Image:
    """Layout horizontal: info a la izquierda, foto grande a la derecha (o blanco si no hay foto)."""
    W, H   = 1080, 1080
    HEADER = 130
    FOOTER = 72

    NAVY  = (29,  33,  64)
    BRAND = (60,  115, 185)
    DARK  = (5,   15,  48)
    WHITE = (255, 255, 255)
    GRAY  = (80,  100, 140)
    SILV  = (155, 175, 215)
    RED   = (215, 42,  42)
    GREEN = (15,  140, 55)

    img  = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # ── Header ───────────────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, HEADER)], fill=NAVY)
    _paste_logo(img, draw, 0, 0, W, HEADER, white=True)
    draw.rectangle([(0, HEADER), (W, HEADER + 5)], fill=BRAND)

    # ── Column geometry ───────────────────────────────────────────────────────
    # Left info column: x ∈ [48, 530]  → 482px wide
    # Divider at x = 545
    # Right image column: x ∈ [555, 1055] → 500px wide
    CONTENT_Y = HEADER + 5
    LX  = 48    # left margin of info column
    LXR = 530   # right edge of info column
    DIV = 545   # vertical divider x
    RX  = 555   # left edge of image column
    RXR = 1055  # right edge of image column

    # Thin vertical divider
    draw.line([(DIV, CONTENT_Y + 40), (DIV, H - FOOTER - 40)],
              fill=(210, 220, 245), width=1)

    # ── LEFT: badge ──────────────────────────────────────────────────────────
    cy = CONTENT_Y + 50

    f_badge    = _pil_font(FONT_BOLD, 16)
    badge_text = (f"{dia_oferta.strip().upper()} DE OFERTAS"
                  if dia_oferta.strip() else "OFERTA ESPECIAL")
    text_w = int(draw.textlength(badge_text, font=f_badge))
    bh = 34
    bw = text_w + 44
    bx = LX
    r  = bh // 2
    draw.ellipse([bx, cy, bx + bh, cy + bh], fill=RED)
    draw.ellipse([bx + bw - bh, cy, bx + bw, cy + bh], fill=RED)
    draw.rectangle([bx + r, cy, bx + bw - r, cy + bh], fill=RED)
    draw.text((bx + bw // 2, cy + bh // 2), badge_text,
              font=f_badge, fill=WHITE, anchor="mm")
    cy += bh + 26

    # ── LEFT: nombre (pixel-based wrap, auto-shrink font) ────────────────────
    lines, f_name = _fit_name(draw, producto.nombre.upper(), FONT_BLACK,
                               max_w=LXR - LX, base_size=58, min_size=26, max_lines=3)
    for i, line in enumerate(lines):
        bb = draw.textbbox((LX, cy), line, font=f_name, anchor="lt")
        draw.text((LX, cy), line, font=f_name, fill=DARK, anchor="lt")
        cy = bb[3] + (6 if i < len(lines) - 1 else 0)
    cy += 16

    # ── LEFT: descripción IA (completa, sin cortar) ───────────────────────────
    if descripcion_promo:
        f_desc   = _pil_font(FONT_REG, 15)
        desc_max = LXR - LX   # 482 px
        words    = descripcion_promo.split()
        desc_lines: list[str] = []
        cur = ""
        for w in words:
            test = (cur + " " + w).strip() if cur else w
            if draw.textlength(test, font=f_desc) <= desc_max:
                cur = test
            else:
                if cur:
                    desc_lines.append(cur)
                cur = w
        if cur:
            desc_lines.append(cur)
        cy += 10
        for i, dl in enumerate(desc_lines):
            draw.text((LX, cy), dl, font=f_desc, fill=GRAY, anchor="lt")
            bb = draw.textbbox((LX, cy), dl, font=f_desc, anchor="lt")
            cy = bb[3] + (3 if i < len(desc_lines) - 1 else 0)
        cy += 12

    # ── LEFT: presentación ───────────────────────────────────────────────────
    raw_sub = [producto.presentacion, producto.concentracion, producto.contenido]
    sub = list(dict.fromkeys(x for x in raw_sub if x))
    if sub:
        f_sub = _pil_font(FONT_SEMI, 19)
        sub_txt = "  ·  ".join(sub)
        draw.text((LX, cy), sub_txt, font=f_sub, fill=GRAY, anchor="lt")
        bb = draw.textbbox((LX, cy), sub_txt, font=f_sub, anchor="lt")
        cy = bb[3]

    info_bottom = cy + 28  # breathing room below info section

    # ── LEFT BOTTOM: medir bloque de precios ─────────────────────────────────
    f_tach   = _pil_font(FONT_SEMI, 36)
    f_price  = _pil_font(FONT_BLACK, 98)
    f_bold20 = _pil_font(FONT_BOLD, 20)
    f_extra  = _pil_font(FONT_ITALIC, 19)
    txt_t = f"${precio_tachado:,.2f}"
    txt_p = f"${precio_promo:,.2f}"
    ahorro = precio_tachado - precio_promo

    def _text_h(txt, font):
        bb = draw.textbbox((0, 0), txt, font=font, anchor="lt")
        return bb[3] - bb[1]

    tach_h  = _text_h(txt_t, f_tach)
    price_h = _text_h(txt_p, f_price)
    sav_h   = (36 + 10) if ahorro > 0.01 else 0
    ext_h   = (_text_h(texto_extra, f_extra) + 16) if texto_extra else 0
    price_block_h = tach_h + 10 + price_h + 16 + sav_h + ext_h

    # Anclar bloque de precios 120px arriba del footer (reduce el hueco central)
    price_start = H - FOOTER - 120 - price_block_h

    # ── Separador centrado en el hueco entre info y precios ───────────────────
    sep_y = (info_bottom + price_start) // 2
    draw.line([(LX, sep_y), (LXR - 10, sep_y)], fill=(200, 215, 245), width=1)

    # ── LEFT: precio tachado ─────────────────────────────────────────────────
    py = price_start
    bb = draw.textbbox((LX, py), txt_t, font=f_tach, anchor="lt")
    draw.text((LX, py), txt_t, font=f_tach, fill=SILV, anchor="lt")
    mid_y = (bb[1] + bb[3]) // 2
    draw.line([(bb[0] - 2, mid_y), (bb[2] + 2, mid_y)], fill=RED, width=3)
    py = bb[3] + 10

    # ── LEFT: precio promo GRANDE ────────────────────────────────────────────
    bb = draw.textbbox((LX, py), txt_p, font=f_price, anchor="lt")
    draw.text((LX, py), txt_p, font=f_price, fill=DARK, anchor="lt")
    py = bb[3] + 16

    # ── LEFT: badge ahorras ───────────────────────────────────────────────────
    if ahorro > 0.01:
        sw = int(draw.textlength(f"¡AHORRAS ${ahorro:,.2f}!", font=f_bold20)) + 32
        draw.rounded_rectangle([LX, py, LX + sw, py + 36], radius=18, fill=GREEN)
        draw.text((LX + sw // 2, py + 18), f"¡AHORRAS ${ahorro:,.2f}!",
                  font=f_bold20, fill=WHITE, anchor="mm")
        py += 46

    if texto_extra:
        draw.text((LX, py + 8), texto_extra, font=f_extra, fill=GRAY, anchor="lt")

    # ── RIGHT: foto grande centrada (si hay imagen) ───────────────────────────
    RW = RXR - RX      # 500
    RH = H - FOOTER - CONTENT_Y - 20
    if prod_img is not None:
        try:
            pimg   = prod_img.convert("RGBA")
            iw, ih = pimg.size
            scale  = min(RW / iw, RH / ih) * 0.90
            nw, nh = int(iw * scale), int(ih * scale)
            pfit   = pimg.resize((nw, nh), Image.LANCZOS)
            px_img = RX + (RW - nw) // 2
            py_img = CONTENT_Y + 20 + (RH - nh) // 2
            img.paste(pfit.convert("RGB"), (px_img, py_img), pfit.split()[3])
        except Exception:
            pass

    # ── Footer ────────────────────────────────────────────────────────────────
    draw.rectangle([(0, H - FOOTER), (W, H)], fill=NAVY)
    draw.rectangle([(0, H - FOOTER), (W, H - FOOTER + 5)], fill=BRAND)
    draw.text((W // 2, H - FOOTER // 2 + 2),
              f"Farmacia Eben-Ezer  ·  {cfg.PHARMACY_ADDRESS}",
              font=_pil_font(FONT_BOLD, 22), fill=WHITE, anchor="mm")

    return img


# ══════════════════════════════════════════════════════════════════════════════
#  Generador PDF con ReportLab
# ══════════════════════════════════════════════════════════════════════════════

def _generar_pdf_reportlab(productos, path: str,
                            inc_stock: bool = True,
                            inc_barcode: bool = True):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                     Paragraph, Spacer, HRFlowable,
                                     Image as RLImage)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    BLUE_RL   = colors.HexColor("#1d2140")
    BLUE_L_RL = colors.HexColor("#EFF6FF")
    DARK_RL   = colors.HexColor("#0F172A")
    MUTED_RL  = colors.HexColor("#64748B")
    GREEN_RL  = colors.HexColor("#16A34A")
    WHITE_RL  = colors.white
    GRAY_RL   = colors.HexColor("#F1F5F9")

    doc = SimpleDocTemplate(
        path,
        pagesize=letter,
        rightMargin=1.5 * cm, leftMargin=1.5 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    styles  = getSampleStyleSheet()
    c_style = ParagraphStyle("cell", parent=styles["Normal"],
                              fontSize=9, textColor=DARK_RL,
                              fontName="Helvetica", leading=12)
    c_bold  = ParagraphStyle("cellbold", parent=c_style, fontName="Helvetica-Bold")
    sub_sty = ParagraphStyle("sub", parent=styles["Normal"],
                              fontSize=10, textColor=MUTED_RL, fontName="Helvetica")

    story = []
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Header: solo logo + título (sin texto duplicado del nombre)
    logo_cell = ""
    for logo_src in (LOGO_PATH, LOGO_BLANCO_PATH):
        if logo_src.exists():
            try:
                logo_rl = RLImage(str(logo_src))
                logo_rl._restrictSize(7 * cm, 2.2 * cm)
                logo_cell = logo_rl
                break
            except Exception:
                pass

    hdr_data = [[
        logo_cell,
        Paragraph(
            f"<b>Catálogo de Productos</b><br/>"
            f"<font color='#64748B' size='9'>Generado: {now_str}</font>",
            ParagraphStyle("rh", parent=styles["Normal"],
                           fontSize=14, textColor=DARK_RL,
                           alignment=TA_RIGHT, fontName="Helvetica-Bold", leading=18)
        ),
    ]]

    hdr_t = Table(hdr_data, colWidths=[8 * cm, None])
    hdr_t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
    ]))
    story.append(hdr_t)
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE_RL, spaceAfter=10))
    story.append(Paragraph(
        f"Total: <b>{len(productos)}</b> productos  ·  "
        f"{cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}",
        sub_sty
    ))
    story.append(Spacer(1, 0.3 * cm))

    # Columnas
    headers  = ["#", "Nombre del Producto", "Categoría", "Precio Venta"]
    col_w    = [1.2 * cm, None, 4.5 * cm, 3 * cm]
    if inc_barcode:
        headers.append("Código de Barras")
        col_w.append(4 * cm)
    if inc_stock:
        headers.append("Stock")
        col_w.append(2.5 * cm)

    def _hdr_cell(txt, align=TA_LEFT):
        return Paragraph(f"<b>{txt}</b>",
                         ParagraphStyle("h", parent=styles["Normal"],
                                        fontSize=9, textColor=WHITE_RL,
                                        fontName="Helvetica-Bold", alignment=align))

    table_data = [[_hdr_cell(h, TA_CENTER if h not in ("Nombre del Producto", "Categoría") else TA_LEFT)
                   for h in headers]]

    for i, p in enumerate(productos):
        cat   = p.categoria.nombre if p.categoria else "—"
        row   = [
            Paragraph(str(i + 1), ParagraphStyle("n", parent=c_style, alignment=TA_CENTER)),
            Paragraph(p.nombre, c_bold),
            Paragraph(cat, c_style),
            Paragraph(f"${p.precio_venta:>8,.2f}",
                      ParagraphStyle("price", parent=c_style, alignment=TA_RIGHT,
                                     textColor=GREEN_RL, fontName="Helvetica-Bold")),
        ]
        if inc_barcode:
            row.append(Paragraph(p.codigo_barras or "—",
                                  ParagraphStyle("bc", parent=c_style, fontSize=8)))
        if inc_stock:
            sc = colors.HexColor("#EF4444") if p.stock <= p.stock_minimo else DARK_RL
            row.append(Paragraph(str(p.stock),
                                  ParagraphStyle("st", parent=c_style,
                                                 alignment=TA_CENTER, textColor=sc)))
        table_data.append(row)

    prod_t = Table(table_data, colWidths=col_w, repeatRows=1)
    prod_t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0),  BLUE_RL),
        ("TEXTCOLOR",      (0, 0), (-1, 0),  WHITE_RL),
        ("FONTNAME",       (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0, 0), (-1, 0),  9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE_RL, GRAY_RL]),
        ("FONTSIZE",       (0, 1), (-1, -1), 9),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
        ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ("GRID",           (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
        ("LINEBELOW",      (0, 0), (-1, 0),  1.5, BLUE_RL),
    ]))
    story.append(prod_t)

    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=MUTED_RL))
    story.append(Paragraph(
        f"<font color='#64748B' size='8'>{cfg.PHARMACY_NAME}  ·  "
        f"{cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}</font>",
        ParagraphStyle("foot", parent=styles["Normal"], alignment=TA_CENTER)
    ))
    doc.build(story)


# ══════════════════════════════════════════════════════════════════════════════
#  Manual de Usuario — PDF auto-generado con todos los atajos y funciones
# ══════════════════════════════════════════════════════════════════════════════

def generar_manual_pdf(path: str) -> None:
    """Genera el manual de usuario del sistema POS en PDF (ReportLab)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable,
                                    Image as RLImage, KeepTogether)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    BLUE_RL  = colors.HexColor("#1d2140")
    BLUE_L   = colors.HexColor("#EFF6FF")
    DARK_RL  = colors.HexColor("#0F172A")
    MUTED_RL = colors.HexColor("#64748B")
    GREEN_RL = colors.HexColor("#16A34A")
    RED_RL   = colors.HexColor("#DC2626")
    GRAY_RL  = colors.HexColor("#F1F5F9")
    WHITE_RL = colors.white

    doc = SimpleDocTemplate(
        path,
        pagesize=letter,
        rightMargin=1.8 * cm, leftMargin=1.8 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
        title=f"Manual de Usuario — {cfg.PHARMACY_NAME}",
    )
    styles = getSampleStyleSheet()
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    body  = sty("body",  fontSize=9,  textColor=DARK_RL,  fontName="Helvetica",       leading=13)
    bold9 = sty("bold9", fontSize=9,  textColor=DARK_RL,  fontName="Helvetica-Bold",  leading=13)
    mut9  = sty("mut9",  fontSize=9,  textColor=MUTED_RL, fontName="Helvetica",       leading=13)
    grn9  = sty("grn9",  fontSize=9,  textColor=GREEN_RL, fontName="Helvetica-Bold",  leading=13, alignment=TA_CENTER)
    ctr   = sty("ctr",   fontSize=9,  textColor=DARK_RL,  fontName="Helvetica",       leading=13, alignment=TA_CENTER)
    hdr_c = sty("hdr_c", fontSize=9,  textColor=WHITE_RL, fontName="Helvetica-Bold",  leading=13, alignment=TA_CENTER)

    story = []

    # ── Portada / Header ──────────────────────────────────────────────────────
    logo_cell = ""
    for logo_src in (LOGO_PATH, LOGO_BLANCO_PATH):
        if logo_src.exists():
            try:
                rl = RLImage(str(logo_src))
                rl._restrictSize(6 * cm, 2 * cm)
                logo_cell = rl
                break
            except Exception:
                pass

    hdr_data = [[
        logo_cell,
        Paragraph(
            f"<b>Manual de Usuario</b><br/>"
            f"<font color='#64748B' size='9'>v{cfg.VERSION}  ·  Generado: {now_str}</font>",
            sty("rh", fontSize=14, textColor=DARK_RL, alignment=TA_RIGHT,
                fontName="Helvetica-Bold", leading=18)
        ),
    ]]
    hdr_t = Table(hdr_data, colWidths=[7 * cm, None])
    hdr_t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
    ]))
    story.append(hdr_t)
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE_RL, spaceAfter=6))
    story.append(Paragraph(
        f"{cfg.PHARMACY_NAME}  ·  {cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}",
        mut9
    ))
    story.append(Spacer(1, 0.5 * cm))

    # ── Utilidades ────────────────────────────────────────────────────────────
    def section_title(txt, icon=""):
        story.append(Spacer(1, 0.35 * cm))
        t = Table(
            [[Paragraph(f"<b>{icon}  {txt}</b>" if icon else f"<b>{txt}</b>",
                        sty("st", fontSize=11, textColor=WHITE_RL,
                            fontName="Helvetica-Bold", leading=14))]],
            colWidths=["100%"],
        )
        t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, -1), BLUE_RL),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
            ("LEFTPADDING",    (0, 0), (-1, -1), 10),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
            ("ROUNDEDCORNERS", (0, 0), (-1, -1), [4, 4, 4, 4]),
        ]))
        story.append(t)
        story.append(Spacer(1, 0.2 * cm))

    def key_table(rows):
        """rows = [(key_label, description), ...]"""
        data = [
            [Paragraph("<b>Tecla</b>", hdr_c), Paragraph("<b>Acción</b>", hdr_c)]
        ] + [
            [Paragraph(f"<b>{k}</b>", grn9), Paragraph(d, body)]
            for k, d in rows
        ]
        t = Table(data, colWidths=[3 * cm, None])
        t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  BLUE_RL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE_RL, GRAY_RL]),
            ("GRID",           (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
            ("LINEBELOW",      (0, 0), (-1, 0),  1.5, BLUE_RL),
        ]))
        story.append(KeepTogether(t))
        story.append(Spacer(1, 0.25 * cm))

    def info_table(rows):
        """rows = [(label, value), ...]"""
        data = [[Paragraph(f"<b>{l}</b>", bold9), Paragraph(v, body)] for l, v in rows]
        t = Table(data, colWidths=[5 * cm, None])
        t.setStyle(TableStyle([
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE_RL, GRAY_RL]),
            ("GRID",           (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",     (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ]))
        story.append(KeepTogether(t))
        story.append(Spacer(1, 0.25 * cm))

    # ═══════════════════════════════════════════════════════════════════════
    #  1. ATAJOS DE TECLADO
    # ═══════════════════════════════════════════════════════════════════════
    section_title("ATAJOS DE TECLADO — Acceso rápido global")
    key_table([
        ("F1",  "Ir al módulo POS (Punto de Venta)"),
        ("F2 / F3", "POS → enfocar campo de búsqueda de producto para teclear inmediatamente"),
        ("F5",  "Limpiar el carrito de venta actual (pide confirmación)"),
        ("F6",  "Ir al módulo de Inventario"),
        ("F7",  "Ir al módulo de Reportes (solo administrador)"),
        ("F8",  "POS → enfocar campo de monto pagado (cobrar efectivo)"),
        ("F10", "Procesar y confirmar la venta actual"),
        ("Enter (en buscador)", "Agregar el primer resultado al carrito automáticamente"),
        ("Tab (en buscador)",   "Mismo efecto que Enter — agrega el producto al carrito"),
        ("Esc (en modal)",      "Cerrar ventana emergente activa"),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  2. SECCIONES DEL SISTEMA
    # ═══════════════════════════════════════════════════════════════════════
    section_title("SECCIONES DEL SISTEMA")
    info_table([
        ("POS (Punto de Venta)",  "Registrar ventas, buscar productos por nombre/código de barras, cobrar en efectivo, tarjeta o transferencia, imprimir ticket."),
        ("Inventario",            "Ver stock, buscar por nombre/marca/código, editar producto, gestionar lotes de caducidad, ajuste físico de inventario."),
        ("Ventas",                "Historial completo de ventas, filtrar por fecha/cajero/método de pago, cancelar venta (restaura stock automáticamente)."),
        ("Reportes",              "Resumen de ventas por período, ganancias, productos más vendidos, exportar a Excel/PDF (solo administrador)."),
        ("Clientes",              "Base de datos de clientes, historial de compras, recetas médicas, alergias y antecedentes."),
        ("Control de Caja",       "Abrir/cerrar turnos, registrar retiros (personal o inversión), ver ganancia disponible del período."),
        ("Empleados",             "Crear y gestionar usuarios (cajeros y administradores), cambiar contraseña."),
        ("Configuración",         "Datos de la farmacia, credenciales API (Turso, Cloudinary), terminal Mercado Pago, respaldo y restauración de BD."),
        ("Marketing",             "Generar catálogo PDF de productos, crear imágenes promocionales para redes sociales, descargar este manual."),
        ("IA Médica",             "Asistente de inteligencia artificial para consultas farmacéuticas y verificación de medicamentos."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  3. CÓMO HACER UNA VENTA (POS)
    # ═══════════════════════════════════════════════════════════════════════
    section_title("CÓMO HACER UNA VENTA — POS")
    info_table([
        ("1. Abrir POS",         "Presionar F1 o hacer clic en 'POS' en el menú lateral izquierdo."),
        ("2. Buscar producto",    "Presionar F2 o F3 y teclear el nombre, marca o código de barras. El sistema busca en tiempo real."),
        ("3. Agregar al carrito", "Presionar Enter o Tab para agregar el primer resultado. También se puede hacer clic en el producto."),
        ("4. Ajustar cantidad",   "En el carrito, hacer clic en + / − o editar el número directamente. Doble clic en el precio para aplicar descuento."),
        ("5. Seleccionar pago",   "Elegir Efectivo, Tarjeta o Transferencia en los botones de método de pago."),
        ("6. Cobrar",             "Presionar F10 o el botón 'Cobrar'. Para efectivo: ingresar el monto recibido (F8 enfoca ese campo)."),
        ("7. Ticket",             "El ticket se imprime automáticamente si hay impresora configurada. También se puede guardar como PDF."),
        ("Descuento global",      "Ingresar porcentaje en el campo '% Desc' del carrito para aplicar descuento a toda la venta."),
        ("Receta requerida",      "Si el producto requiere receta, el sistema muestra alerta. Se puede asociar al expediente del cliente."),
        ("Cajero de prueba",      "Modo especial (usuario 'cajero') para simular ventas sin registrarlas en la base de datos."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  4. INVENTARIO
    # ═══════════════════════════════════════════════════════════════════════
    section_title("INVENTARIO")
    info_table([
        ("Ver stock",          "Menú lateral → Inventario (o F6). Lista todos los productos con stock, precio y código."),
        ("Buscar producto",    "Campo de búsqueda superior: busca por nombre, marca, código de barras o categoría."),
        ("Agregar producto",   "Botón '+' (verde) en la barra superior. Completar campos obligatorios: nombre, precio, stock inicial."),
        ("Editar producto",    "Clic en el ícono de lápiz (✏) en la fila del producto. Se puede cambiar precio, stock mínimo, imagen, etc."),
        ("Lotes/Caducidad",    "Clic en ícono de lotes (🗂) para agregar lotes con fecha de caducidad. El sistema alerta cuando están próximos a vencer."),
        ("Ajuste físico",      "Clic en ícono de ajuste (◎) para corregir stock cuando hay diferencia entre el conteo físico y el sistema."),
        ("Stock bajo",         "Los productos con stock ≤ stock mínimo se resaltan en rojo automáticamente."),
        ("Descuento",          "Campo 'Desc %' en el detalle del producto para aplicar descuento permanente en POS."),
        ("Sync automático",    "El stock se descuenta automáticamente con cada venta en todas las PCs conectadas a la nube."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  5. CONTROL DE CAJA
    # ═══════════════════════════════════════════════════════════════════════
    section_title("CONTROL DE CAJA")
    info_table([
        ("Abrir turno",        "Módulo 'Caja' → botón 'Abrir Turno'. Ingresar monto de apertura (efectivo inicial en caja)."),
        ("Cerrar turno",       "Botón 'Cerrar Turno'. El sistema calcula ganancia bruta, retiros y efectivo esperado en caja."),
        ("Retiro personal",    "Registrar retirada de ganancia personal. El sistema valida que no exceda la ganancia disponible."),
        ("Retiro inversión",   "Registrar recompra de mercancía. Se descuenta del capital de inversión calculado."),
        ("Ganancia disponible","Ganancia bruta del período menos los retiros personales ya registrados."),
        ("Efectivo en caja",   "Monto de apertura + ventas en efectivo − retiros. Lo que debería haber físicamente."),
        ("Sync multi-PC",      "Los retiros de cualquier PC se sincronizan automáticamente. Botón 'Sync' fuerza actualización inmediata."),
        ("Corte histórico",    "Desde 'Cortes históricos' se puede ver y crear cierres con fecha retroactiva (solo admin)."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  6. SINCRONIZACIÓN MULTI-PC (TURSO)
    # ═══════════════════════════════════════════════════════════════════════
    section_title("SINCRONIZACIÓN MULTI-PC — Turso Cloud")
    info_table([
        ("Cómo funciona",     "Cada PC tiene una copia local (SQLite). Los datos se sincronizan automáticamente con la nube (Turso) cada 30 segundos."),
        ("Al hacer una venta","Los datos se envían a la nube inmediatamente después de cada venta."),
        ("Sync forzado",      "En Control de Caja → botón 'Sync' para forzar sincronización bidireccional de inmediato."),
        ("Sin internet",      "El sistema sigue funcionando localmente. Los cambios se suben cuando se restaura la conexión."),
        ("Primer inicio",     "Si la BD local está vacía, el sistema importa todos los datos desde la nube automáticamente."),
        ("Tablas sincronizadas", "Productos, inventario, ventas, clientes, usuarios, cortes, retiros, lotes, compras."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  7. MÉTODOS DE PAGO
    # ═══════════════════════════════════════════════════════════════════════
    section_title("MÉTODOS DE PAGO")
    info_table([
        ("Efectivo",          "Ingresar monto recibido → el sistema calcula el cambio automáticamente. F8 enfoca este campo."),
        ("Tarjeta",           "Registra el cobro con tarjeta. Si hay terminal Mercado Pago configurada, envía el monto automáticamente."),
        ("Transferencia",     "Para pagos por transferencia bancaria (SPEI, CoDi, etc.). Se registra igual que efectivo pero sin cambio."),
        ("Terminal MP",       "Mercado Pago Point (modelo Point Smart 2). Se configura en Configuración → Terminal de Pago."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  8. CONFIGURACIÓN
    # ═══════════════════════════════════════════════════════════════════════
    section_title("CONFIGURACIÓN (solo administrador)")
    info_table([
        ("Datos farmacia",    "Nombre, dirección, teléfono, RFC — aparecen en los tickets de venta."),
        ("Turno automático",  "Configura hora de apertura y cierre automático de turno (activa en configuración)."),
        ("Turso / Nube",      "Token de acceso a la base de datos en la nube. No modificar sin conocimiento técnico."),
        ("Cloudinary",        "Servicio de imágenes para fotos de productos. Se configura con API Key y Secret."),
        ("Terminal MP",       "Access Token y Device ID de Mercado Pago Point para cobros con tarjeta automáticos."),
        ("Respaldo BD",       "Exportar copia de seguridad (.db) de la base de datos local. Recomendado: semanal."),
        ("Restaurar BD",      "Cargar archivo .db de respaldo. ADVERTENCIA: reemplaza todos los datos actuales."),
        ("Purgar datos",      "Opciones para eliminar ventas/historial o todos los datos. Operación irreversible."),
    ])

    # ═══════════════════════════════════════════════════════════════════════
    #  9. ACTUALIZACIONES
    # ═══════════════════════════════════════════════════════════════════════
    section_title("ACTUALIZACIONES DEL SISTEMA")
    info_table([
        ("Verificación",      "El sistema verifica automáticamente si hay versión nueva al iniciar."),
        ("Actualizar",        "Notificación en la barra superior → clic en 'Actualizar'. El sistema descarga e instala automáticamente."),
        ("Versión actual",    f"v{cfg.VERSION}"),
        ("Repositorio",       "Las actualizaciones se publican en GitHub y se distribuyen como instalador (.exe)."),
    ])

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=MUTED_RL))
    story.append(Spacer(1, 0.15 * cm))
    story.append(Paragraph(
        f"<font color='#64748B' size='8'>"
        f"{cfg.PHARMACY_NAME}  ·  {cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}  ·  "
        f"Manual v{cfg.VERSION} — {now_str}"
        f"</font>",
        sty("foot", fontSize=8, alignment=TA_CENTER)
    ))

    doc.build(story)
