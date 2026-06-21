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
#  Manual de Usuario — PDF profesional multi-página con diagrams y guías
# ══════════════════════════════════════════════════════════════════════════════

def generar_manual_pdf(path: str) -> None:  # noqa: C901
    """Genera el manual de usuario profesional — portada, índice, sección por página."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, HRFlowable,
                                    Image as RLImage, KeepTogether, PageBreak)
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY

    W, H = letter
    now_str  = datetime.now().strftime("%d/%m/%Y")
    now_full = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ── Paleta ────────────────────────────────────────────────────────────────
    C_BLUE   = colors.HexColor("#1d2140")
    C_BLUE_L = colors.HexColor("#EFF6FF")
    C_BLUE_M = colors.HexColor("#BFDBFE")
    C_DARK   = colors.HexColor("#0F172A")
    C_MUTED  = colors.HexColor("#64748B")
    C_GREEN  = colors.HexColor("#16A34A")
    C_GRN_L  = colors.HexColor("#DCFCE7")
    C_AMBER  = colors.HexColor("#D97706")
    C_AMB_L  = colors.HexColor("#FFFBEB")
    C_AMB_B  = colors.HexColor("#FDE68A")
    C_RED    = colors.HexColor("#DC2626")
    C_RED_L  = colors.HexColor("#FEF2F2")
    C_GRAY   = colors.HexColor("#F1F5F9")
    C_GRAY_B = colors.HexColor("#E2E8F0")
    C_WHITE  = colors.white
    C_CYAN   = colors.HexColor("#0EA5E9")
    C_CYAN_L = colors.HexColor("#E0F2FE")

    styles = getSampleStyleSheet()

    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    s_body  = sty("_b",  fontSize=9,  textColor=C_DARK,  fontName="Helvetica",      leading=14)
    s_bold  = sty("_bb", fontSize=9,  textColor=C_DARK,  fontName="Helvetica-Bold", leading=14)
    s_mut   = sty("_m",  fontSize=8,  textColor=C_MUTED, fontName="Helvetica",      leading=12)
    s_just  = sty("_j",  fontSize=9,  textColor=C_DARK,  fontName="Helvetica",      leading=14, alignment=TA_JUSTIFY)
    s_hdr   = sty("_h",  fontSize=9,  textColor=C_WHITE, fontName="Helvetica-Bold", leading=13, alignment=TA_CENTER)
    s_ctrb  = sty("_cb", fontSize=9,  textColor=C_DARK,  fontName="Helvetica-Bold", leading=13, alignment=TA_CENTER)
    s_green = sty("_g",  fontSize=9,  textColor=C_GREEN, fontName="Helvetica-Bold", leading=13, alignment=TA_CENTER)
    s_white = sty("_w",  fontSize=9,  textColor=C_WHITE, fontName="Helvetica",      leading=13)
    s_wb    = sty("_wb", fontSize=9,  textColor=C_WHITE, fontName="Helvetica-Bold", leading=13)

    story = []
    cw = W - 3.6 * cm  # usable width (margins 1.8cm each side)

    # ─────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def sp(h=0.3):
        story.append(Spacer(1, h * cm))

    def hr(clr=C_GRAY_B, t=0.5):
        story.append(HRFlowable(width="100%", thickness=t, color=clr, spaceAfter=6))

    def pb():
        story.append(PageBreak())

    def section_banner(num: int, title: str, sub: str = ""):
        t = Table([[
            Paragraph(f"<b>{num:02d}</b>",
                      sty(f"bn{num}", fontSize=30, textColor=C_WHITE,
                          fontName="Helvetica-Bold", leading=34, alignment=TA_CENTER)),
            [Paragraph(f"<b>{title}</b>",
                       sty(f"bt{num}", fontSize=16, textColor=C_WHITE,
                           fontName="Helvetica-Bold", leading=20)),
             Spacer(1, 3),
             Paragraph(sub,
                       sty(f"bs{num}", fontSize=9, textColor=colors.HexColor("#93C5FD"),
                           fontName="Helvetica", leading=12)) if sub else Spacer(0, 0)],
        ]], colWidths=[2.4 * cm, None])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("LINEAFTER",     (0, 0), (0, -1),  1, colors.HexColor("#FFFFFF25")),
        ]))
        story.append(t)
        sp(0.35)

    def sub_label(txt: str, clr=C_BLUE):
        t = Table([[Paragraph(f"<b>{txt}</b>",
                              sty(f"sl{txt[:4]}", fontSize=8, textColor=clr,
                                  fontName="Helvetica-Bold", leading=11))]], colWidths=[cw])
        t.setStyle(TableStyle([
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ("LINEBELOW",     (0, 0), (-1, -1), 1, clr),
        ]))
        story.append(t)
        sp(0.12)

    def tip_box(text: str, kind="info"):
        if kind == "warning":
            bg, bd, lbl, tc = C_AMB_L,  C_AMB_B,  "⚠  ATENCIÓN",     C_AMBER
        elif kind == "success":
            bg, bd, lbl, tc = C_GRN_L,  C_GREEN,  "✓  CONSEJO",       C_GREEN
        elif kind == "error":
            bg, bd, lbl, tc = C_RED_L,  C_RED,    "✕  IMPORTANTE",    C_RED
        else:
            bg, bd, lbl, tc = C_BLUE_L, C_BLUE_M, "ℹ  INFORMACIÓN",   C_BLUE
        cell = [
            Paragraph(f"<b>{lbl}</b>",
                      sty(f"tl{lbl[:2]}", fontSize=8, textColor=tc,
                          fontName="Helvetica-Bold", leading=11)),
            Spacer(1, 3),
            Paragraph(text, sty(f"tb{lbl[:2]}", fontSize=9, textColor=C_DARK,
                                fontName="Helvetica", leading=13)),
        ]
        t = Table([[cell]], colWidths=[cw])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), bg),
            ("TOPPADDING",    (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING",   (0, 0), (-1, -1), 12),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
            ("LINEBEFORE",    (0, 0), (0, -1),  3, bd),
            ("BOX",           (0, 0), (-1, -1), 0.5, bd),
        ]))
        story.append(KeepTogether(t))
        sp(0.2)

    def step_boxes(steps):
        for i, (title, desc) in enumerate(steps):
            num_t = Table(
                [[Paragraph(f"<b>{i + 1}</b>",
                            sty(f"sn{i}", fontSize=12, textColor=C_WHITE,
                                fontName="Helvetica-Bold", leading=14, alignment=TA_CENTER))]],
                colWidths=[0.85 * cm], rowHeights=[0.85 * cm],
            )
            num_t.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ]))
            row = Table([[num_t,
                         [Paragraph(f"<b>{title}</b>",
                                    sty(f"stit{i}", fontSize=9, textColor=C_DARK,
                                        fontName="Helvetica-Bold", leading=13)),
                          Paragraph(desc, s_just)]]],
                        colWidths=[1.2 * cm, None])
            row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                ("BOX",           (0, 0), (-1, -1), 0.5, C_GRAY_B),
                ("LINEAFTER",     (0, 0), (0, -1),  2.5, C_BLUE),
                ("BACKGROUND",    (0, 0), (-1, -1), C_WHITE),
            ]))
            story.append(KeepTogether(row))
            if i < len(steps) - 1:
                arr = Table([[Paragraph("↓", sty(f"ar{i}", fontSize=13, textColor=C_MUTED,
                                                 alignment=TA_CENTER))]], colWidths=[1.2 * cm])
                arr.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),
                                         ("LEFTPADDING",(0,0),(-1,-1),0)]))
                outer = Table([[arr, ""]], colWidths=[1.2 * cm, None])
                outer.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
                                            ("LEFTPADDING",(0,0),(-1,-1),0)]))
                story.append(outer)
        sp(0.2)

    def flow_diagram(steps):
        n   = len(steps)
        sw  = cw / (n * 2 - 1)  # step width unit
        cells = []
        widths = []
        for i, (icon, label) in enumerate(steps):
            cells.append([
                Paragraph(icon, sty(f"fi{i}", fontSize=16, alignment=TA_CENTER)),
                Spacer(1, 3),
                Paragraph(f"<b>{label}</b>",
                          sty(f"fl{i}", fontSize=8, textColor=C_DARK,
                              fontName="Helvetica-Bold", alignment=TA_CENTER, leading=11)),
            ])
            widths.append(sw * 2)
            if i < n - 1:
                cells.append(Paragraph("→", sty(f"fa{i}", fontSize=16, textColor=C_MUTED,
                                                alignment=TA_CENTER)))
                widths.append(sw)
        t = Table([cells], colWidths=widths)
        bg_cmds = [("BACKGROUND", (i * 2, 0), (i * 2, 0), C_BLUE_L) for i in range(n)]
        bx_cmds = [("BOX",        (i * 2, 0), (i * 2, 0), 0.5, C_BLUE_M) for i in range(n)]
        t.setStyle(TableStyle([
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ] + bg_cmds + bx_cmds))
        story.append(KeepTogether(t))
        sp(0.25)

    def key_table(rows):
        """rows = [(key, function, description)]"""
        data = [[Paragraph("<b>Tecla</b>", s_hdr),
                 Paragraph("<b>Función</b>", s_hdr),
                 Paragraph("<b>Descripción detallada</b>", s_hdr)]]
        for key, func, desc in rows:
            kb = Table([[Paragraph(f"<b>{key}</b>",
                                   sty(f"k{key}", fontSize=8, textColor=C_DARK,
                                       fontName="Helvetica-Bold", alignment=TA_CENTER))]],
                       colWidths=[2.6 * cm])
            kb.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), C_GRAY),
                ("BOX",           (0, 0), (-1, -1), 0.75, C_GRAY_B),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            data.append([kb, Paragraph(f"<b>{func}</b>", s_bold), Paragraph(desc, s_body)])
        t = Table(data, colWidths=[3 * cm, 4 * cm, None])
        t.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  C_BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_GRAY]),
            ("GRID",           (0, 0), (-1, -1), 0.25, C_GRAY_B),
            ("LINEBELOW",      (0, 0), (-1, 0),  1.5, C_BLUE),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
        ]))
        story.append(KeepTogether(t))
        sp(0.25)

    def feat_list(items):
        for label, desc in items:
            row = Table([[
                Paragraph("●", sty(f"dt{label[:3]}", fontSize=11, textColor=C_BLUE,
                                   fontName="Helvetica-Bold", alignment=TA_CENTER)),
                [Paragraph(f"<b>{label}</b>",
                           sty(f"fl{label[:3]}", fontSize=9, textColor=C_DARK,
                               fontName="Helvetica-Bold", leading=13)),
                 Paragraph(desc, s_mut) if desc else Spacer(0, 0)],
            ]], colWidths=[0.55 * cm, None])
            row.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING",   (0, 0), (-1, -1), 0),
            ]))
            story.append(row)
        sp(0.15)

    def grid_table(data, col_widths, header=True):
        t = Table(data, colWidths=col_widths)
        cmds = [
            ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [C_WHITE, C_GRAY]),
            ("GRID",           (0, 0), (-1, -1), 0.25, C_GRAY_B),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",     (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
            ("LEFTPADDING",    (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
        ]
        if header:
            cmds += [
                ("BACKGROUND", (0, 0), (-1, 0), C_BLUE),
                ("LINEBELOW",  (0, 0), (-1, 0), 1.5, C_BLUE),
                ("VALIGN",     (0, 0), (-1, 0), "MIDDLE"),
            ]
        t.setStyle(TableStyle(cmds))
        story.append(KeepTogether(t))
        sp(0.2)

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ PORTADA ═══
    # ─────────────────────────────────────────────────────────────────────────
    logo_img = ""
    for lsrc in (LOGO_BLANCO_PATH, LOGO_PATH):
        if lsrc.exists():
            try:
                rl = RLImage(str(lsrc))
                rl._restrictSize(9 * cm, 3 * cm)
                logo_img = rl
                break
            except Exception:
                pass

    cover = Table([[
        logo_img if logo_img else Spacer(1, 3 * cm),
        Spacer(1, 0.6 * cm),
        Paragraph("MANUAL DE USUARIO",
                  sty("ct", fontSize=30, textColor=C_WHITE, fontName="Helvetica-Bold",
                      leading=36, alignment=TA_CENTER)),
        Spacer(1, 0.25 * cm),
        Paragraph(f"Sistema POS — {cfg.PHARMACY_NAME}",
                  sty("cs", fontSize=13, textColor=colors.HexColor("#93C5FD"),
                      fontName="Helvetica", leading=17, alignment=TA_CENTER)),
        Spacer(1, 0.5 * cm),
        HRFlowable(width="60%", thickness=1, color=colors.HexColor("#FFFFFF40")),
        Spacer(1, 0.5 * cm),
        Paragraph(f"Versión {cfg.VERSION}",
                  sty("cv", fontSize=11, textColor=colors.HexColor("#CBD5E1"),
                      fontName="Helvetica", alignment=TA_CENTER)),
        Spacer(1, 0.12 * cm),
        Paragraph(now_str,
                  sty("cd", fontSize=10, textColor=colors.HexColor("#94A3B8"),
                      fontName="Helvetica", alignment=TA_CENTER)),
        Spacer(1, 1.8 * cm),
        Paragraph(f"<b>{cfg.PHARMACY_NAME}</b>",
                  sty("cn", fontSize=12, textColor=C_WHITE, fontName="Helvetica-Bold",
                      alignment=TA_CENTER)),
        Spacer(1, 0.1 * cm),
        Paragraph(f"{cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}",
                  sty("ca", fontSize=9, textColor=colors.HexColor("#94A3B8"),
                      fontName="Helvetica", alignment=TA_CENTER)),
    ]], colWidths=[cw])
    cover.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(cover)
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ ÍNDICE ═══
    # ─────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Índice de Contenidos",
                            sty("idx", fontSize=18, textColor=C_DARK,
                                fontName="Helvetica-Bold", leading=24)))
    sp(0.25)
    hr(C_BLUE, 2)
    sp(0.15)

    toc_rows = [
        ("01", "Atajos de Teclado",       "Referencia de todas las teclas de acceso directo del sistema"),
        ("02", "Módulos del Sistema",      "Descripción de cada sección y sus funciones principales"),
        ("03", "Punto de Venta (POS)",     "Cómo registrar ventas — guía paso a paso con flujo completo"),
        ("04", "Inventario",               "Gestión de productos, stock, lotes de caducidad y ajustes"),
        ("05", "Control de Caja",          "Turnos, retiros de efectivo y cálculo financiero"),
        ("06", "Sincronización Multi-PC",  "Arquitectura en red con Turso Cloud — cómo fluyen los datos"),
        ("07", "Métodos de Pago",          "Efectivo, tarjeta y configuración terminal Mercado Pago"),
        ("08", "Gestión de Clientes",      "Expedientes, historial de compras y recetas médicas"),
        ("09", "Configuración",            "Ajustes del sistema, APIs, usuarios y respaldos de base de datos"),
        ("10", "Actualizaciones",          "Cómo mantener el sistema al día — proceso automático"),
    ]
    toc_data = [[Paragraph(f"<b>{n}</b>",
                            sty(f"tn{n}", fontSize=16, textColor=C_BLUE,
                                fontName="Helvetica-Bold", leading=20, alignment=TA_CENTER)),
                 [Paragraph(f"<b>{t}</b>",
                             sty(f"tt{n}", fontSize=11, textColor=C_DARK,
                                 fontName="Helvetica-Bold", leading=15)),
                  Paragraph(d, sty(f"td{n}", fontSize=8, textColor=C_MUTED,
                                   fontName="Helvetica", leading=12))]]
                for n, t, d in toc_rows]
    toc_t = Table(toc_data, colWidths=[1.4 * cm, None])
    toc_t.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_GRAY]),
        ("GRID",           (0, 0), (-1, -1), 0.25, C_GRAY_B),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ("LINEAFTER",      (0, 0), (0, -1),  2, C_BLUE),
    ]))
    story.append(KeepTogether(toc_t))
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 01 — ATAJOS DE TECLADO ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(1, "Atajos de Teclado", "Acceso rápido desde cualquier pantalla del sistema")
    story.append(Paragraph(
        "Los atajos funcionan en cualquier módulo mientras el usuario esté autenticado. "
        "El sistema navega automáticamente al módulo correspondiente al presionar la tecla.",
        s_just))
    sp(0.25)
    key_table([
        ("F1",     "Ir al POS",            "Navega directamente al Punto de Venta desde cualquier sección del sistema."),
        ("F2",     "Buscar producto",       "Abre el POS y coloca el cursor en el buscador para teclear nombre o código de barras."),
        ("F3",     "Buscar producto",       "Igual que F2 — acceso alternativo al buscador. Útil para flujo de caja rápido."),
        ("F5",     "Limpiar carrito",       "Elimina todos los productos del carrito activo. Solicita confirmación antes de borrar."),
        ("F6",     "Inventario",            "Navega al módulo de Inventario para consultar o modificar productos y stock."),
        ("F7",     "Reportes (admin)",      "Abre el módulo de Reportes. Solo disponible para usuarios con rol Administrador."),
        ("F8",     "Campo de pago",         "Enfoca el campo 'Monto recibido' en el POS para cobrar con teclado sin usar el ratón."),
        ("F10",    "Procesar venta",        "Confirma y procesa la venta actual. Equivale a presionar el botón 'Cobrar [F10]'."),
        ("Enter",  "Agregar al carrito",    "En el buscador del POS: agrega el primer producto de la lista al carrito."),
        ("Tab",    "Agregar al carrito",    "Alternativa a Enter en el buscador — mismo efecto para flujo continuo de captura."),
        ("Escape", "Cerrar ventana",        "Cierra el modal o ventana emergente activa sin guardar cambios."),
    ])
    sp(0.15)
    tip_box(
        "<b>Flujo recomendado sin ratón:</b>  "
        "<b>F3</b> → escribir producto → <b>Enter</b> (agregar) → repetir → "
        "<b>F8</b> (monto) → ingresar cantidad → <b>F10</b> (cobrar). "
        "Una venta completa en segundos usando solo el teclado.",
        kind="success"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 02 — MÓDULOS DEL SISTEMA ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(2, "Módulos del Sistema", "Descripción de cada sección y sus funciones principales")
    story.append(Paragraph(
        "El sistema se organiza en módulos accesibles desde el menú lateral izquierdo. "
        "Los módulos marcados con <b>🔒 Admin</b> solo están disponibles para usuarios con rol Administrador.",
        s_just))
    sp(0.25)
    mod_data = [
        [Paragraph("<b>Módulo</b>", s_hdr),
         Paragraph("<b>Acceso</b>", s_hdr),
         Paragraph("<b>Funciones principales</b>", s_hdr)],
        [Paragraph("🛒 Nueva Venta — POS", s_bold),
         Paragraph("Todos", s_green),
         Paragraph("Registrar ventas, buscar productos, cobrar, imprimir tickets", s_body)],
        [Paragraph("📦 Inventario", s_bold),
         Paragraph("Todos", s_green),
         Paragraph("Consultar stock, editar productos, agregar lotes, ajuste físico", s_body)],
        [Paragraph("👥 Clientes", s_bold),
         Paragraph("Todos", s_green),
         Paragraph("Expedientes, historial de compras, alergias, recetas médicas", s_body)],
        [Paragraph("🧠 IA Médica", s_bold),
         Paragraph("Todos", s_green),
         Paragraph("Asistente farmacéutico con inteligencia artificial (Farmacito)", s_body)],
        [Paragraph("📋 Historial Clínico", s_bold),
         Paragraph("Todos", s_green),
         Paragraph("Consultas, prescripciones y seguimiento por paciente", s_body)],
        [Paragraph("📈 Dashboard", s_bold),
         Paragraph("Todos", s_green),
         Paragraph("Métricas del día: ventas, ingresos, stock bajo, turno activo", s_body)],
        [Paragraph("📊 Reportes", s_bold),
         Paragraph("🔒 Admin", sty("adm1", fontSize=9, textColor=C_AMBER, fontName="Helvetica-Bold",
                                   leading=13, alignment=TA_CENTER)),
         Paragraph("Resumen de ventas, ganancias, exportar Excel/PDF por período", s_body)],
        [Paragraph("🏦 Control de Caja", s_bold),
         Paragraph("🔒 Admin", sty("adm2", fontSize=9, textColor=C_AMBER, fontName="Helvetica-Bold",
                                   leading=13, alignment=TA_CENTER)),
         Paragraph("Turnos, apertura/cierre, retiros, ganancia disponible, sincronización", s_body)],
        [Paragraph("👤 Empleados", s_bold),
         Paragraph("🔒 Admin", sty("adm3", fontSize=9, textColor=C_AMBER, fontName="Helvetica-Bold",
                                   leading=13, alignment=TA_CENTER)),
         Paragraph("Crear y gestionar cajeros, cambiar contraseñas, activar/desactivar", s_body)],
        [Paragraph("🎯 Marketing", s_bold),
         Paragraph("🔒 Admin", sty("adm4", fontSize=9, textColor=C_AMBER, fontName="Helvetica-Bold",
                                   leading=13, alignment=TA_CENTER)),
         Paragraph("Catálogo PDF, imágenes promo para redes sociales, manual PDF", s_body)],
        [Paragraph("⚙️ Configuración", s_bold),
         Paragraph("🔒 Admin", sty("adm5", fontSize=9, textColor=C_AMBER, fontName="Helvetica-Bold",
                                   leading=13, alignment=TA_CENTER)),
         Paragraph("Datos farmacia, APIs, terminal MP, respaldo y restauración de BD", s_body)],
    ]
    grid_table(mod_data, [5.5 * cm, 2.2 * cm, None])
    tip_box(
        "Al iniciar sesión como <b>Cajero</b>, el menú lateral solo muestra los módulos de acceso general. "
        "Los módulos de administración quedan ocultos automáticamente por seguridad.",
        kind="warning"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 03 — PUNTO DE VENTA ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(3, "Punto de Venta — POS", "Cómo registrar ventas de forma rápida y eficiente")
    sub_label("Flujo completo de una venta")
    flow_diagram([
        ("🔍", "Buscar\nProducto"),
        ("🛒", "Agregar\nCarrito"),
        ("💰", "Elegir\nPago"),
        ("✅", "Cobrar\nF10"),
        ("🧾", "Ticket\nAutomatic"),
    ])
    sub_label("Pasos detallados")
    step_boxes([
        ("Abrir el POS",
         "Presionar <b>F1</b> o hacer clic en 'Nueva Venta' en el menú lateral. "
         "El sistema carga todos los productos activos con imagen, precio y stock."),
        ("Buscar el producto",
         "Presionar <b>F2</b> o <b>F3</b> para enfocar el buscador automáticamente. "
         "Escribir nombre, marca, laboratorio o código de barras. La búsqueda es en tiempo real."),
        ("Agregar al carrito",
         "Presionar <b>Enter</b> o <b>Tab</b> para agregar el primer resultado. "
         "También se puede hacer clic en la tarjeta del producto. "
         "El carrito muestra cantidad, precio unitario y subtotal."),
        ("Ajustar cantidad y descuento",
         "En el carrito usar + / − para modificar la cantidad. "
         "Doble clic en el precio de un ítem para aplicar descuento individual. "
         "El campo '% Desc' en la parte superior aplica descuento global a toda la venta."),
        ("Seleccionar método de pago",
         "Hacer clic en <b>Efectivo</b>, <b>Tarjeta</b> o <b>Transferencia</b>. "
         "Con terminal Mercado Pago configurada, el cobro con tarjeta va directo al dispositivo."),
        ("Cobrar — F10",
         "Para efectivo: presionar <b>F8</b> para ir al campo de monto, "
         "ingresar el dinero recibido, el sistema calcula el cambio. "
         "Presionar <b>F10</b> para confirmar y procesar la venta."),
        ("Ticket automático",
         "El ticket se genera automáticamente con folio, fecha, productos, subtotal, IVA 16% y total. "
         "Se imprime si hay impresora configurada. También disponible como PDF."),
    ])
    sp(0.1)
    tip_box(
        "<b>Productos con receta:</b> Si un medicamento requiere receta médica, el sistema muestra una "
        "alerta al agregarlo al carrito. Se puede asociar al expediente del cliente para el historial clínico.",
        kind="info"
    )
    tip_box(
        "<b>Cajero de prueba:</b> El usuario especial 'cajero' simula ventas completas sin registrarlas "
        "en la base de datos ni descontar stock. Útil para capacitar nuevo personal.",
        kind="warning"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 04 — INVENTARIO ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(4, "Inventario", "Gestión completa de productos, stock y caducidades")
    story.append(Paragraph(
        "El inventario centraliza toda la información de los medicamentos y productos de la farmacia. "
        "El stock se actualiza automáticamente con cada venta desde cualquier PC conectada al sistema.",
        s_just))
    sp(0.25)
    sub_label("Funciones del módulo")
    feat_list([
        ("Búsqueda avanzada",
         "Buscar por nombre, marca, laboratorio, código de barras o categoría. Sin distinción de mayúsculas/minúsculas."),
        ("Agregar producto",
         "Botón '+' verde en la barra superior. Campos obligatorios: nombre, precio de venta, stock inicial. "
         "Opcionales: marca, código de barras, precio de costo, stock mínimo, imagen."),
        ("Editar producto",
         "Clic en el ícono de lápiz ✏ en la fila del producto. Modificar cualquier campo: precio, descripción, imagen, etc."),
        ("Gestión de lotes y caducidad",
         "Cada producto puede tener múltiples lotes con fecha de caducidad y cantidad. "
         "Alertas automáticas cuando un lote vence en menos de 30 días."),
        ("Ajuste físico de inventario",
         "Botón ◎ junto al producto. Corregir diferencia entre conteo físico y sistema. "
         "Se registra el motivo y queda en el historial de movimientos."),
        ("Descuento permanente",
         "Campo '% Desc' en el detalle del producto. Se aplica automáticamente en el POS cada vez que se vende."),
        ("Alertas de stock mínimo",
         "Cuando el stock llega al nivel mínimo configurado, la fila se resalta en rojo como advertencia visual."),
        ("Piezas sueltas",
         "Productos que se venden por pieza individual (pastillas sueltas). "
         "Campo separado de stock de cajas completas."),
    ])
    sp(0.2)
    sub_label("Cómo gestionar lotes de caducidad")
    lote_data = [
        [Paragraph("<b>Paso</b>", s_hdr), Paragraph("<b>Acción</b>", s_hdr)],
        [Paragraph("1", s_ctrb), Paragraph("En el inventario, hacer clic en el ícono de lotes 🗂 del producto.", s_body)],
        [Paragraph("2", s_ctrb), Paragraph("Hacer clic en 'Agregar Lote'. Ingresar: número de lote, cantidad y fecha de caducidad.", s_body)],
        [Paragraph("3", s_ctrb), Paragraph("El sistema registra el lote. Los que vencen en menos de 30 días se resaltan en amarillo.", s_body)],
        [Paragraph("4", s_ctrb), Paragraph("Al realizar una venta, el sistema descuenta del lote más próximo a vencer (FIFO automático).", s_body)],
        [Paragraph("5", s_ctrb), Paragraph("Los lotes vencidos se muestran en rojo. Se pueden eliminar manualmente cuando se retiren del inventario.", s_body)],
    ]
    grid_table(lote_data, [1.5 * cm, None])
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 05 — CONTROL DE CAJA ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(5, "Control de Caja", "Turnos, retiros de efectivo y resumen financiero")
    sub_label("Ciclo de un turno de caja")
    flow_diagram([
        ("🔓", "Abrir\nTurno"),
        ("💊", "Ventas\ndel día"),
        ("💸", "Retiros"),
        ("🔒", "Cerrar\nTurno"),
        ("📋", "Reporte"),
    ])
    sub_label("Pasos del turno")
    step_boxes([
        ("Abrir turno",
         "Ir a <b>Control de Caja</b> → botón 'Abrir Turno'. "
         "Ingresar el monto de apertura (efectivo físico con el que inicia la caja). "
         "El sistema registra la hora de inicio y el usuario que abre."),
        ("Ventas del día",
         "Registrar ventas normalmente desde el POS durante el turno. "
         "El sistema acumula el total desglosado por método de pago: efectivo, tarjeta y transferencia."),
        ("Registrar retiro de efectivo",
         "Si se retira efectivo durante el turno, registrarlo como retiro. "
         "<b>Tipo Personal:</b> ganancia retirada. "
         "<b>Tipo Inversión:</b> dinero destinado a recomprar mercancía. "
         "El sistema valida que el monto no exceda el disponible."),
        ("Cerrar turno",
         "Botón 'Cerrar Turno'. El sistema calcula ganancia bruta, total de retiros, "
         "efectivo esperado y diferencia si se ingresa el conteo físico."),
    ])
    sp(0.1)
    sub_label("Fórmulas de cálculo automático")
    calc_data = [
        [Paragraph("<b>Concepto</b>", s_hdr), Paragraph("<b>Fórmula</b>", s_hdr)],
        [Paragraph("Ganancia bruta", s_bold),
         Paragraph("Total ventas − Costo de productos vendidos", s_body)],
        [Paragraph("Ganancia disponible", s_bold),
         Paragraph("Ganancia bruta − Retiros personales ya registrados", s_body)],
        [Paragraph("Efectivo esperado en caja", s_bold),
         Paragraph("Monto apertura + Ventas en efectivo − Retiros del turno", s_body)],
        [Paragraph("Capital de inversión disponible", s_bold),
         Paragraph("Costo total vendido − Retiros de inversión registrados", s_body)],
        [Paragraph("Diferencia de caja", s_bold),
         Paragraph("Efectivo físico contado − Efectivo esperado  (0 = cuadre exacto)", s_body)],
    ]
    grid_table(calc_data, [6 * cm, None])
    tip_box(
        "Los retiros y cortes se sincronizan automáticamente entre todas las PCs conectadas. "
        "Si hiciste un retiro en otra computadora y no aparece, presiona el botón <b>Sync</b> "
        "en Control de Caja para forzar la actualización desde la nube.",
        kind="info"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 06 — SINCRONIZACIÓN MULTI-PC ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(6, "Sincronización Multi-PC", "Arquitectura en red con Turso Cloud")
    story.append(Paragraph(
        "El sistema usa <b>Turso</b> (base de datos en la nube LibSQL) para sincronizar datos entre "
        "múltiples computadoras. Cada PC mantiene una copia local para funcionar sin internet, "
        "y los cambios se sincronizan automáticamente cada 30 segundos.",
        s_just))
    sp(0.3)
    sub_label("Diagrama de arquitectura")

    # Network diagram
    pc_style = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ])
    cloud_style = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_CYAN),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
    ])

    def net_box(txt, bg):
        bt = Table([[Paragraph(txt, sty("nb", fontSize=9, textColor=C_WHITE,
                                        fontName="Helvetica-Bold", alignment=TA_CENTER, leading=13))]],
                   colWidths=[3.5 * cm], rowHeights=[1.4 * cm])
        bt.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), bg),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return bt

    net = Table([[
        net_box("🖥️  PC-A\nCajero 1", C_BLUE),
        Paragraph("⇄", sty("a1", fontSize=18, textColor=C_MUTED, alignment=TA_CENTER)),
        net_box("☁️  TURSO\nCLOUD", C_CYAN),
        Paragraph("⇄", sty("a2", fontSize=18, textColor=C_MUTED, alignment=TA_CENTER)),
        net_box("🖥️  PC-B\nCajero 2", C_BLUE),
    ]], colWidths=[3.5 * cm, None, 3.5 * cm, None, 3.5 * cm])
    net.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(KeepTogether(net))
    sp(0.3)

    sub_label("Qué se sincroniza y con qué frecuencia")
    sync_data = [
        [Paragraph("<b>Datos</b>", s_hdr),
         Paragraph("<b>Descripción</b>", s_hdr),
         Paragraph("<b>Frecuencia</b>", s_hdr)],
        [Paragraph("Productos / Stock", s_bold),
         Paragraph("Precios, stock, marca, imagen, descripción", s_body),
         Paragraph("Inmediata tras venta", s_mut)],
        [Paragraph("Ventas", s_bold),
         Paragraph("Historial completo de todas las ventas por cualquier PC", s_body),
         Paragraph("Inmediata", s_mut)],
        [Paragraph("Retiros de caja", s_bold),
         Paragraph("Retiros de efectivo de cualquier turno o PC", s_body),
         Paragraph("Inmediata + Sync", s_mut)],
        [Paragraph("Cortes de caja", s_bold),
         Paragraph("Historial de turnos abiertos y cerrados", s_body),
         Paragraph("Inmediata", s_mut)],
        [Paragraph("Clientes", s_bold),
         Paragraph("Expedientes, historial clínico y contactos", s_body),
         Paragraph("Cada 30 segundos", s_mut)],
        [Paragraph("Usuarios", s_bold),
         Paragraph("Cuentas, roles y contraseñas de empleados", s_body),
         Paragraph("Cada 30 segundos", s_mut)],
        [Paragraph("Lotes / Caducidad", s_bold),
         Paragraph("Lotes de productos con fecha de vencimiento", s_body),
         Paragraph("Inmediata", s_mut)],
    ]
    grid_table(sync_data, [4 * cm, None, 3.8 * cm])
    tip_box(
        "<b>Sin internet:</b> El sistema funciona al 100% sin conexión. "
        "Los datos se guardan localmente (SQLite) y se sincronizan automáticamente "
        "con la nube en cuanto se restaura la conexión a internet.",
        kind="success"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 07 — MÉTODOS DE PAGO ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(7, "Métodos de Pago", "Efectivo, tarjeta y terminal Mercado Pago Point")
    sub_label("Comparación de métodos")
    pay_data = [
        [Paragraph("<b>💵  Efectivo</b>",
                   sty("ph1", fontSize=10, textColor=C_WHITE, fontName="Helvetica-Bold",
                       alignment=TA_CENTER)),
         Paragraph("<b>💳  Tarjeta</b>",
                   sty("ph2", fontSize=10, textColor=C_WHITE, fontName="Helvetica-Bold",
                       alignment=TA_CENTER)),
         Paragraph("<b>📲  Transferencia</b>",
                   sty("ph3", fontSize=10, textColor=C_WHITE, fontName="Helvetica-Bold",
                       alignment=TA_CENTER))],
        [Paragraph("El cliente paga con billetes o monedas en mano.", s_body),
         Paragraph("Cobro con tarjeta bancaria de débito o crédito.", s_body),
         Paragraph("Pago por SPEI, CoDi o app bancaria del cliente.", s_body)],
        [Paragraph("Ingresar monto recibido → el sistema calcula el cambio automáticamente.", s_body),
         Paragraph("Con terminal MP: el monto se envía automáticamente al dispositivo.", s_body),
         Paragraph("El cliente transfiere antes de confirmar la venta.", s_body)],
        [Paragraph("<b>Atajo:</b> F8 enfoca el campo de monto directamente.", s_mut),
         Paragraph("<b>Sin terminal:</b> cajero procesa en el dispositivo y confirma en sistema.", s_mut),
         Paragraph("<b>No genera cambio</b> — verificar recepción antes de confirmar.", s_mut)],
    ]
    pay_t = Table(pay_data, colWidths=[cw / 3] * 3)
    pay_t.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, 0), C_BLUE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_GRAY, C_BLUE_L]),
        ("GRID",           (0, 0), (-1, -1), 0.25, C_GRAY_B),
        ("LINEBELOW",      (0, 0), (-1, 0),  1.5, C_BLUE),
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
    ]))
    story.append(KeepTogether(pay_t))
    sp(0.3)

    sub_label("Configurar terminal Mercado Pago Point")
    step_boxes([
        ("Obtener Access Token",
         "Ingresar a <b>developers.mercadopago.com</b> con la cuenta de Mercado Pago de la farmacia. "
         "En 'Credenciales de producción' copiar el Access Token."),
        ("Configurar en el sistema",
         "Ir a <b>Configuración → Terminal de Pago</b>. "
         "Pegar el Access Token en el campo correspondiente y presionar 'Guardar'."),
        ("Detectar el dispositivo",
         "Presionar <b>'Detectar Terminales'</b>. El sistema consulta la API de Mercado Pago "
         "y muestra los dispositivos vinculados. Copiar el Device ID del terminal."),
        ("Activar modo PDV",
         "Asegurarse de que la terminal esté encendida y conectada a WiFi. "
         "Presionar <b>'Activar Modo PDV'</b>. La terminal queda lista para recibir cobros."),
        ("Cobrar con tarjeta",
         "En el POS seleccionar 'Tarjeta' y presionar 'Cobrar'. "
         "El monto aparece automáticamente en la terminal. "
         "El cliente inserta/acerca su tarjeta y el sistema recibe confirmación."),
    ])
    tip_box(
        "<b>Modelo compatible:</b> <b>Point Smart 2</b> (SMART2). "
        "El modelo Point Mini (ME30S / NEWLAND) no soporta la API de integración automática. "
        "Con el Mini se cobra manualmente en el dispositivo y se registra 'Tarjeta' en el sistema.",
        kind="warning"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 08 — GESTIÓN DE CLIENTES ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(8, "Gestión de Clientes", "Expedientes, historial de compras y recetas médicas")
    story.append(Paragraph(
        "El módulo de Clientes permite llevar un expediente médico completo de cada paciente, "
        "incluyendo medicamentos actuales, alergias, antecedentes y recetas. "
        "El historial de compras se actualiza automáticamente con cada venta asociada.",
        s_just))
    sp(0.25)
    sub_label("Información del expediente")
    clt_data = [
        [Paragraph("<b>Campo</b>", s_hdr), Paragraph("<b>Descripción</b>", s_hdr)],
        [Paragraph("Datos básicos", s_bold),
         Paragraph("Nombre completo, teléfono, fecha de nacimiento, CURP, correo electrónico", s_body)],
        [Paragraph("Historial de compras", s_bold),
         Paragraph("Todas las ventas asociadas al cliente: fecha, productos comprados y monto", s_body)],
        [Paragraph("Medicamentos actuales", s_bold),
         Paragraph("Lista de medicamentos que toma el paciente regularmente con dosis y frecuencia", s_body)],
        [Paragraph("Alergias", s_bold),
         Paragraph("Alergias a medicamentos o sustancias. El sistema muestra alerta al vender productos relacionados", s_body)],
        [Paragraph("Antecedentes médicos", s_bold),
         Paragraph("Enfermedades crónicas, cirugías y otras condiciones relevantes para la atención", s_body)],
        [Paragraph("Recetas médicas", s_bold),
         Paragraph("Medicamento, dosis, frecuencia, duración y médico que prescribe. Se puede marcar con sello de receta", s_body)],
        [Paragraph("Signos vitales", s_bold),
         Paragraph("Registro de presión arterial y peso para seguimiento de pacientes crónicos", s_body)],
    ]
    grid_table(clt_data, [4.5 * cm, None])
    tip_box(
        "Al hacer una venta en el POS, se puede asociar al cliente desde el selector superior del carrito. "
        "La venta queda registrada en su historial automáticamente para consultas futuras.",
        kind="info"
    )
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 09 — CONFIGURACIÓN ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(9, "Configuración del Sistema", "Ajustes, credenciales de APIs y respaldos de datos")
    tip_box(
        "Esta sección es exclusiva del Administrador. Los cambios en credenciales de API "
        "afectan el funcionamiento completo del sistema. No compartir ni modificar tokens "
        "sin conocimiento técnico. Siempre hacer un respaldo antes de cambios mayores.",
        kind="error"
    )
    sp(0.1)
    sub_label("Ajustes disponibles")
    cfg_data = [
        [Paragraph("<b>Ajuste</b>", s_hdr),
         Paragraph("<b>Descripción</b>", s_hdr),
         Paragraph("<b>Impacto</b>", s_hdr)],
        [Paragraph("Datos de la farmacia", s_bold),
         Paragraph("Nombre, dirección, teléfono, RFC — aparecen en todos los tickets impresos", s_body),
         Paragraph("Tickets de venta", s_mut)],
        [Paragraph("Turno automático", s_bold),
         Paragraph("Hora de apertura y cierre automático del turno de caja (activar/desactivar)", s_body),
         Paragraph("Control de caja", s_mut)],
        [Paragraph("Turso / Nube", s_bold),
         Paragraph("URL y token de acceso a la base de datos en la nube Turso (LibSQL)", s_body),
         Paragraph("Sincronización multi-PC", s_mut)],
        [Paragraph("Cloudinary", s_bold),
         Paragraph("Cloud name, API Key y Secret para almacenar imágenes de productos en la nube", s_body),
         Paragraph("Fotos de productos", s_mut)],
        [Paragraph("Terminal MP", s_bold),
         Paragraph("Access Token y Device ID de Mercado Pago Point para cobros automáticos con tarjeta", s_body),
         Paragraph("Cobro con tarjeta", s_mut)],
        [Paragraph("Respaldo de BD", s_bold),
         Paragraph("Exportar copia de seguridad completa de todos los datos en formato .db (SQLite)", s_body),
         Paragraph("Recuperación ante fallas", s_mut)],
        [Paragraph("Restaurar BD", s_bold),
         Paragraph("Cargar un archivo .db de respaldo. REEMPLAZA TODOS los datos actuales sin excepción", s_body),
         Paragraph("⚠ Irreversible", sty("irr1", fontSize=8, textColor=C_RED,
                                          fontName="Helvetica-Bold", leading=12))],
        [Paragraph("Purgar datos", s_bold),
         Paragraph("Eliminar ventas/historial o todos los datos incluyendo Turso. Confirmar con contraseña", s_body),
         Paragraph("⚠ Irreversible", sty("irr2", fontSize=8, textColor=C_RED,
                                          fontName="Helvetica-Bold", leading=12))],
    ]
    grid_table(cfg_data, [4.5 * cm, None, 3.2 * cm])

    sub_label("Gestión de empleados")
    step_boxes([
        ("Crear nuevo usuario",
         "Ir a <b>Empleados</b> → botón '+'. Completar: nombre completo, nombre de usuario y contraseña. "
         "Rol <b>Cajero</b>: acceso al POS, inventario y clientes. "
         "Rol <b>Administrador</b>: acceso completo al sistema."),
        ("Cambiar contraseña",
         "En la lista de empleados, clic en el ícono de contraseña 🔑. "
         "El administrador puede cambiar la contraseña de cualquier usuario sin necesitar la contraseña actual."),
        ("Desactivar empleado",
         "Al desactivar un usuario, no puede iniciar sesión pero su historial de ventas se conserva íntegro. "
         "Recomendado cuando un empleado deja de trabajar en la farmacia."),
    ])
    pb()

    # ─────────────────────────────────────────────────────────────────────────
    # ═══ 10 — ACTUALIZACIONES ═══
    # ─────────────────────────────────────────────────────────────────────────
    section_banner(10, "Actualizaciones del Sistema", "Cómo mantener el POS siempre al día")
    story.append(Paragraph(
        "El sistema verifica automáticamente si hay nuevas versiones disponibles cada vez que se inicia. "
        "Las actualizaciones se distribuyen como instalador (.exe) y se aplican sin intervención técnica.",
        s_just))
    sp(0.25)
    sub_label("Proceso de actualización paso a paso")
    step_boxes([
        ("Detección automática",
         "Al iniciar sesión, el sistema consulta GitHub Releases silenciosamente. "
         "Si hay una versión más reciente disponible, el botón <b>'Actualizar'</b> en la barra superior "
         "se resalta en amarillo mostrando el número de versión disponible (ej. ⬆ v2.3.19)."),
        ("Revisar versiones disponibles",
         "Hacer clic en el botón 'Actualizar'. Se abre una ventana con la lista de versiones disponibles, "
         "la versión instalada actualmente y las notas de cada actualización."),
        ("Seleccionar e instalar",
         "Seleccionar la versión deseada en la lista (la más reciente está pre-seleccionada) "
         "y presionar <b>'Instalar'</b>. La descarga inicia en segundo plano."),
        ("Progreso de descarga",
         "Una tarjeta de progreso aparece en la esquina superior derecha mostrando el porcentaje de descarga. "
         "El sistema sigue funcionando normalmente durante la descarga."),
        ("Instalación y reinicio automático",
         "Al completar la descarga (100%), el instalador se ejecuta automáticamente. "
         "La aplicación se cierra y reabre con la nueva versión instalada. "
         "Los datos de la base de datos <b>no se eliminan</b> con la actualización."),
        ("Verificar la versión",
         "Tras reiniciar, el botón 'Actualizar' desaparece si ya se tiene la versión más reciente. "
         "La versión instalada se muestra en el PDF del Manual (sección de portada)."),
    ])
    sp(0.15)
    tip_box(
        f"<b>Versión actual del sistema:</b>  v{cfg.VERSION}"
        f"  ·  <b>Manual generado:</b>  {now_str}<br/>"
        "Para soporte técnico o reportar errores, contactar al administrador del sistema.",
        kind="success"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # PAGE HEADER / FOOTER (todas excepto portada)
    # ─────────────────────────────────────────────────────────────────────────
    def _on_cover(canvas, doc):
        pass

    def _on_page(canvas, doc):
        canvas.saveState()
        # Header
        canvas.setStrokeColorRGB(0.886, 0.91, 0.941)
        canvas.setLineWidth(0.5)
        canvas.line(1.8 * cm, H - 1.7 * cm, W - 1.8 * cm, H - 1.7 * cm)
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColorRGB(0.114, 0.129, 0.251)
        canvas.drawString(1.8 * cm, H - 1.4 * cm, cfg.PHARMACY_NAME)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColorRGB(0.392, 0.455, 0.545)
        canvas.drawRightString(W - 1.8 * cm, H - 1.4 * cm,
                               f"Manual de Usuario  ·  v{cfg.VERSION}")
        # Footer
        canvas.setStrokeColorRGB(0.886, 0.91, 0.941)
        canvas.line(1.8 * cm, 1.6 * cm, W - 1.8 * cm, 1.6 * cm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColorRGB(0.392, 0.455, 0.545)
        canvas.drawString(1.8 * cm, 1.2 * cm, now_str)
        canvas.drawCentredString(
            W / 2, 1.2 * cm,
            f"{cfg.PHARMACY_ADDRESS}  ·  {cfg.PHARMACY_PHONE}"
        )
        canvas.drawRightString(W - 1.8 * cm, 1.2 * cm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        path,
        pagesize=letter,
        rightMargin=1.8 * cm, leftMargin=1.8 * cm,
        topMargin=2.2 * cm, bottomMargin=2.4 * cm,
        title=f"Manual de Usuario — {cfg.PHARMACY_NAME}",
        author=cfg.PHARMACY_NAME,
    )
    doc.build(story, onFirstPage=_on_cover, onLaterPages=_on_page)
