"""
Scanner service — three modes:

  HID_HOOK (primary):
       Uses the 'keyboard' module to hook keystrokes at OS level.
       Works for ANY scanner: USB, Bluetooth HID, wireless dongle.
       Distinguishes scanner (burst of chars < 50ms apart) from human typing.
       Does NOT require admin on Windows.

  SERIAL (SPP / Bluetooth COM / USB-CDC / RS-232):
       Background thread reads a COM port line-by-line.

  BIND (fallback):
       Tkinter bind_all — used by main_window as last resort.
"""
from __future__ import annotations

import threading
import time
from typing import Callable


class ScannerService:
    BAUD_RATES = [9600, 115200, 38400, 19200, 4800, 2400]

    # Max milliseconds between consecutive chars to be considered a scanner burst
    HID_CHAR_GAP_MS = 80

    def __init__(self, on_barcode: Callable[[str], None]):
        self.on_barcode = on_barcode

        # Serial state
        self._serial_thread: threading.Thread | None = None
        self._serial_stop = threading.Event()
        self._serial_port: str | None = None
        self._serial_baud: int = 9600
        self._serial_running = False

        # HID hook state
        self._hid_running = False
        self._hid_buf: list[str] = []
        self._hid_last_time: float = 0.0
        self._hid_timer: threading.Timer | None = None
        self._hid_lock = threading.Lock()

    # ── HID hook mode (keyboard module) ──────────────────────────────────────

    def start_hid_hook(self) -> bool:
        """Hook OS-level keyboard events. Returns True on success."""
        if self._hid_running:
            return True
        try:
            import keyboard as kb
        except ImportError:
            print("[Scanner] 'keyboard' module not available")
            return False

        self._hid_buf = []
        self._hid_last_time = 0.0

        def on_key(event):
            if event.event_type != "down":
                return
            self._hid_on_key(event.name)

        try:
            kb.hook(on_key, suppress=False)
            self._hid_running = True
            print("[Scanner] HID hook started (OS-level keyboard capture)")
            return True
        except Exception as e:
            print(f"[Scanner] HID hook failed: {e}")
            return False

    def stop_hid_hook(self):
        if self._hid_running:
            try:
                import keyboard as kb
                kb.unhook_all()
            except Exception:
                pass
            self._hid_running = False
            self._hid_buf = []
            print("[Scanner] HID hook stopped")

    def _hid_on_key(self, name: str):
        now = time.monotonic() * 1000  # ms

        with self._hid_lock:
            # Large gap → user is typing manually, reset buffer
            if self._hid_buf and (now - self._hid_last_time) > self.HID_CHAR_GAP_MS:
                self._hid_buf.clear()

            self._hid_last_time = now

            # Cancel pending flush timer
            if self._hid_timer:
                self._hid_timer.cancel()
                self._hid_timer = None

            # Terminator chars → flush immediately
            if name in ("enter", "kp enter", "return", "tab", "\r", "\n"):
                buf = "".join(self._hid_buf).strip()
                self._hid_buf.clear()
                if len(buf) >= 4:
                    print(f"[Scanner] HID barcode (terminator): {buf}")
                    self._fire(buf)
                return

            # Accumulate printable single chars
            if len(name) == 1 and name.isprintable():
                self._hid_buf.append(name)
            elif name.startswith("shift+") and len(name) == 7:
                # shift+a → A  (some HID scanners send shifted chars)
                self._hid_buf.append(name[-1].upper())
            else:
                return  # Ignore special keys (ctrl, alt, F-keys, etc.)

            # Schedule timeout flush — catches scanners that don't send Enter
            buf_snapshot = list(self._hid_buf)
            def _timeout_flush(snapshot=buf_snapshot):
                with self._hid_lock:
                    if self._hid_buf == snapshot and len(self._hid_buf) >= 4:
                        buf = "".join(self._hid_buf).strip()
                        self._hid_buf.clear()
                        print(f"[Scanner] HID barcode (timeout): {buf}")
                        self._fire(buf)

            self._hid_timer = threading.Timer(self.HID_CHAR_GAP_MS / 1000, _timeout_flush)
            self._hid_timer.daemon = True
            self._hid_timer.start()

    def _fire(self, barcode: str):
        try:
            self.on_barcode(barcode)
        except Exception as e:
            print(f"[Scanner] Callback error: {e}")

    # ── Serial mode ──────────────────────────────────────────────────────────

    def start_serial(self, port: str, baud: int = 9600) -> bool:
        self.stop_serial()
        try:
            import serial
            ser = serial.Serial(port, baud, timeout=1)
        except Exception as e:
            print(f"[Scanner] Cannot open {port}: {e}")
            return False

        self._serial_port = port
        self._serial_baud = baud
        self._serial_stop.clear()
        self._serial_running = True
        self._serial_thread = threading.Thread(
            target=self._serial_loop, args=(ser,), daemon=True, name="scanner-serial"
        )
        self._serial_thread.start()
        print(f"[Scanner] Serial mode on {port} @ {baud}")
        return True

    def stop_serial(self):
        if self._serial_running:
            self._serial_stop.set()
            self._serial_running = False
            if self._serial_thread:
                self._serial_thread.join(timeout=2)
            self._serial_thread = None
            self._serial_port = None
            print("[Scanner] Serial mode stopped")

    def _serial_loop(self, ser):
        import serial
        buf = b""
        while not self._serial_stop.is_set():
            try:
                chunk = ser.read(64)
                if not chunk:
                    continue
                buf += chunk
                while b"\n" in buf or b"\r" in buf:
                    for sep in (b"\r\n", b"\n", b"\r"):
                        if sep in buf:
                            line, buf = buf.split(sep, 1)
                            barcode = line.decode("ascii", errors="ignore").strip()
                            if barcode:
                                print(f"[Scanner] Serial barcode: {barcode}")
                                self._fire(barcode)
                            break
                    else:
                        break
            except serial.SerialException as e:
                print(f"[Scanner] Port error: {e}")
                break
            except Exception:
                time.sleep(0.1)
        try:
            ser.close()
        except Exception:
            pass

    # ── Port discovery ────────────────────────────────────────────────────────

    @staticmethod
    def list_ports() -> list[dict]:
        try:
            from serial.tools import list_ports
            return [
                {"device": p.device, "description": p.description, "hwid": p.hwid}
                for p in list_ports.comports()
            ]
        except Exception:
            return []

    @staticmethod
    def auto_detect() -> str | None:
        try:
            import serial
            from serial.tools import list_ports
        except ImportError:
            return None
        for p in list_ports.comports():
            try:
                ser = serial.Serial(p.device, 9600, timeout=0.5)
                ser.close()
                return p.device
            except Exception:
                continue
        return None

    # ── Status ────────────────────────────────────────────────────────────────

    @property
    def is_serial_running(self) -> bool:
        return self._serial_running

    @property
    def is_hid_running(self) -> bool:
        return self._hid_running

    @property
    def active_port(self) -> str | None:
        return self._serial_port


scanner_service = ScannerService(on_barcode=lambda b: None)
