import customtkinter as ctk
from tkinter import ttk, messagebox
from app.database.connection import get_db_session
from app.database.models import Proveedor
from app.auth.auth_service import registrar_accion


class SuppliersScreen(ctk.CTkFrame):
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

        ctk.CTkLabel(hdr, text="🚚 Proveedores", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=14, pady=10, sticky="w")

        self.entry_search = ctk.CTkEntry(hdr, placeholder_text="Buscar proveedor...", height=36, width=260)
        self.entry_search.grid(row=0, column=1, padx=8, pady=10, sticky="w")
        self.entry_search.bind("<KeyRelease>", lambda e: self._load())

        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.grid(row=0, column=2, padx=14)
        ctk.CTkButton(btns, text="+ Agregar", width=90, height=34,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._agregar).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="✏️ Editar", width=80, height=34,
                      command=self._editar).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Desactivar", width=90, height=34,
                      fg_color="#e74c3c", hover_color="#c0392b",
                      command=self._desactivar).pack(side="left", padx=3)

        table_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        table_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Prov.Treeview",
                        background="#FFFFFF", foreground="#0F172A",
                        rowheight=30, fieldbackground="#FFFFFF",
                        borderwidth=0, font=("Segoe UI", 11))
        style.configure("Prov.Treeview.Heading",
                        background="#F1F5F9", foreground="#64748B",
                        relief="flat", font=("Segoe UI", 11, "bold"), padding=(6, 6))
        style.map("Prov.Treeview",
                  background=[("selected", "#EFF6FF")],
                  foreground=[("selected", "#2563EB")])
        style.layout("Prov.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        cols = ("id", "nombre", "contacto", "telefono", "email", "rfc", "activo")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                  style="Prov.Treeview", selectmode="browse")
        headers = {
            "id": ("ID", 45), "nombre": ("Nombre", 200), "contacto": ("Contacto", 140),
            "telefono": ("Teléfono", 110), "email": ("Email", 160),
            "rfc": ("RFC", 120), "activo": ("Estado", 80),
        }
        for col, (heading, width) in headers.items():
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width)

        self.tree.tag_configure("inactive", foreground="#94A3B8", background="#F8FAFF")
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
            q = db.query(Proveedor)
            search = self.entry_search.get().strip()
            if search:
                q = q.filter(Proveedor.nombre.ilike(f"%{search}%") | Proveedor.contacto.ilike(f"%{search}%"))
            for p in q.order_by(Proveedor.nombre).all():
                tag = "" if p.activo else "inactive"
                self.tree.insert("", "end", iid=str(p.id), values=(
                    p.id, p.nombre, p.contacto or "", p.telefono or "",
                    p.email or "", p.rfc or "", "Activo" if p.activo else "Inactivo",
                ), tags=(tag,))
        finally:
            db.close()

    def _get_selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _agregar(self):
        ProveedorDialog(self, on_save=self._load)

    def _editar(self):
        pid = self._get_selected_id()
        if not pid:
            messagebox.showwarning("Seleccionar", "Selecciona un proveedor")
            return
        db = get_db_session()
        try:
            p = db.query(Proveedor).filter(Proveedor.id == pid).first()
            if p:
                data = {"id": p.id, "nombre": p.nombre, "contacto": p.contacto or "",
                        "telefono": p.telefono or "", "email": p.email or "",
                        "direccion": p.direccion or "", "rfc": p.rfc or ""}
                ProveedorDialog(self, data=data, on_save=self._load)
        finally:
            db.close()

    def _desactivar(self):
        pid = self._get_selected_id()
        if not pid:
            messagebox.showwarning("Seleccionar", "Selecciona un proveedor")
            return
        db = get_db_session()
        try:
            p = db.query(Proveedor).filter(Proveedor.id == pid).first()
            if p and messagebox.askyesno("Confirmar", f"¿Desactivar a {p.nombre}?"):
                p.activo = False
                db.commit()
                self._load()
        finally:
            db.close()

    def on_show(self):
        self._load()


class ProveedorDialog(ctk.CTkToplevel):
    def __init__(self, parent, data: dict = None, on_save=None):
        super().__init__(parent)
        self.title("Proveedor")
        self.geometry("420x450")
        self.grab_set()
        self.data = data or {}
        self.on_save = on_save
        self._build_ui()

    def _build_ui(self):
        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        frame.grid_columnconfigure(1, weight=1)

        fields = [
            ("Nombre:*", "nombre"), ("Persona de Contacto:", "contacto"),
            ("Teléfono:", "telefono"), ("Email:", "email"),
            ("RFC:", "rfc"), ("Dirección:", "direccion"),
        ]
        self.entries = {}
        for i, (label, key) in enumerate(fields):
            ctk.CTkLabel(frame, text=label, anchor="e").grid(row=i, column=0, padx=(0, 8), pady=6, sticky="e")
            e = ctk.CTkEntry(frame, height=34)
            e.grid(row=i, column=1, pady=6, sticky="ew")
            if self.data.get(key):
                e.insert(0, str(self.data[key]))
            self.entries[key] = e

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
                p = db.query(Proveedor).filter(Proveedor.id == self.data["id"]).first()
            else:
                p = Proveedor()
                db.add(p)
            p.nombre = nombre
            p.contacto = self.entries["contacto"].get().strip() or None
            p.telefono = self.entries["telefono"].get().strip() or None
            p.email = self.entries["email"].get().strip() or None
            p.rfc = self.entries["rfc"].get().strip() or None
            p.direccion = self.entries["direccion"].get().strip() or None
            db.commit()
            registrar_accion("GUARDAR_PROVEEDOR", "proveedores", p.id, p.nombre)
            if self.on_save:
                self.on_save()
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()
