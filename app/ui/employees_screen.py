import customtkinter as ctk
from tkinter import ttk, messagebox
import tkinter as tk
from app.database.connection import get_db_session
from app.database.models import Usuario, RolUsuario
from app.auth.auth_service import hash_password, registrar_accion


class EmployeesScreen(ctk.CTkFrame):
    def __init__(self, parent, user):
        super().__init__(parent, corner_radius=0, fg_color="transparent")
        self.current_user = user
        self._build_ui()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Header
        hdr = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(hdr, text="👤 Empleados", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=14, pady=10, sticky="w")

        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.grid(row=0, column=2, padx=14, pady=10)
        ctk.CTkButton(btns, text="+ Agregar", width=90, height=34,
                      fg_color="#4CAF50", hover_color="#388E3C",
                      command=self._agregar).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="✏️ Editar", width=80, height=34,
                      command=self._editar).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="🔑 Clave", width=80, height=34,
                      fg_color="#FF9800", hover_color="#F57C00",
                      command=self._cambiar_password).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="Desactivar", width=90, height=34,
                      fg_color="#e74c3c", hover_color="#c0392b",
                      command=self._toggle_activo).pack(side="left", padx=3)

        # Tabla
        table_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=("#fff", "#2b2b2b"))
        table_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        style = ttk.Style()
        style.configure("Emp.Treeview", background="#2b2b2b", foreground="white",
                        rowheight=32, fieldbackground="#2b2b2b", borderwidth=0,
                        font=("Segoe UI", 11))
        style.configure("Emp.Treeview.Heading", background="#1e1e1e", foreground="white",
                        relief="flat", font=("Segoe UI", 11, "bold"))
        style.map("Emp.Treeview", background=[("selected", "#2196F3")])

        cols = ("id", "username", "nombre", "rol", "telefono", "email", "activo", "creado")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings",
                                  style="Emp.Treeview", selectmode="browse")
        headers = {
            "id": ("ID", 45), "username": ("Usuario", 110), "nombre": ("Nombre Completo", 200),
            "rol": ("Rol", 110), "telefono": ("Teléfono", 110),
            "email": ("Email", 160), "activo": ("Estado", 80), "creado": ("Creado", 100),
        }
        for col, (heading, width) in headers.items():
            self.tree.heading(col, text=heading)
            self.tree.column(col, width=width, anchor="w" if col in ("nombre", "email") else "center")

        self.tree.tag_configure("inactive", foreground="#666666")

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
            users = db.query(Usuario).order_by(Usuario.nombre).all()
            for u in users:
                tag = "" if u.activo else "inactive"
                self.tree.insert("", "end", iid=str(u.id), values=(
                    u.id, u.username, u.nombre,
                    u.rol.value.capitalize(),
                    u.telefono or "", u.email or "",
                    "Activo" if u.activo else "Inactivo",
                    u.creado_en.strftime("%d/%m/%Y") if u.creado_en else "",
                ), tags=(tag,))
        finally:
            db.close()

    def _get_selected_id(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def _agregar(self):
        EmpleadoDialog(self, on_save=self._load)

    def _editar(self):
        uid = self._get_selected_id()
        if not uid:
            messagebox.showwarning("Seleccionar", "Selecciona un empleado")
            return
        db = get_db_session()
        try:
            u = db.query(Usuario).filter(Usuario.id == uid).first()
            if u:
                data = {"id": u.id, "username": u.username, "nombre": u.nombre,
                        "rol": u.rol.value, "telefono": u.telefono or "", "email": u.email or ""}
                EmpleadoDialog(self, data=data, on_save=self._load)
        finally:
            db.close()

    def _cambiar_password(self):
        uid = self._get_selected_id()
        if not uid:
            messagebox.showwarning("Seleccionar", "Selecciona un empleado")
            return

        win = ctk.CTkToplevel(self)
        win.title("Cambiar Contraseña")
        win.geometry("340x220")
        win.grab_set()

        ctk.CTkLabel(win, text="Nueva contraseña:", font=ctk.CTkFont(size=13)).pack(pady=(20, 4))
        e1 = ctk.CTkEntry(win, show="•", height=36, width=260)
        e1.pack(pady=4)
        ctk.CTkLabel(win, text="Confirmar:", font=ctk.CTkFont(size=13)).pack(pady=(8, 4))
        e2 = ctk.CTkEntry(win, show="•", height=36, width=260)
        e2.pack(pady=4)

        def guardar():
            p1, p2 = e1.get(), e2.get()
            if not p1 or p1 != p2:
                messagebox.showwarning("Error", "Las contraseñas no coinciden")
                return
            if len(p1) < 4:
                messagebox.showwarning("Error", "Mínimo 4 caracteres")
                return
            db = get_db_session()
            try:
                u = db.query(Usuario).filter(Usuario.id == uid).first()
                u.password_hash = hash_password(p1)
                db.commit()
                registrar_accion("CAMBIO_PASSWORD", "usuarios", uid)
                messagebox.showinfo("OK", "Contraseña actualizada")
                win.destroy()
            finally:
                db.close()

        ctk.CTkButton(win, text="Guardar", fg_color="#4CAF50", command=guardar).pack(pady=12)

    def _toggle_activo(self):
        uid = self._get_selected_id()
        if not uid:
            messagebox.showwarning("Seleccionar", "Selecciona un empleado")
            return
        if uid == self.current_user.id:
            messagebox.showwarning("Error", "No puedes desactivarte a ti mismo")
            return
        db = get_db_session()
        try:
            u = db.query(Usuario).filter(Usuario.id == uid).first()
            if u:
                estado = "activar" if not u.activo else "desactivar"
                if not messagebox.askyesno("Confirmar", f"¿{estado.capitalize()} a {u.nombre}?"):
                    return
                u.activo = not u.activo
                db.commit()
                registrar_accion(f"{'ACTIVAR' if u.activo else 'DESACTIVAR'}_USUARIO", "usuarios", uid)
                self._load()
        finally:
            db.close()

    def on_show(self):
        self._load()


class EmpleadoDialog(ctk.CTkToplevel):
    def __init__(self, parent, data: dict = None, on_save=None):
        super().__init__(parent)
        self.title("Empleado")
        self.geometry("420x500")
        self.grab_set()
        self.data = data or {}
        self.on_save = on_save
        self._build_ui()

    def _build_ui(self):
        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        frame.grid_columnconfigure(1, weight=1)

        editing = bool(self.data.get("id"))

        fields = [
            ("Usuario:*", "username"), ("Nombre Completo:*", "nombre"),
            ("Teléfono:", "telefono"), ("Email:", "email"),
        ]
        if not editing:
            fields.append(("Contraseña:*", "password"))

        self.entries = {}
        for i, (label, key) in enumerate(fields):
            ctk.CTkLabel(frame, text=label, anchor="e").grid(row=i, column=0, padx=(0, 8), pady=6, sticky="e")
            e = ctk.CTkEntry(frame, height=34, show="•" if key == "password" else "")
            e.grid(row=i, column=1, pady=6, sticky="ew")
            if self.data.get(key):
                e.insert(0, str(self.data[key]))
            self.entries[key] = e

        # Rol
        row = len(fields)
        ctk.CTkLabel(frame, text="Rol:*", anchor="e").grid(row=row, column=0, padx=(0, 8), pady=6, sticky="e")
        self.opt_rol = ctk.CTkOptionMenu(frame, values=["admin", "cajero", "farmaceutico"])
        self.opt_rol.grid(row=row, column=1, pady=6, sticky="ew")
        if self.data.get("rol"):
            self.opt_rol.set(self.data["rol"])
        else:
            self.opt_rol.set("cajero")

        ctk.CTkButton(
            self, text="💾 Guardar", height=42, fg_color="#4CAF50", hover_color="#388E3C",
            command=self._guardar
        ).pack(fill="x", padx=16, pady=(0, 16))

    def _guardar(self):
        nombre = self.entries["nombre"].get().strip()
        username = self.entries["username"].get().strip()
        if not nombre or not username:
            messagebox.showwarning("Error", "Nombre y usuario son obligatorios")
            return

        db = get_db_session()
        try:
            if self.data.get("id"):
                u = db.query(Usuario).filter(Usuario.id == self.data["id"]).first()
            else:
                password = self.entries.get("password", ctk.CTkEntry(self)).get().strip()
                if not password:
                    messagebox.showwarning("Error", "Contraseña requerida")
                    return
                # Check duplicate username
                existe = db.query(Usuario).filter(Usuario.username == username).first()
                if existe:
                    messagebox.showwarning("Error", f"El usuario '{username}' ya existe")
                    return
                u = Usuario(password_hash=hash_password(password))
                db.add(u)

            u.username = username
            u.nombre = nombre
            u.rol = RolUsuario(self.opt_rol.get())
            u.telefono = self.entries.get("telefono") and self.entries["telefono"].get().strip() or None
            u.email = self.entries.get("email") and self.entries["email"].get().strip() or None

            db.commit()
            registrar_accion("GUARDAR_EMPLEADO", "usuarios", u.id, u.nombre)
            if self.on_save:
                self.on_save()
            self.destroy()
        except Exception as e:
            db.rollback()
            messagebox.showerror("Error", str(e))
        finally:
            db.close()
