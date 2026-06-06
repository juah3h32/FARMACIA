import customtkinter as ctk
from tkinter import ttk, messagebox
from app.database.connection import get_db_session
from app.database.models import Cliente, Venta
from app.auth.auth_service import registrar_accion


class CustomersScreen(ctk.CTkFrame):
    def __init__(self, parent, user):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.user = user
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(hdr, text="👥 Clientes", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=14, pady=10, sticky="w")

        self.entry_search = ctk.CTkEntry(hdr, placeholder_text="Buscar cliente...", height=36, width=260)
        self.entry_search.grid(row=0, column=1, padx=8, pady=10, sticky="w")
        self.entry_search.bind("<KeyRelease>", lambda e: self._load())

        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.grid(row=0, column=2, padx=14)
        ctk.CTkButton(btns, text="+ Agregar", width=90, height=34,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._agregar).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="✏️ Editar", width=80, height=34,
                      command=self._editar).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="📋 Historial", width=90, height=34,
                      fg_color="#2196F3", hover_color="#1976D2",
                      command=self._ver_historial).pack(side="left", padx=3)

        table_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        table_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Cli.Treeview", background="#2b2b2b", foreground="white",
                        rowheight=30, fieldbackground="#2b2b2b", borderwidth=0,
                        font=("Segoe UI", 11))
        style.configure("Cli.Treeview.Heading", background="#1e1e1e", foreground="white",
                        relief="flat", font=("Segoe UI", 11, "bold"))
        style.map("Cli.Treeview", background=[("selected", "#2196F3")])

        cols = ("id", "nombre", "telefono", "email", "rfc", "credito", "deuda")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                  style="Cli.Treeview", selectmode="browse")
        headers = {
            "id": ("ID", 40), "nombre": ("Nombre", 180), "telefono": ("Teléfono", 100),
            "email": ("Email", 140), "rfc": ("RFC", 100),
            "credito": ("Límite Crédito", 100), "deuda": ("Deuda", 80),
        }
        for col, (heading, width) in headers.items():
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, minwidth=width, 
                             anchor="w" if col in ("nombre", "email") else "center",
                             stretch=True if col == "nombre" else False)

        self.tree.tag_configure("deuda", foreground="#FF9800")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Double-1>", lambda e: self._editar())

        self._load()

    def _load(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        db = get_db_session()
        try:
            q = db.query(Cliente).filter(Cliente.activo == True)
            search = self.entry_search.get().strip()
            if search:
                q = q.filter(
                    Cliente.nombre.ilike(f"%{search}%") |
                    Cliente.telefono.ilike(f"%{search}%")
                )
            for c in q.order_by(Cliente.nombre).all():
                tag = "deuda" if c.saldo_deuda > 0 else ""
                self.tree.insert("", "end", iid=str(c.id), values=(
                    c.id, c.nombre, c.telefono or "", c.email or "", c.rfc or "",
                    f"${c.limite_credito:.2f}", f"${c.saldo_deuda:.2f}",
                ), tags=(tag,))
        finally:
            db.close()

    def _get_selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _agregar(self):
        ClienteDialog(self, on_save=self._load)

    def _editar(self):
        cid = self._get_selected_id()
        if not cid:
            messagebox.showwarning("Seleccionar", "Selecciona un cliente")
            return
        db = get_db_session()
        try:
            c = db.query(Cliente).filter(Cliente.id == cid).first()
            if c:
                data = {"id": c.id, "nombre": c.nombre, "telefono": c.telefono or "",
                        "email": c.email or "", "rfc": c.rfc or "",
                        "direccion": c.direccion or "", "limite_credito": c.limite_credito}
                ClienteDialog(self, data=data, on_save=self._load)
        finally:
            db.close()

    def _ver_historial(self):
        cid = self._get_selected_id()
        if not cid:
            messagebox.showwarning("Seleccionar", "Selecciona un cliente")
            return
        HistorialClienteDialog(self, cliente_id=cid)

    def on_show(self):
        self._load()


class ClienteDialog(ctk.CTkToplevel):
    def __init__(self, parent, data: dict = None, on_save=None):
        super().__init__(parent)
        self.title("Cliente")
        self.geometry("420x460")
        self.grab_set()
        self.data = data or {}
        self.on_save = on_save
        self._build_ui()

    def _build_ui(self):
        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        frame.grid_columnconfigure(1, weight=1)

        fields = [
            ("Nombre:*", "nombre"), ("Teléfono:", "telefono"),
            ("Email:", "email"), ("RFC:", "rfc"),
            ("Dirección:", "direccion"), ("Límite de Crédito $:", "limite_credito"),
        ]
        self.entries = {}
        for i, (label, key) in enumerate(fields):
            ctk.CTkLabel(frame, text=label, anchor="e").grid(row=i, column=0, padx=(0, 8), pady=6, sticky="e")
            e = ctk.CTkEntry(frame, height=34)
            e.grid(row=i, column=1, pady=6, sticky="ew")
            if self.data.get(key) is not None:
                e.insert(0, str(self.data[key]))
            self.entries[key] = e

        # Enter key navigation
        self.entries["nombre"].bind("<Return>", lambda e: self.entries["telefono"].focus_set())
        self.entries["telefono"].bind("<Return>", lambda e: self.entries["email"].focus_set())
        self.entries["email"].bind("<Return>", lambda e: self.entries["rfc"].focus_set())
        self.entries["rfc"].bind("<Return>", lambda e: self.entries["direccion"].focus_set())
        self.entries["direccion"].bind("<Return>", lambda e: self.entries["limite_credito"].focus_set())
        self.entries["limite_credito"].bind("<Return>", lambda e: self._guardar())

        ctk.CTkButton(
            self, text="💾 Guardar", height=42, fg_color="#4CAF50", hover_color="#388E3C",
            command=self._guardar
        ).pack(fill="x", padx=16, pady=(0, 16))

    def _guardar(self):
        nombre = self.entries["nombre"].get().strip()
        if not nombre:
            messagebox.showwarning("Error", "El nombre es obligatorio")
            return
        db = get_db_session()
        try:
            if self.data.get("id"):
                c = db.query(Cliente).filter(Cliente.id == self.data["id"]).first()
            else:
                c = Cliente()
                db.add(c)
            c.nombre = nombre
            c.telefono = self.entries["telefono"].get().strip() or None
            c.email = self.entries["email"].get().strip() or None
            c.rfc = self.entries["rfc"].get().strip() or None
            c.direccion = self.entries["direccion"].get().strip() or None
            try:
                c.limite_credito = float(self.entries["limite_credito"].get().strip() or "0")
            except ValueError:
                c.limite_credito = 0.0
            db.commit()
            registrar_accion("GUARDAR_CLIENTE", "clientes", c.id, c.nombre)
            if self.on_save:
                self.on_save()
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()


class HistorialClienteDialog(ctk.CTkToplevel):
    def __init__(self, parent, cliente_id: int):
        super().__init__(parent)
        self.cliente_id = cliente_id
        self.title("Historial de Compras")
        self.geometry("600x450")
        self.grab_set()
        self._build_ui()

    def _build_ui(self):
        db = get_db_session()
        try:
            c = db.query(Cliente).filter(Cliente.id == self.cliente_id).first()
            nombre = c.nombre if c else "?"
            ventas = db.query(Venta).filter(Venta.cliente_id == self.cliente_id).order_by(
                Venta.creado_en.desc()).limit(50).all()
        finally:
            db.close()

        ctk.CTkLabel(self, text=f"Historial: {nombre}", font=ctk.CTkFont(size=15, weight="bold")).pack(
            pady=(16, 4))

        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Hist.Treeview", background="#2b2b2b", foreground="white",
                        rowheight=28, fieldbackground="#2b2b2b", borderwidth=0, font=("Segoe UI", 11))
        style.configure("Hist.Treeview.Heading", background="#1e1e1e", foreground="white",
                        relief="flat", font=("Segoe UI", 11, "bold"))
        style.map("Hist.Treeview", background=[("selected", "#2196F3")])

        cols = ("folio", "fecha", "total", "pago", "estado")
        tree = ttk.Treeview(frame, columns=cols, show="headings", style="Hist.Treeview")
        for col, heading, width in [
            ("folio", "Folio", 130), ("fecha", "Fecha", 140), ("total", "Total", 90),
            ("pago", "Método Pago", 110), ("estado", "Estado", 100),
        ]:
            tree.heading(col, text=heading)
            tree.column(col, width=width, anchor="center")
        tree.grid(row=0, column=0, sticky="nsew")

        total_gastado = 0
        for v in ventas:
            total_gastado += v.total if v.estado.value == "completada" else 0
            tree.insert("", "end", values=(
                v.folio or v.id,
                v.creado_en.strftime("%d/%m/%Y %H:%M") if v.creado_en else "",
                f"${v.total:.2f}",
                v.metodo_pago.value.capitalize(),
                v.estado.value.capitalize(),
            ))

        ctk.CTkLabel(self, text=f"Total de compras: ${total_gastado:.2f}  |  Visitas: {len(ventas)}",
                     font=ctk.CTkFont(size=12, weight="bold"), text_color="#2196F3").pack(pady=(0, 8))
