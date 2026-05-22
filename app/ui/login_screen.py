import tkinter as tk
import customtkinter as ctk
from app.auth.auth_service import login
import app.config as cfg

W, H = 460, 510
CARD_W, CARD_H = 388, 474


class LoginScreen(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Farmacia Eben-Ezer")
        self.resizable(False, False)
        self.attributes("-alpha", 0.0)
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self._draw_bg()
        self._build_card()
        self.after(20, lambda: self._anim(0.0, 0.70))

    # ── Gradient background ───────────────────────────────────────────────────

    def _draw_bg(self):
        c = tk.Canvas(self, width=W, height=H, highlightthickness=0, bd=0)
        c.place(x=0, y=0, relwidth=1, relheight=1)

        # Gradient: dark navy → medium navy
        steps = 50
        for i in range(steps):
            t  = i / steps
            r  = int(9  + (20 - 9)  * t)
            g  = int(14 + (40 - 14) * t)
            b  = int(38 + (80 - 38) * t)
            y0 = int(i * H / steps)
            y1 = int((i + 1) * H / steps)
            c.create_rectangle(0, y0, W, y1,
                               fill=f"#{r:02x}{g:02x}{b:02x}", outline="")

        # Decorative blobs
        c.create_oval(240, -100, 540, 220, fill="#162850", outline="")
        c.create_oval(-120, 320, 160, 570, fill="#0C1B35", outline="")
        c.create_oval(340, 190, 400, 250, fill="#1E3A6A", outline="")

    # ── Floating card ─────────────────────────────────────────────────────────

    def _build_card(self):
        self._card = ctk.CTkFrame(
            self, width=CARD_W, height=CARD_H,
            corner_radius=22, fg_color="#FFFFFF", border_width=0,
        )
        self._card.place(relx=0.5, rely=0.70, anchor="center")
        self._card.lift()
        self._fill_card(self._card)

    def _fill_card(self, card):
        # ── Brand ─────────────────────────────────────────────────────────────
        brand = ctk.CTkFrame(card, fg_color="transparent")
        brand.pack(pady=(26, 0))

        ring = ctk.CTkFrame(brand, width=68, height=68,
                            corner_radius=34, fg_color="#DCFCE7")
        ring.pack()
        ring.pack_propagate(False)
        ctk.CTkLabel(ring, text="✚",
                     font=ctk.CTkFont(size=32, weight="bold"),
                     text_color="#16A34A",
                     ).place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(brand, text="FARMACIA",
                     font=ctk.CTkFont(size=9, weight="bold"),
                     text_color="#16A34A").pack(pady=(9, 0))
        ctk.CTkLabel(brand, text="EBEN-EZER",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#0F172A").pack(pady=(1, 0))
        ctk.CTkLabel(brand, text="Sistema de Punto de Venta",
                     font=ctk.CTkFont(size=10),
                     text_color="#94A3B8").pack(pady=(2, 0))

        # ── Divider ───────────────────────────────────────────────────────────
        ctk.CTkFrame(card, height=1, fg_color="#E2E8F0").pack(
            fill="x", padx=32, pady=(18, 16))

        # ── Form ──────────────────────────────────────────────────────────────
        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=32)

        ctk.CTkLabel(form, text="Usuario",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#374151", anchor="w").pack(anchor="w")
        self.entry_user = ctk.CTkEntry(
            form, placeholder_text="Nombre de usuario",
            height=42, font=ctk.CTkFont(size=12),
            corner_radius=8, border_color="#E2E8F0", fg_color="#F8FAFF",
        )
        self.entry_user.pack(fill="x", pady=(3, 12))

        ctk.CTkLabel(form, text="Contraseña",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color="#374151", anchor="w").pack(anchor="w")
        self.entry_pass = ctk.CTkEntry(
            form, placeholder_text="Contraseña",
            show="•", height=42, font=ctk.CTkFont(size=12),
            corner_radius=8, border_color="#E2E8F0", fg_color="#F8FAFF",
        )
        self.entry_pass.pack(fill="x", pady=(3, 0))

        self.lbl_err = ctk.CTkLabel(card, text="",
                                    text_color="#EF4444",
                                    font=ctk.CTkFont(size=11))
        self.lbl_err.pack(pady=(8, 0))

        self.btn = ctk.CTkButton(
            card, text="Iniciar Sesión",
            height=44, corner_radius=10,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2563EB", hover_color="#1D4ED8",
            command=self._do_login,
        )
        self.btn.pack(fill="x", padx=32, pady=(6, 0))

        # ── Footer ────────────────────────────────────────────────────────────
        ctk.CTkFrame(card, height=1, fg_color="#E2E8F0").pack(
            fill="x", padx=32, pady=(18, 6))
        ctk.CTkLabel(card,
                     text=f"Farmacia Eben-Ezer  ·  v{cfg.VERSION}",
                     font=ctk.CTkFont(size=10),
                     text_color="#94A3B8").pack(pady=(0, 14))

        self.entry_pass.bind("<Return>", lambda e: self._do_login())
        self.entry_user.bind("<Return>", lambda e: self.entry_pass.focus())
        self.entry_user.focus()

    # ── Entrance animation ────────────────────────────────────────────────────

    def _anim(self, alpha, rely):
        alpha = min(1.0, alpha + 0.055)
        rely  = max(0.5,  rely  - 0.022)
        self.attributes("-alpha", alpha)
        self._card.place(relx=0.5, rely=rely, anchor="center")
        if alpha < 1.0 or rely > 0.5:
            self.after(16, lambda: self._anim(alpha, rely))

    # ── Auth logic ────────────────────────────────────────────────────────────

    def _do_login(self):
        u = self.entry_user.get().strip()
        p = self.entry_pass.get()

        if not u or not p:
            self._shake("Ingresa usuario y contraseña")
            return

        self.btn.configure(state="disabled", text="Verificando...")
        self.update()

        user = login(u, p)
        if user:
            self.lbl_err.configure(text="")
            self._open_main(user)
        else:
            self._shake("Usuario o contraseña incorrectos")
            self.entry_pass.delete(0, "end")
            self.btn.configure(state="normal", text="Iniciar Sesión")

    def _shake(self, msg):
        self.lbl_err.configure(text=msg)
        ox, oy = self.winfo_x(), self.winfo_y()
        for i, dx in enumerate([10, -10, 8, -8, 5, -5, 2, -2, 0]):
            self.after(i * 36, lambda x=dx: self.geometry(f"+{ox+x}+{oy}"))

    def _open_main(self, user):
        from app.ui.main_window import MainWindow
        self.withdraw()
        main = MainWindow(user, on_logout=self._on_logout)
        main.mainloop()

    def _on_logout(self):
        self.entry_user.delete(0, "end")
        self.entry_pass.delete(0, "end")
        self.lbl_err.configure(text="")
        self.btn.configure(state="normal", text="Iniciar Sesión")
        self.deiconify()
        self.entry_user.focus()
