"""Animated toast notifications — slide in/out from bottom-right."""
import customtkinter as ctk

_STYLES = {
    "success": {"accent": "#22C55E", "icon": "✓"},
    "error":   {"accent": "#EF4444", "icon": "✕"},
    "warning": {"accent": "#F59E0B", "icon": "⚠"},
    "info":    {"accent": "#3B82F6", "icon": "ℹ"},
}

TOAST_W   = 310
PAD_X     = 16
PAD_Y     = 16
GAP       = 8

_manager = None


def init(root):
    global _manager
    _manager = _Manager(root)


def show(message: str, kind: str = "info", title: str = "", duration: int = 3500):
    if _manager:
        _manager.show(message, kind, title, duration)


# ── Manager ───────────────────────────────────────────────────────────────────

class _Manager:
    def __init__(self, root):
        self.root  = root
        self.stack: list[_Toast] = []

    def show(self, msg, kind, title, dur):
        self.root.after(60, lambda: self._spawn(msg, kind, title, dur))

    def _spawn(self, msg, kind, title, dur):
        t = _Toast(self.root, msg, kind, title, dur, self._done)
        self.stack.append(t)
        self._relayout()

    def _done(self, t):
        if t in self.stack:
            self.stack.remove(t)
        self._relayout()

    def _relayout(self):
        win_w = self.root.winfo_width()
        win_h = self.root.winfo_height()
        y = win_h - PAD_Y
        for t in reversed(self.stack):
            if not t.winfo_exists():
                continue
            t.update_idletasks()
            h = max(t.winfo_reqheight(), 58)
            y -= h
            t._final_x = win_w - TOAST_W - PAD_X
            t._final_y = y
            info = t.place_info()
            cur_x = int(float(info.get("x", win_w + 10))) if info else win_w + 10
            t.place(x=cur_x, y=y)
            t.lift()
            y -= GAP


# ── Toast widget ──────────────────────────────────────────────────────────────

class _Toast(ctk.CTkFrame):
    def __init__(self, parent, msg, kind, title, dur, done_cb):
        s = _STYLES.get(kind, _STYLES["info"])
        super().__init__(
            parent,
            width=TOAST_W,
            corner_radius=10,
            fg_color=("#FFFFFF", "#1E293B"),
            border_width=1,
            border_color=("#E2E8F0", "#334155"),
        )
        self._done     = done_cb
        self._gone     = False
        self._final_x  = parent.winfo_width() - TOAST_W - PAD_X
        self._final_y  = 0

        self.grid_columnconfigure(2, weight=1)

        # Left accent strip
        strip = ctk.CTkFrame(self, width=4, corner_radius=2, fg_color=s["accent"])
        strip.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(4, 0), pady=4)

        # Icon badge
        ib = ctk.CTkFrame(self, width=30, height=30, corner_radius=15, fg_color=s["accent"])
        ib.grid(row=0, column=1, padx=(10, 0), pady=(10, 0), sticky="n")
        ib.grid_propagate(False)
        ctk.CTkLabel(
            ib, text=s["icon"],
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white",
        ).place(relx=0.5, rely=0.5, anchor="center")

        # Text block
        tf = ctk.CTkFrame(self, fg_color="transparent")
        tf.grid(row=0, column=2, sticky="ew", padx=(8, 4), pady=(8, 8))
        if title:
            ctk.CTkLabel(
                tf, text=title,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=(s["accent"],) * 2,
                anchor="w",
            ).pack(anchor="w")
        ctk.CTkLabel(
            tf, text=msg,
            font=ctk.CTkFont(size=11),
            text_color=("#374151", "#CBD5E1"),
            wraplength=TOAST_W - 100,
            justify="left",
            anchor="w",
        ).pack(anchor="w", pady=(2 if title else 0, 0))

        # Close button
        ctk.CTkButton(
            self, text="✕", width=20, height=20,
            corner_radius=10,
            fg_color="transparent",
            text_color=("#94A3B8", "#64748B"),
            hover_color=("#F1F5F9", "#334155"),
            font=ctk.CTkFont(size=10),
            command=self._dismiss,
        ).grid(row=0, column=3, sticky="ne", padx=(0, 6), pady=(6, 0))

        # Progress bar
        self._pb = ctk.CTkProgressBar(
            self, height=3, corner_radius=0,
            fg_color=("transparent", "transparent"),
            progress_color=s["accent"],
        )
        self._pb.set(1.0)
        self._pb.grid(row=1, column=0, columnspan=4, sticky="ew", padx=4, pady=(0, 4))

        # Start off-screen right
        parent.update_idletasks()
        self.place(x=parent.winfo_width() + 10, y=0)
        self.lift()
        self.after(20, self._slide_in)

        # Progress starts after slide (~280ms)
        prog_dur = max(200, dur - 280)
        self.after(280, lambda: self._tick(prog_dur, prog_dur))

        # Auto-dismiss
        self.after(dur, self._dismiss)

    # ── Animation ─────────────────────────────────────────────────────────────

    def _slide_in(self):
        if not self.winfo_exists() or self._gone:
            return
        info = self.place_info()
        cur_x = int(float(info.get("x", 9999)))
        fx    = self._final_x
        if cur_x > fx:
            step = max(18, (cur_x - fx) // 3)
            self.place(x=cur_x - step)
            self.after(16, self._slide_in)

    def _tick(self, rem, total):
        if not self.winfo_exists() or self._gone:
            return
        self._pb.set(max(0.0, rem / total))
        if rem > 16:
            self.after(16, lambda: self._tick(rem - 16, total))

    def _dismiss(self):
        if self._gone:
            return
        self._gone = True
        self._slide_out()

    def _slide_out(self):
        if not self.winfo_exists():
            self._done(self)
            return
        info = self.place_info()
        if not info:
            self._done(self)
            return
        cur_x = int(float(info.get("x", 0)))
        tgt   = self.master.winfo_width() + 10
        if cur_x < tgt:
            step = max(20, (tgt - cur_x) // 2)
            self.place(x=cur_x + step)
            self.after(16, self._slide_out)
        else:
            self.destroy()
            self._done(self)
