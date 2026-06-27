"""Generador y exportador de códigos de barras y QR para productos."""
import io
import threading
from tkinter import messagebox, filedialog
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from PIL import Image

from app.database.connection import get_db_session
from app.database.models import Producto


# ─── helpers ──────────────────────────────────────────────────────────────────

def _barcode_img(texto: str, fmt: str) -> Image.Image:
    if fmt == "qr":
        import qrcode
        qr = qrcode.QRCode(box_size=7, border=2)
        qr.add_data(texto)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").get_image()
    else:
        import barcode
        from barcode.writer import ImageWriter
        writer = ImageWriter()
        writer.set_options({
            "module_height": 12,
            "quiet_zone": 3,
            "font_size": 9,
            "text_distance": 3,
            "write_text": True,
        })
        buf = io.BytesIO()
        bc_class = barcode.get_barcode_class(fmt)
        bc = bc_class(texto, writer=writer)
        bc.write(buf)
        buf.seek(0)
        img = Image.open(buf)
        img.load()
        return img.copy()


def _label_img(nombre: str, precio: float, codigo: str, fmt: str,
               label_w: int = 380) -> Image.Image:
    """Compose label: barcode/QR + product name + price."""
    from PIL import ImageDraw, ImageFont

    bc = _barcode_img(codigo, fmt)

    bc_w = label_w - 20
    ratio = bc_w / bc.width
    bc_h = max(int(bc.height * ratio), 10)
    bc = bc.resize((bc_w, bc_h), Image.LANCZOS)

    label_h = bc_h + 72
    label = Image.new("RGB", (label_w, label_h), "white")
    label.paste(bc, (10, 5))

    draw = ImageDraw.Draw(label)
    try:
        fnt_big = ImageFont.truetype("arial.ttf", 13)
        fnt_sm  = ImageFont.truetype("arial.ttf", 11)
    except Exception:
        fnt_big = ImageFont.load_default()
        fnt_sm  = fnt_big

    cx = label_w // 2
    y0 = bc_h + 10
    name = (nombre[:44] + "…") if len(nombre) > 44 else nombre
    draw.text((cx, y0), name, fill="black", font=fnt_big, anchor="mt")
    draw.text((cx, y0 + 22), f"$ {precio:.2f}", fill="#333333", font=fnt_sm, anchor="mt")
    return label


def _ean13_check(digits12: str) -> str:
    """Compute EAN-13 check digit for 12-digit string."""
    s = sum(int(d) * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits12))
    return str((10 - s % 10) % 10)


def _export_pdf_labels(labels: list, out_path: str, cols: int = 3, rows: int = 8):
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.utils import ImageReader

    page_w, page_h = letter
    margin = 10 * mm
    label_w = (page_w - 2 * margin) / cols
    label_h = (page_h - 2 * margin) / rows

    c = rl_canvas.Canvas(out_path, pagesize=letter)
    col_i, row_i = 0, 0
    first_page = True

    for img, _ in labels:
        if not first_page and col_i == 0 and row_i == 0:
            c.showPage()
        first_page = False

        x = margin + col_i * label_w
        y = page_h - margin - (row_i + 1) * label_h

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        ir = ImageReader(buf)
        iw, ih = ir.getSize()
        pad = 3 * mm
        max_w = label_w - 2 * pad
        max_h = label_h - 2 * pad
        scale = min(max_w / iw, max_h / ih)
        draw_w = iw * scale
        draw_h = ih * scale
        img_x = x + pad + (max_w - draw_w) / 2
        img_y = y + pad + (max_h - draw_h) / 2

        c.drawImage(ir, img_x, img_y, width=draw_w, height=draw_h)
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(0.5)
        c.rect(x + 1, y + 1, label_w - 2, label_h - 2)

        col_i += 1
        if col_i >= cols:
            col_i = 0
            row_i += 1
            if row_i >= rows:
                col_i, row_i = 0, 0

    c.save()


# ─── Dialog ───────────────────────────────────────────────────────────────────

class CodigosDialog(ctk.CTkToplevel):
    def __init__(self, parent, producto_id: int | None = None):
        super().__init__(parent)
        self.title("🔲 Generador de Códigos QR / Barras")
        self.geometry("920x660")
        self.minsize(760, 540)
        self.grab_set()

        self._selected_pid: int | None = None
        self._preview_img = None
        self._productos: list = []
        self._fmt_var = tk.StringVar(value="code128")
        self._filter_sin_codigo = tk.BooleanVar(value=False)
        self._pending_preview = False

        self._build_ui()
        self._load_products()

        if producto_id:
            self.after(300, lambda: self._select_by_id(producto_id))

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=2)
        self.grid_columnconfigure(1, weight=3)
        self.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color="#2563EB", height=50)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        hdr.grid_propagate(False)
        hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(hdr, text="🔲  Generador de Códigos QR y de Barras",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="white").grid(row=0, column=0, padx=16, sticky="w", pady=10)

        # ── Left panel ───────────────────────────────────────────────────────
        left = ctk.CTkFrame(self, corner_radius=0, fg_color="#F8FAFF",
                            border_width=1, border_color="#E2E8F0")
        left.grid(row=1, column=0, sticky="nsew", padx=(10, 4), pady=10)
        left.grid_rowconfigure(2, weight=1)
        left.grid_columnconfigure(0, weight=1)

        search_row = ctk.CTkFrame(left, fg_color="transparent")
        search_row.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 2))
        search_row.grid_columnconfigure(0, weight=1)

        self.entry_search = ctk.CTkEntry(
            search_row, placeholder_text="🔍 Nombre o código...", height=32)
        self.entry_search.grid(row=0, column=0, sticky="ew")
        self.entry_search.bind("<KeyRelease>", lambda e: self._load_products())

        ctk.CTkCheckBox(left, text="Solo sin código",
                        variable=self._filter_sin_codigo,
                        command=self._load_products,
                        font=ctk.CTkFont(size=11)
                        ).grid(row=1, column=0, sticky="w", padx=10, pady=2)

        # Tree
        style = ttk.Style()
        style.configure("Cod.Treeview", rowheight=26, font=("Segoe UI", 10))
        style.configure("Cod.Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.map("Cod.Treeview", background=[("selected", "#EFF6FF")],
                  foreground=[("selected", "#2563EB")])

        tf = ctk.CTkFrame(left, fg_color="white", corner_radius=6)
        tf.grid(row=2, column=0, sticky="nsew", padx=8, pady=(2, 8))
        tf.grid_rowconfigure(0, weight=1)
        tf.grid_columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(tf, columns=("nombre", "codigo"),
                                  show="headings", style="Cod.Treeview",
                                  selectmode="browse")
        self.tree.heading("nombre", text="Producto")
        self.tree.heading("codigo", text="Código")
        self.tree.column("nombre", width=160, stretch=True)
        self.tree.column("codigo", width=90, stretch=False)

        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.tag_configure("sin_cod", foreground="#D97706")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        # ── Right panel ───────────────────────────────────────────────────────
        right = ctk.CTkFrame(self, corner_radius=10, fg_color="white",
                             border_width=1, border_color="#E2E8F0")
        right.grid(row=1, column=1, sticky="nsew", padx=(4, 10), pady=10)
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        # Type selector
        type_row = ctk.CTkFrame(right, fg_color="transparent")
        type_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 0))
        ctk.CTkLabel(type_row, text="Tipo de código:",
                     font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 10))
        for lbl, val in [("Code128", "code128"), ("QR", "qr"), ("EAN-13", "ean13")]:
            ctk.CTkRadioButton(type_row, text=lbl, variable=self._fmt_var, value=val,
                               command=self._on_fmt_change,
                               font=ctk.CTkFont(size=11)).pack(side="left", padx=5)

        # Preview
        pv_outer = ctk.CTkFrame(right, corner_radius=8, fg_color="#F1F5F9")
        pv_outer.grid(row=1, column=0, sticky="nsew", padx=14, pady=10)
        pv_outer.grid_rowconfigure(0, weight=1)
        pv_outer.grid_columnconfigure(0, weight=1)

        self.lbl_preview = ctk.CTkLabel(
            pv_outer,
            text="← Selecciona un producto",
            font=ctk.CTkFont(size=13), text_color="gray60")
        self.lbl_preview.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.lbl_info = ctk.CTkLabel(
            right, text="", font=ctk.CTkFont(size=11),
            text_color="#64748B", wraplength=380, justify="left")
        self.lbl_info.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 4))

        # Code entry row
        code_frame = ctk.CTkFrame(right, fg_color="transparent")
        code_frame.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 6))
        code_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(code_frame, text="Texto del código:",
                     font=ctk.CTkFont(size=11), text_color="#64748B"
                     ).grid(row=0, column=0, sticky="w")

        entry_row = ctk.CTkFrame(code_frame, fg_color="transparent")
        entry_row.grid(row=1, column=0, sticky="ew")
        entry_row.grid_columnconfigure(0, weight=1)

        self.entry_codigo = ctk.CTkEntry(
            entry_row, height=34,
            placeholder_text="Código del producto")
        self.entry_codigo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry_codigo.bind("<KeyRelease>", lambda e: self._schedule_preview())

        ctk.CTkButton(entry_row, text="⚡ Auto", width=70, height=34,
                      fg_color="#7C3AED", hover_color="#6D28D9",
                      command=self._auto_gen).grid(row=0, column=1)

        # Action buttons
        btn_frame = ctk.CTkFrame(right, fg_color="transparent")
        btn_frame.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 14))

        ctk.CTkButton(btn_frame, text="💾 Asignar al producto", height=36,
                      fg_color="#16A34A", hover_color="#15803D",
                      command=self._asignar).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_frame, text="🖼 PNG", height=36, width=76,
                      fg_color="#2563EB", hover_color="#1D4ED8",
                      command=self._export_png).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_frame, text="📄 PDF", height=36, width=76,
                      fg_color="#DC2626", hover_color="#B91C1C",
                      command=self._export_pdf_single).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_frame, text="📋 PDF masivo", height=36,
                      fg_color="#F59E0B", hover_color="#D97706", text_color="white",
                      command=self._export_pdf_bulk).pack(side="left")

    # ── Data ─────────────────────────────────────────────────────────────────

    def _load_products(self):
        search = self.entry_search.get().strip()
        sin_cod = self._filter_sin_codigo.get()
        db = get_db_session()
        try:
            q = db.query(Producto).filter(Producto.activo == True)
            if search:
                q = q.filter(
                    Producto.nombre.ilike(f"%{search}%") |
                    Producto.codigo_barras.ilike(f"%{search}%")
                )
            if sin_cod:
                q = q.filter(
                    (Producto.codigo_barras == None) | (Producto.codigo_barras == "")
                )
            self._productos = q.order_by(Producto.nombre).limit(200).all()
            data = [(p.id, p.nombre[:40], p.codigo_barras or "") for p in self._productos]
        finally:
            db.close()

        for row in self.tree.get_children():
            self.tree.delete(row)
        for pid, nombre, codigo in data:
            tags = () if codigo else ("sin_cod",)
            self.tree.insert("", "end", iid=str(pid),
                             values=(nombre, codigo or "—"), tags=tags)

    def _on_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        pid = int(sel[0])
        db = get_db_session()
        try:
            prod = db.query(Producto).filter(Producto.id == pid).first()
            if not prod:
                return
            self._selected_pid = pid
            self.entry_codigo.delete(0, "end")
            if prod.codigo_barras:
                self.entry_codigo.insert(0, prod.codigo_barras)
            self.lbl_info.configure(
                text=(f"📦 {prod.nombre}\n"
                      f"Precio: ${prod.precio_venta:.2f}  |  Stock: {prod.stock}  |  "
                      f"Código: {prod.codigo_barras or '(sin código)'}"))
        finally:
            db.close()
        self._refresh_preview()

    def _select_by_id(self, pid: int):
        try:
            self.tree.selection_set(str(pid))
            self.tree.see(str(pid))
            self._on_select()
        except Exception:
            pass

    # ── Code generation helpers ───────────────────────────────────────────────

    def _on_fmt_change(self):
        fmt = self._fmt_var.get()
        current = self.entry_codigo.get().strip()
        if fmt == "ean13" and current and not (len(current) in (12, 13) and current.isdigit()):
            messagebox.showinfo("EAN-13",
                "EAN-13 requiere exactamente 12 dígitos (el 13° se calcula automáticamente).",
                parent=self)
        self._refresh_preview()

    def _auto_gen(self):
        if not self._selected_pid:
            messagebox.showwarning("Seleccionar", "Primero selecciona un producto", parent=self)
            return
        import random
        fmt = self._fmt_var.get()
        if fmt == "ean13":
            digits12 = "".join(str(random.randint(0, 9)) for _ in range(12))
            code = digits12 + _ean13_check(digits12)
        else:
            code = f"FAR{self._selected_pid:06d}"
        self.entry_codigo.delete(0, "end")
        self.entry_codigo.insert(0, code)
        self._refresh_preview()

    def _schedule_preview(self):
        if not self._pending_preview:
            self._pending_preview = True
            self.after(400, self._do_schedule)

    def _do_schedule(self):
        self._pending_preview = False
        self._refresh_preview()

    def _get_selected_product(self):
        if not self._selected_pid:
            return None
        db = get_db_session()
        try:
            return db.query(Producto).filter(Producto.id == self._selected_pid).first()
        finally:
            db.close()

    def _refresh_preview(self):
        codigo = self.entry_codigo.get().strip()
        prod = self._get_selected_product()
        if not codigo or not prod:
            self.lbl_preview.configure(image=None, text="← Selecciona un producto")
            return

        fmt = self._fmt_var.get()
        nombre, precio = prod.nombre, prod.precio_venta

        def _worker():
            try:
                if fmt == "ean13":
                    digits = codigo[:12] if len(codigo) >= 12 else codigo.zfill(12)
                    if not digits.isdigit():
                        raise ValueError("EAN-13 necesita dígitos numéricos")
                    texto = digits[:12] + _ean13_check(digits[:12])
                else:
                    texto = codigo

                img = _label_img(nombre, precio, texto, fmt, label_w=400)
                max_w, max_h = 430, 300
                ratio = min(max_w / img.width, max_h / img.height)
                if ratio < 1:
                    img = img.resize(
                        (int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, size=(img.width, img.height))

                def _apply():
                    self._preview_img = ctk_img
                    self.lbl_preview.configure(image=ctk_img, text="")
                self.after(0, _apply)
            except Exception as exc:
                self.after(0, lambda e=exc: self.lbl_preview.configure(
                    image=None, text=f"Error: {e}"))

        threading.Thread(target=_worker, daemon=True, name="BcPreview").start()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _asignar(self):
        codigo = self.entry_codigo.get().strip()
        prod = self._get_selected_product()
        if not codigo or not prod:
            messagebox.showwarning("Seleccionar",
                "Selecciona un producto y escribe el código", parent=self)
            return
        db = get_db_session()
        try:
            dup = db.query(Producto).filter(
                Producto.codigo_barras == codigo,
                Producto.id != prod.id).first()
            if dup:
                messagebox.showwarning("Duplicado",
                    f"El código '{codigo}' ya pertenece a:\n{dup.nombre}", parent=self)
                return
            p = db.query(Producto).filter(Producto.id == prod.id).first()
            p.codigo_barras = codigo
            db.commit()
            messagebox.showinfo("OK", f"Código asignado a:\n{prod.nombre}", parent=self)
            self._load_products()
            self.lbl_info.configure(
                text=(f"📦 {prod.nombre}\n"
                      f"Precio: ${prod.precio_venta:.2f}  |  Stock: {prod.stock}  |  "
                      f"Código: {codigo}"))
        except Exception as exc:
            db.rollback()
            messagebox.showerror("Error", str(exc), parent=self)
        finally:
            db.close()

    def _get_label(self) -> Image.Image | None:
        codigo = self.entry_codigo.get().strip()
        prod = self._get_selected_product()
        if not codigo or not prod:
            return None
        fmt = self._fmt_var.get()
        if fmt == "ean13":
            digits = codigo[:12].zfill(12)
            codigo = digits + _ean13_check(digits)
        return _label_img(prod.nombre, prod.precio_venta, codigo, fmt, label_w=420)

    def _export_png(self):
        prod = self._get_selected_product()
        if not prod:
            messagebox.showwarning("Seleccionar", "Selecciona un producto primero", parent=self)
            return
        img = self._get_label()
        if not img:
            messagebox.showwarning("Sin código", "Ingresa o genera un código primero", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Guardar etiqueta PNG",
            defaultextension=".png",
            initialfile=f"etiqueta_{prod.nombre[:20].replace(' ', '_')}.png",
            filetypes=[("PNG", "*.png")])
        if not path:
            return
        try:
            img.save(path, "PNG", dpi=(203, 203))
            messagebox.showinfo("Exportado", f"PNG guardado en:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _export_pdf_single(self):
        prod = self._get_selected_product()
        if not prod:
            messagebox.showwarning("Seleccionar", "Selecciona un producto primero", parent=self)
            return
        img = self._get_label()
        if not img:
            messagebox.showwarning("Sin código", "Ingresa o genera un código primero", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Guardar etiqueta PDF",
            defaultextension=".pdf",
            initialfile=f"etiqueta_{prod.nombre[:20].replace(' ', '_')}.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return
        try:
            _export_pdf_labels([(img, prod.nombre)], path, cols=3, rows=8)
            messagebox.showinfo("Exportado", f"PDF guardado en:\n{path}", parent=self)
        except Exception as exc:
            messagebox.showerror("Error", str(exc), parent=self)

    def _export_pdf_bulk(self):
        db = get_db_session()
        try:
            pids = [int(iid) for iid in self.tree.get_children()]
            productos = db.query(Producto).filter(Producto.id.in_(pids)).all()
        finally:
            db.close()

        con_codigo = [p for p in productos if p.codigo_barras]
        if not con_codigo:
            messagebox.showwarning("Sin datos",
                "Ningún producto visible tiene código asignado.\n"
                "Asigna códigos primero usando el botón 'Asignar al producto'.", parent=self)
            return

        path = filedialog.asksaveasfilename(
            parent=self, title="Guardar PDF de etiquetas",
            defaultextension=".pdf",
            initialfile="etiquetas_productos.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not path:
            return

        fmt = self._fmt_var.get()

        def _worker():
            try:
                labels = []
                for p in con_codigo:
                    codigo = p.codigo_barras
                    if fmt == "ean13":
                        digits = codigo[:12].zfill(12)
                        if not digits.isdigit():
                            continue
                        codigo = digits + _ean13_check(digits)
                    img = _label_img(p.nombre, p.precio_venta, codigo, fmt, label_w=340)
                    labels.append((img, p.nombre))
                _export_pdf_labels(labels, path, cols=3, rows=8)
                self.after(0, lambda: messagebox.showinfo(
                    "Exportado",
                    f"PDF con {len(labels)} etiquetas guardado en:\n{path}",
                    parent=self))
            except Exception as exc:
                self.after(0, lambda e=exc: messagebox.showerror("Error", str(e), parent=self))

        threading.Thread(target=_worker, daemon=True, name="BulkPDF").start()


# ─── Mini-dialog for ProductoDialog integration ───────────────────────────────

class GenerarCodigoMiniDialog(ctk.CTkToplevel):
    """Small dialog to generate a barcode for a product being created/edited."""

    def __init__(self, parent, nombre_producto: str = "", on_confirm=None):
        super().__init__(parent)
        self.title("🔲 Generar Código")
        self.geometry("480x420")
        self.resizable(False, False)
        self.grab_set()
        self.on_confirm = on_confirm

        self._fmt_var = tk.StringVar(value="code128")
        self._preview_img = None
        self._nombre = nombre_producto

        self._build_ui()

    def _build_ui(self):
        ctk.CTkLabel(self, text="🔲  Generar Código de Barras / QR",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(pady=(16, 4))

        type_row = ctk.CTkFrame(self, fg_color="transparent")
        type_row.pack()
        ctk.CTkLabel(type_row, text="Tipo:", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 8))
        for lbl, val in [("Code128", "code128"), ("QR", "qr")]:
            ctk.CTkRadioButton(type_row, text=lbl, variable=self._fmt_var, value=val,
                               command=self._refresh,
                               font=ctk.CTkFont(size=11)).pack(side="left", padx=6)

        ctk.CTkLabel(self, text="Texto del código:",
                     font=ctk.CTkFont(size=11), text_color="#64748B").pack(anchor="w", padx=20, pady=(10, 2))

        code_row = ctk.CTkFrame(self, fg_color="transparent")
        code_row.pack(fill="x", padx=20)
        code_row.grid_columnconfigure(0, weight=1)

        self.entry_code = ctk.CTkEntry(code_row, height=34, placeholder_text="Código a generar")
        self.entry_code.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.entry_code.bind("<KeyRelease>", lambda e: self._refresh())

        ctk.CTkButton(code_row, text="⚡ Auto", width=70, height=34,
                      fg_color="#7C3AED", hover_color="#6D28D9",
                      command=self._auto).grid(row=0, column=1)

        # Preview
        pv = ctk.CTkFrame(self, corner_radius=8, fg_color="#F1F5F9")
        pv.pack(fill="both", expand=True, padx=20, pady=10)
        self.lbl_pv = ctk.CTkLabel(pv, text="Escribe un código o usa ⚡ Auto",
                                    font=ctk.CTkFont(size=11), text_color="gray60")
        self.lbl_pv.pack(expand=True, fill="both", padx=8, pady=8)

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(0, 16))
        ctk.CTkButton(btn_row, text="✓ Usar este código", height=36,
                      fg_color="#16A34A", hover_color="#15803D",
                      command=self._confirmar).pack(side="left", padx=(0, 8))
        ctk.CTkButton(btn_row, text="Cancelar", height=36, width=100,
                      fg_color="transparent", border_width=1, border_color="#ccc",
                      command=self.destroy).pack(side="left")

    def _auto(self):
        import random
        fmt = self._fmt_var.get()
        if fmt == "qr":
            code = f"FAR{random.randint(100000, 999999)}"
        else:
            code = f"FAR{random.randint(100000, 999999)}"
        self.entry_code.delete(0, "end")
        self.entry_code.insert(0, code)
        self._refresh()

    def _refresh(self):
        codigo = self.entry_code.get().strip()
        if not codigo:
            return
        fmt = self._fmt_var.get()
        nombre = self._nombre or "Producto"

        def _worker():
            try:
                img = _label_img(nombre, 0.0, codigo, fmt, label_w=340)
                max_w, max_h = 380, 180
                ratio = min(max_w / img.width, max_h / img.height)
                if ratio < 1:
                    img = img.resize(
                        (int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
                ctk_img = ctk.CTkImage(light_image=img, size=(img.width, img.height))

                def _apply():
                    self._preview_img = ctk_img
                    self.lbl_pv.configure(image=ctk_img, text="")
                self.after(0, _apply)
            except Exception as exc:
                self.after(0, lambda e=exc: self.lbl_pv.configure(
                    image=None, text=f"Error: {e}"))

        threading.Thread(target=_worker, daemon=True, name="MiniPreview").start()

    def _confirmar(self):
        codigo = self.entry_code.get().strip()
        if not codigo:
            messagebox.showwarning("Vacío", "Escribe o genera un código primero", parent=self)
            return
        if self.on_confirm:
            self.on_confirm(codigo)
        self.destroy()
