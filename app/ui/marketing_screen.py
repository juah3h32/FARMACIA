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

# Fuentes — Montserrat (busca sistema y carpeta usuario, fallback Arial)
_SYS_FONTS  = Path("C:/Windows/Fonts")
_USER_FONTS = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"

def _font_path(name: str, fallback: str) -> str | None:
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

        # Texto extra
        ctk.CTkLabel(left, text="Texto adicional (opcional):",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MUTED).grid(row=14, column=0, padx=12, pady=(8, 0), sticky="w")

        self._promo_texto_extra = ctk.CTkEntry(left, height=34,
                                                placeholder_text="Ej: Por tiempo limitado")
        self._promo_texto_extra.grid(row=15, column=0, padx=12, pady=(0, 8), sticky="ew")

        # Separador
        ctk.CTkFrame(left, height=1, fg_color=BORDER).grid(
            row=16, column=0, sticky="ew", padx=12, pady=8)

        # Botones
        ctk.CTkButton(
            left, text="👁 Vista previa",
            height=36, corner_radius=8,
            fg_color=GREEN, text_color=WHITE, hover_color="#15803D",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._preview_promo,
        ).grid(row=17, column=0, padx=12, pady=(0, 6), sticky="ew")

        ctk.CTkButton(
            left, text="💾 Guardar imagen PNG",
            height=36, corner_radius=8,
            fg_color=BLUE, text_color=WHITE, hover_color=BLUE_D,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._guardar_promo,
        ).grid(row=18, column=0, padx=12, pady=(0, 12), sticky="ew")

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
            "producto":       self._selected_prod,
            "precio_promo":   precio_promo,
            "precio_tachado": precio_tachado,
            "texto_extra":    self._promo_texto_extra.get().strip(),
            "usar_imagen":    self._usar_imagen_var.get() and bool(self._selected_prod.imagen_url),
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
    """Wrap product name to lines of at most max_chars, respecting word boundaries."""
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
                           usar_imagen: bool = False) -> Image.Image:
    prod_img = None
    if usar_imagen and producto.imagen_url:
        prod_img = _fetch_cloudinary_image(producto.imagen_url)

    if prod_img is not None:
        return _layout_blanco(producto, precio_promo, precio_tachado, texto_extra, prod_img)
    else:
        return _layout_azul(producto, precio_promo, precio_tachado, texto_extra)


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
                    prod_img: Image.Image) -> Image.Image:
    W, H   = 1080, 1080
    HEADER = 138
    FOOTER = 72

    NAVY  = (29,  33,  64)    # #1d2140
    BRAND = (60,  115, 185)   # #3c73b9
    DARK  = (5,   15,  48)
    WHITE = (255, 255, 255)
    GRAY  = (80,  100, 140)
    SILV  = (155, 175, 215)
    RED   = (215, 42,  42)
    GREEN = (15,  140, 55)

    img  = Image.new("RGB", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # ── Header #1d2140 ───────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, HEADER)], fill=NAVY)
    _paste_logo(img, draw, 0, 0, W, HEADER, white=True)

    # Barra #3c73b9 bajo el header
    draw.rectangle([(0, HEADER), (W, HEADER + 5)], fill=BRAND)

    cy = HEADER + 5 + 28   # top del primer elemento

    # ── Badge OFERTA (pill manual — sin artefactos de esquinas) ─────────────
    bw, bh = 230, 36
    bx = (W - bw) // 2
    r = bh // 2
    draw.ellipse([bx, cy, bx + bh, cy + bh], fill=RED)
    draw.ellipse([bx + bw - bh, cy, bx + bw, cy + bh], fill=RED)
    draw.rectangle([bx + r, cy, bx + bw - r, cy + bh], fill=RED)
    draw.text((W // 2, cy + bh // 2), "OFERTA ESPECIAL",
              font=_pil_font(FONT_BOLD, 17), fill=WHITE, anchor="mm")
    cy += bh + 30   # gap explícito badge → nombre

    # ── Nombre (anchor="mt": y = TOP del texto, sin overlap garantizado) ──────
    f_name = _pil_font(FONT_BLACK, 62)
    lines  = _wrap_name(producto.nombre.upper(), 20)
    for i, line in enumerate(lines[:2]):
        bb = draw.textbbox((W // 2, cy), line, font=f_name, anchor="mt")
        draw.text((W // 2, cy), line, font=f_name, fill=DARK, anchor="mt")
        cy = bb[3] + (8 if i < len(lines[:2]) - 1 else 0)
    cy += 18   # gap nombre → presentación

    # ── Presentación deduplicada ──────────────────────────────────────────────
    raw_sub = [producto.presentacion, producto.concentracion, producto.contenido]
    sub = list(dict.fromkeys(x for x in raw_sub if x))
    if sub:
        f_sub = _pil_font(FONT_SEMI, 21)
        bb = draw.textbbox((W // 2, cy), "  ·  ".join(sub), font=f_sub, anchor="mt")
        draw.text((W // 2, cy), "  ·  ".join(sub), font=f_sub, fill=GRAY, anchor="mt")
        cy = bb[3] + 20
    else:
        cy += 6

    # ── Imagen — fondo blanco, sin caja, sin oval, tamaño máximo ─────────────
    IMG_H  = 290
    MAX_IW = 960
    try:
        pimg  = prod_img.convert("RGBA")
        iw, ih = pimg.size
        scale  = min(MAX_IW / iw, IMG_H / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        pfit   = pimg.resize((nw, nh), Image.LANCZOS)
        px = (W - nw) // 2
        py = cy + (IMG_H - nh) // 2
        img.paste(pfit.convert("RGB"), (px, py), pfit.split()[3])
    except Exception:
        pass
    cy += IMG_H + 24

    # ── Separador fino ────────────────────────────────────────────────────────
    draw.line([(W // 4, cy), (3 * W // 4, cy)], fill=(200, 215, 245), width=1)
    cy += 22

    # ── Precio tachado (anchor="mt", medido con textbbox) ────────────────────
    f_tach = _pil_font(FONT_SEMI, 38)
    txt_t  = f"${precio_tachado:,.2f}"
    bb = draw.textbbox((W // 2, cy), txt_t, font=f_tach, anchor="mt")
    draw.text((W // 2, cy), txt_t, font=f_tach, fill=SILV, anchor="mt")
    mid_y = (bb[1] + bb[3]) // 2
    draw.line([(bb[0] - 4, mid_y), (bb[2] + 4, mid_y)], fill=RED, width=4)
    cy = bb[3] + 26   # gap medido tachado → precio (sin overlap)

    # ── Precio PROMO — Montserrat Black 88px ──────────────────────────────────
    f_price = _pil_font(FONT_BLACK, 88)
    txt_p   = f"${precio_promo:,.2f}"
    bb = draw.textbbox((W // 2, cy), txt_p, font=f_price, anchor="mt")
    draw.text((W // 2, cy), txt_p, font=f_price, fill=DARK, anchor="mt")
    cy = bb[3] + 14

    # ── Badge ahorro ──────────────────────────────────────────────────────────
    ahorro = precio_tachado - precio_promo
    if ahorro > 0.01:
        sw, sh = 254, 36
        sx = (W - sw) // 2
        draw.rounded_rectangle([sx, cy, sx + sw, cy + sh], radius=18, fill=GREEN)
        draw.text((W // 2, cy + sh // 2), f"¡AHORRAS ${ahorro:,.2f}!",
                  font=_pil_font(FONT_BOLD, 21), fill=WHITE, anchor="mm")
        cy += sh + 10

    if texto_extra:
        draw.text((W // 2, cy + 8), texto_extra,
                  font=_pil_font(FONT_ITALIC, 20), fill=GRAY, anchor="mt")

    # ── Footer NAVY + barra #3c73b9 ───────────────────────────────────────────
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
