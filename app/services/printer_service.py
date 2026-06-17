from datetime import datetime
from pathlib import Path
import traceback
import app.config as cfg

_LOG = cfg.DATA_DIR / "printer.log"

def _log(msg: str):
    try:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

# Reemplaza acentos y chars especiales a ASCII puro — compatible con cualquier codepage del POS
_CHAR_MAP = str.maketrans({
    'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
    'Á': 'A', 'É': 'E', 'Í': 'I', 'Ó': 'O', 'Ú': 'U',
    'ñ': 'n', 'Ñ': 'N', 'ü': 'u', 'Ü': 'U',
    'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
    'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
    '¡': '!', '¿': '?',
})

def _s(text: str) -> str:
    return str(text).translate(_CHAR_MAP)


class PrinterService:
    def __init__(self):
        self.printer = None
        self.connected = False
        self.printer_type = "usb"
        self.printer_name = ""
        self.width = 32  # 32 = 58mm | 48 = 80mm

    # ── Conexión ──────────────────────────────────────────────────────────────

    def connect(self, printer_type: str = "usb", port: str = None):
        self.printer_type = printer_type
        _log(f"Intentando conectar: tipo={printer_type}, port={port}")
        
        try:
            if printer_type == "windows":
                return self._connect_windows(port)

            from escpos import printer as ep
            if printer_type == "usb":
                try:
                    # Lista de VIDs/PIDs comunes
                    common_vids = [
                        (0x04b8, 0x0202), (0x0416, 0x5011), (0x1fc9, 0x2016),
                        (0x0fe6, 0x811e), (0x1ee1, 0x0001), (0x0483, 0x5740),
                        (0x0519, 0x0001), (0x1504, 0x0001),
                    ]
                    
                    success = False
                    for vid, pid in common_vids:
                        try:
                            self.printer = ep.Usb(vid, pid)
                            success = True
                            _log(f"Conectado USB: {hex(vid)}:{hex(pid)}")
                            break
                        except: continue
                    
                    if not success:
                        # Fallback a windows si USB falla
                        _log("USB falló, intentando fallback a modo Windows...")
                        if self._connect_windows(port):
                            self._save_auto_detected_config("windows", self.printer_name)
                            return True
                        raise Exception("No se encontró impresora USB compatible")
                    
                    self.connected = True
                    return True
                except Exception as e:
                    _log(f"Error USB: {e}")
                    # Último intento: fallback a windows
                    if self._connect_windows(port):
                        self._save_auto_detected_config("windows", self.printer_name)
                        return True
                    raise e
                    
            elif printer_type == "serial":
                self.printer = ep.Serial(port or "COM1", baudrate=9600)
            elif printer_type == "network":
                host, p = (port or "192.168.1.100:9100").split(":")
                self.printer = ep.Network(host, int(p))
            
            self.connected = True
            return True
        except Exception as e:
            _log(f"Error crítico conectando: {e}")
            self.connected = False
            return False

    def _connect_windows(self, name: str = None) -> bool:
        try:
            import win32print
            all_printers = self.list_windows_printers()
            if not all_printers: return False

            # 1. Exact match
            if name and name in all_printers:
                self.printer_name = name
                self.connected = True
                self.printer_type = "windows"
                return True
            
            # 2. Keymatch / Fuzzy
            keywords = ["POS", "58", "80", "TICKET", "EPSON", "GENERIC", "XP-", "RP", "GOOJ", "IMPRESORA"]
            best_match = None
            
            # Search by keyword
            for p in all_printers:
                p_up = p.upper()
                if any(k in p_up for k in keywords):
                    best_match = p
                    break
            
            # Search by similarity
            if not best_match and name:
                import difflib
                m = difflib.get_close_matches(name, all_printers, n=1, cutoff=0.4)
                if m: best_match = m[0]

            if not best_match:
                try: best_match = win32print.GetDefaultPrinter()
                except: pass

            if best_match:
                _log(f"Windows Auto-detect: {best_match}")
                self.printer_name = best_match
                self.connected = True
                self.printer_type = "windows"
                return True
            
            return False
        except Exception as e:
            _log(f"Error _connect_windows: {e}")
            return False

    def _save_auto_detected_config(self, tipo: str, name: str):
        """Persiste tipo y nombre en la DB."""
        try:
            from app.database.connection import get_db_session
            from app.database.models import Configuracion
            import threading
            def _save():
                db = get_db_session()
                try:
                    for k, v in [("impresora_tipo", tipo), ("impresora_nombre", name)]:
                        c = db.query(Configuracion).filter(Configuracion.clave == k).first()
                        if c: c.valor = v
                        else: db.add(Configuracion(clave=k, valor=v))
                    db.commit()
                except: db.rollback()
                finally: db.close()
            threading.Thread(target=_save, daemon=True).start()
        except: pass

    @staticmethod
    def list_windows_printers() -> list:
        all_found = []
        _log("Iniciando enumeración exhaustiva de impresoras...")
        
        # 1. win32print (Método estándar)
        try:
            import win32print
            for flags in [win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS,
                          win32print.PRINTER_ENUM_NAME]:
                try:
                    all_found.extend([p[2] for p in win32print.EnumPrinters(flags)])
                except: pass
        except Exception as e:
            _log(f"Error cargando win32print: {e}")
        
        # 2. PowerShell (Muy fiable en Win10/11)
        try:
            import subprocess
            cmd = ["powershell", "-NoProfile", "-Command", "Get-Printer | Select-Object -ExpandProperty Name"]
            res = subprocess.check_output(cmd, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            ps_names = [line.strip() for line in res.splitlines() if line.strip()]
            all_found.extend(ps_names)
        except Exception as e:
            _log(f"Error en PowerShell: {e}")

        # 3. WMIC (Fallback para sistemas antiguos o restringidos)
        try:
            import subprocess
            cmd = ["wmic", "printer", "get", "name"]
            res = subprocess.check_output(cmd, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            # El output de wmic suele tener headers y espacios extras
            wmic_names = [line.strip() for line in res.splitlines() if line.strip() and line.strip().lower() != "name"]
            all_found.extend(wmic_names)
        except Exception as e:
            _log(f"Error en WMIC: {e}")

        # 4. Impresora predeterminada
        try:
            import win32print
            default = win32print.GetDefaultPrinter()
            if default: all_found.append(default)
        except: pass
            
        final_list = sorted(list(set(all_found)))
        _log(f"Enumeración completada. Encontradas ({len(final_list)}): {final_list}")
        return final_list

    # ── Impresión ─────────────────────────────────────────────────────────────

    def print_receipt(self, venta_data: dict, farmacia_config: dict = None):
        if farmacia_config is None:
            farmacia_config = self._load_farmacia_config()

        w = farmacia_config.get("impresora_ancho", "32")
        self.width = int(w) if str(w).isdigit() else 32

        tipo   = farmacia_config.get("impresora_tipo",   "windows")
        puerto = farmacia_config.get("impresora_nombre") or farmacia_config.get("impresora_puerto", "")

        if not self.connected:
            _log(f"Auto-conectando: tipo={tipo} puerto={puerto}")
            self.connect(tipo, puerto or None)
            _log(f"connected={self.connected}")

        if not self.connected:
            _log("No conectada - simulando en consola")
            self._print_to_console(venta_data, farmacia_config)
            return False

        # Abrir cajón para pagos en efectivo o mixto
        metodo_pago = venta_data.get("metodo_pago", "")
        if metodo_pago in ("efectivo", "mixto"):
            self.open_cash_drawer()

        try:
            _log(f"Imprimiendo via tipo={self.printer_type} nombre={self.printer_name}")
            if self.printer_type == "windows":
                result = self._print_windows(venta_data, farmacia_config)
                if not result:
                    _log("Fallo impresion Windows, reintentando con reconexion...")
                    self.connected = False
                    self.connect(tipo, puerto or None)
                    result = self._print_windows(venta_data, farmacia_config)
                _log(f"resultado final: {result}")
                return result

            if not self.printer:
                _log("ESC/POS: printer es None")
                self._print_to_console(venta_data, farmacia_config)
                return False

            try:
                return self._print_escpos(venta_data, farmacia_config)
            except Exception:
                _log("Fallo ESC/POS, reintentando con reconexion...")
                self.connected = False
                self.connect(tipo, puerto or None)
                return self._print_escpos(venta_data, farmacia_config)

        except Exception:
            _log(f"EXCEPCION FINAL: {traceback.format_exc()}")
            return False

    # ── Helpers de texto ─────────────────────────────────────────────────────

    @staticmethod
    def _word_wrap(text: str, width: int) -> list[str]:
        """Word-wrap text into lines of at most `width` chars."""
        if not text:
            return []
        words = str(text).split()
        result, line = [], ""
        for word in words:
            candidate = (line + " " + word).strip() if line else word
            if len(candidate) <= width:
                line = candidate
            else:
                if line:
                    result.append(line)
                # Hard-break word if single word longer than width
                while len(word) > width:
                    result.append(word[:width])
                    word = word[width:]
                line = word
        if line:
            result.append(line)
        return result

    def _ctr(self, txt: str) -> str:
        """Center text; word-wrap if longer than width (never silently truncate)."""
        lines = self._word_wrap(str(txt).strip(), self.width)
        return "\n".join(l.center(self.width) for l in lines) if lines else ""

    def _left(self, label: str, value: str) -> str:
        """Left label + right-aligned value, same row."""
        val  = str(value)
        room = self.width - len(val)
        if room < 1:
            return (label + " " + val)[:self.width]
        return f"{label:<{room}}{val}"

    # ── Cajón de dinero ───────────────────────────────────────────────────────

    def open_cash_drawer(self) -> bool:
        """Send ESC/POS cash-drawer kick pulse."""
        ESC_P = b'\x1b\x70\x00\x19\xfa'   # ESC p 0 25 250
        try:
            if self.printer_type == "windows" and self.connected:
                import win32print
                hP = win32print.OpenPrinter(self.printer_name)
                try:
                    win32print.StartDocPrinter(hP, 1, ("Cajon", None, "RAW"))
                    win32print.StartPagePrinter(hP)
                    win32print.WritePrinter(hP, ESC_P)
                    win32print.EndPagePrinter(hP)
                    win32print.EndDocPrinter(hP)
                finally:
                    win32print.ClosePrinter(hP)
                return True
            elif self.printer:
                self.printer._raw(ESC_P)
                return True
        except Exception:
            _log(f"open_cash_drawer: {traceback.format_exc()}")
        return False

    # ── Construcción del ticket de venta ─────────────────────────────────────

    def _build_ticket(self, venta_data: dict, farmacia_config: dict) -> str:
        cfg_d = farmacia_config or {}
        nombre    = _s(cfg_d.get("farmacia_nombre",    cfg.PHARMACY_NAME)).upper()
        direccion = _s(cfg_d.get("farmacia_direccion", cfg.PHARMACY_ADDRESS)).upper()
        W = self.width

        sep  = "=" * W
        sep2 = "-" * W

        # Column widths adapt to paper size
        # 50mm (W<=28): qty "2x " = 4 chars, price = 7 chars
        # 58mm (W<=36): qty "2 PZ " = 6 chars, price = 9 chars
        # 80mm (W>36) : qty "2 PZ " = 6 chars, price = 10 chars
        if W <= 28:
            QTY_W   = 4
            PRICE_W = 7
        elif W <= 36:
            QTY_W   = 6
            PRICE_W = 9
        else:
            QTY_W   = 6
            PRICE_W = 10
        NAME_W = max(8, W - QTY_W - PRICE_W)

        def money(v):
            n = float(v or 0)
            # omit thousands separator on narrow paper to save chars
            return f"${n:,.2f}" if W > 28 else f"${n:.2f}"

        def tot(label, value):
            val_str = money(value) if isinstance(value, (int, float)) else str(value)
            lbl_w = max(1, W - len(val_str))
            return f"{label:<{lbl_w}}{val_str}"

        # ── Header ────────────────────────────────────────────────────────────
        lines = [sep]
        for ln in self._word_wrap(nombre, W):
            lines.append(ln.center(W))
        for ln in self._word_wrap(direccion, W):
            lines.append(ln.center(W))
        lines.append(sep)

        # Cajero / cliente
        cajero = _s(venta_data.get("cajero", "N/A")).upper()
        for ln in self._word_wrap(f"CAJ: {cajero}" if W <= 28 else f"CAJERO: {cajero}", W):
            lines.append(ln.center(W))
        if venta_data.get("cliente"):
            cli_line = f"CLI: {_s(venta_data['cliente']).upper()}" if W <= 28 else f"CLIENTE: {_s(venta_data['cliente']).upper()}"
            for ln in self._word_wrap(cli_line, W):
                lines.append(ln.center(W))
        lines.append(sep)

        # ── Tabla de productos ────────────────────────────────────────────────
        hdr_qty  = "QTY" if W <= 28 else "CANT"
        hdr_name = "DESCRIPCION"
        hdr_prc  = "PRECIO"
        lines.append(f"{hdr_qty:<{QTY_W}}{hdr_name:<{NAME_W}}{hdr_prc:>{PRICE_W}}")
        lines.append(sep2)

        num_articulos = 0
        for item in venta_data.get("items", []):
            cant       = int(item.get("cantidad", 1))
            sub        = float(item.get("subtotal", 0.0))
            num_articulos += cant
            prod_full  = _s(item.get("nombre", "")).upper()
            price_str  = money(sub)

            # qty prefix: compact on 50mm
            if W <= 28:
                qty_prefix = f"{cant}x".ljust(QTY_W)
            else:
                qty_prefix = f"{cant:>2} PZ "  # always 6 chars

            # Adapt name width if price_str is longer than PRICE_W (prevents overflow)
            eff_price_w = max(PRICE_W, len(price_str))
            eff_name_w  = max(4, W - QTY_W - eff_price_w)
            name_first = prod_full[:eff_name_w]
            lines.append(f"{qty_prefix}{name_first:<{eff_name_w}}{price_str:>{eff_price_w}}")
            resto = prod_full[eff_name_w:]
            indent = " " * QTY_W
            while resto:
                chunk, resto = resto[:eff_name_w], resto[eff_name_w:]
                lines.append(f"{indent}{chunk}")

        # ── Totales ───────────────────────────────────────────────────────────
        lines.append(sep)
        subtotal  = float(venta_data.get("subtotal",   0.0))
        descuento = float(venta_data.get("descuento",  0.0))
        iva       = float(venta_data.get("iva",         0.0))
        total     = float(venta_data.get("total",       0.0))
        pagado    = float(venta_data.get("monto_pagado",0.0))
        cambio    = float(venta_data.get("cambio",      0.0))
        metodo    = _s(venta_data.get("metodo_pago", "efectivo")).upper()

        if descuento > 0:
            lines.append(tot("SUBTOTAL:", money(subtotal)))
            lines.append(tot("DESCUENTO:", money(descuento)))
        if iva > 0:
            lines.append(tot("IVA (16%):", money(iva)))
        lines.append(tot("TOTAL:", money(total)))
        lines.append(sep2)
        lines.append(tot(f"{metodo}:", money(pagado)))
        lines.append(tot("CAMBIO:", money(cambio)))
        lines.append(sep)

        # Info inferior
        lines.append(f"ARTICULOS: {num_articulos}")
        lines.append(f"FOLIO: {venta_data.get('folio', 'N/A')}")
        lines.append(f"FECHA: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        lines += [sep, "GRACIAS POR SU COMPRA".center(W), "CONSERVE SU TICKET".center(W), sep, "", "", ""]
        return "\n".join(lines)

    # ── Ticket de retiro de caja ──────────────────────────────────────────────

    def _build_retiro_ticket(self, retiro_data: dict, farmacia_config: dict) -> str:
        cfg_d = farmacia_config or {}
        nombre   = _s(cfg_d.get("farmacia_nombre", cfg.PHARMACY_NAME)).upper()
        telefono = _s(cfg_d.get("farmacia_telefono", cfg.PHARMACY_PHONE)).upper()
        W = self.width

        sep  = "=" * W
        sep2 = "-" * W

        def money(v):
            return f"${float(v or 0):,.2f}"

        def tot(label, value_str):
            room = W - len(value_str)
            room = max(1, room)
            return f"{label:<{room}}{value_str}"

        lines = [sep]
        for ln in self._word_wrap(nombre, W):
            lines.append(ln.center(W))
        if telefono:
            lines.append(f"TEL: {telefono}".center(W))
        lines.append(sep)
        lines.append("RETIRO DE EFECTIVO DE CAJA".center(W))
        lines.append(sep)

        fecha   = retiro_data.get("fecha", datetime.now().strftime("%d/%m/%Y %H:%M"))
        admin   = _s(retiro_data.get("admin", "Administrador")).upper()
        concepto = _s(retiro_data.get("concepto", "Sin concepto")).upper()
        monto   = float(retiro_data.get("monto", 0.0))

        lines.append(f"FECHA:   {fecha}")
        lines.append(f"ADMIN:   {admin}")
        lines.append(sep2)
        lines.append("CONCEPTO:")
        for ln in self._word_wrap(concepto, W - 2):
            lines.append(f"  {ln}")
        lines.append(sep2)
        lines.append(tot("MONTO RETIRADO:", money(monto)))
        lines.append(sep)
        lines.append("FIRMA AUTORIZADA:".center(W))
        lines.append("")
        lines.append(("_" * min(22, W - 4)).center(W))
        lines += [sep, "", "", ""]
        return "\n".join(lines)

    def print_retiro(self, retiro_data: dict, farmacia_config: dict = None) -> bool:
        """Open cash drawer then print retiro ticket."""
        if farmacia_config is None:
            farmacia_config = self._load_farmacia_config()

        w = farmacia_config.get("impresora_ancho", "32")
        self.width = int(w) if str(w).isdigit() else 32
        tipo   = farmacia_config.get("impresora_tipo",   "windows")
        puerto = farmacia_config.get("impresora_nombre") or farmacia_config.get("impresora_puerto", "")

        if not self.connected:
            _log(f"print_retiro auto-connect: tipo={tipo} puerto={puerto}")
            self.connect(tipo, puerto or None)

        self.open_cash_drawer()

        if not self.connected:
            _log("print_retiro: no conectada — solo cajón")
            return False

        try:
            ticket = self._build_retiro_ticket(retiro_data, farmacia_config)
            _log(f"print_retiro via tipo={self.printer_type}")
            if self.printer_type == "windows":
                return self._print_raw_text(ticket, "Retiro Caja")
            if self.printer:
                self.printer.set(align="left", bold=False, height=1, width=1)
                self.printer.text(ticket + "\n")
                self.printer.cut()
                return True
        except Exception:
            _log(f"print_retiro error: {traceback.format_exc()}")
        return False

    def _print_raw_text(self, text: str, doc_name: str = "Ticket") -> bool:
        """Send text as RAW ESC/POS to Windows printer."""
        try:
            import win32print
            ESC = b'\x1b'
            raw = (ESC + b'@' +
                   text.encode("ascii", errors="replace") +
                   b'\n\n\n\n' +
                   ESC + b'm')
            hP = win32print.OpenPrinter(self.printer_name)
            try:
                win32print.StartDocPrinter(hP, 1, (doc_name, None, "RAW"))
                win32print.StartPagePrinter(hP)
                win32print.WritePrinter(hP, raw)
                win32print.EndPagePrinter(hP)
                win32print.EndDocPrinter(hP)
            finally:
                win32print.ClosePrinter(hP)
            return True
        except Exception:
            _log(f"_print_raw_text error: {traceback.format_exc()}")
            return False

    # ── Rutas de impresión ────────────────────────────────────────────────────

    def _print_windows(self, venta_data: dict, farmacia_config: dict) -> bool:
        try:
            import win32print
            import win32ui
            import win32con

            ticket = self._build_ticket(venta_data, farmacia_config)
            
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(self.printer_name)

            # Compute char height dynamically so self.width chars fit the printable area.
            # HORZRES = printable page width in device pixels (respects actual paper size).
            page_w = hDC.GetDeviceCaps(win32con.HORZRES)
            margin = max(5, page_w // 50)          # ~2% left+right margin
            usable = page_w - margin * 2
            # Courier New monospace: char_width ~= char_height * 0.60
            char_h = max(10, int(usable / self.width / 0.60))
            line_h = int(char_h * 1.30)

            hDC.StartDoc("Ticket Farmacia")
            hDC.StartPage()

            font = win32ui.CreateFont({
                "name":   "Courier New",
                "height": -char_h,
                "weight": 500,
            })
            hDC.SelectObject(font)
            hDC.SetTextColor(0)

            y = margin
            for line in ticket.split("\n"):
                if not line.strip() and y > margin:
                    y += line_h // 2
                    continue
                hDC.TextOut(margin, y, line)
                y += line_h

            hDC.EndPage()
            hDC.EndDoc()
            hDC.DeleteDC()
            return True
        except Exception:
            _log(f"EXCEPCION _print_windows: {traceback.format_exc()}")
            # Si GDI falla o sale en blanco, el modo RAW es el salvavidas
            return self._print_windows_raw(venta_data, farmacia_config)

    def _print_windows_raw(self, venta_data: dict, farmacia_config: dict) -> bool:
        ticket = self._build_ticket(venta_data, farmacia_config)
        return self._print_raw_text(ticket, "Ticket RAW")

    def _print_escpos(self, venta_data: dict, farmacia_config: dict) -> bool:
        # Usa el mismo texto que _build_ticket — evita duplicar lógica
        ticket = self._build_ticket(venta_data, farmacia_config)
        p = self.printer
        p.set(align="left", bold=False, height=1, width=1)
        p.text(ticket + "\n")
        p.cut()
        return True

    def _print_to_console(self, venta_data: dict, farmacia_config: dict = None):
        print(self._build_ticket(venta_data, farmacia_config or {}))

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_farmacia_config(self) -> dict:
        try:
            from app.database.connection import get_db_session
            from app.database.models import Configuracion
            db = get_db_session()
            try:
                return {c.clave: c.valor for c in db.query(Configuracion).all()}
            finally:
                db.close()
        except Exception:
            return {}

    def _save_auto_detected_name(self, name: str):
        """Persiste el nombre auto-detectado en la base de datos."""
        try:
            from app.database.connection import get_db_session
            from app.database.models import Configuracion
            import threading
            
            def _save():
                db = get_db_session()
                try:
                    c = db.query(Configuracion).filter(Configuracion.clave == "impresora_nombre").first()
                    if c:
                        c.valor = name
                    else:
                        db.add(Configuracion(clave="impresora_nombre", valor=name))
                    db.commit()
                except:
                    db.rollback()
                finally:
                    db.close()
            
            # Ejecutar en hilo separado para no bloquear la impresion
            threading.Thread(target=_save, daemon=True).start()
        except:
            pass

    def test_printer(self) -> bool:
        if not self.connected:
            return False
        try:
            if self.printer_type == "windows":
                # Usar GDI para el test (igual que el ticket real) porque RAW falla en muchos drivers
                import win32ui
                import win32con
                
                hDC = win32ui.CreateDC()
                hDC.CreatePrinterDC(self.printer_name)
                hDC.StartDoc("Test Farmacia")
                hDC.StartPage()
                
                font = win32ui.CreateFont({"name": "Courier New", "height": -15, "weight": 400})
                hDC.SelectObject(font)
                
                hDC.TextOut(10, 10, "================================")
                hDC.TextOut(10, 40, "   TEST DE IMPRESION OK")
                hDC.TextOut(10, 70, f"   IMPRESORA: {self.printer_name}")
                hDC.TextOut(10, 100, f"   FECHA: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
                hDC.TextOut(10, 130, "================================")
                hDC.TextOut(10, 160, " ")
                hDC.TextOut(10, 190, " ")
                
                hDC.EndPage()
                hDC.EndDoc()
                hDC.DeleteDC()
                return True

            if self.printer:
                self.printer.text("Test de impresion OK\n")
                self.printer.cut()
                return True
        except Exception as e:
            _log(f"test_printer error: {traceback.format_exc()}")
        return False


printer_service = PrinterService()
