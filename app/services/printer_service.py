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
                import win32print
                all_printers = self.list_windows_printers()
                _log(f"Impresoras encontradas en el sistema: {all_printers}")
                
                if not all_printers:
                    _log("ERROR: No se detectaron impresoras instaladas en Windows.")
                    self.connected = False
                    return False

                # 1. Intentar con el nombre exacto
                name = port
                if name and name in all_printers:
                    _log(f"Conexión exitosa por nombre exacto: {name}")
                    self.printer_name = name
                    self.connected = True
                    return True
                
                # 2. Buscar uno que parezca ticketera (ampliado)
                keywords = [
                    "POS", "58", "80", "TICKET", "EPSON", "GENERIC", "IMPRESORA", 
                    "ZJIANG", "XPRINTER", "STAR", "BIXOLON", "TM-T", "SRP", "XP-",
                    "RECEIPT", "MINIPRINTER", "THERMAL", "RP80", "RP58", "GOOJPRT",
                    "HOIN", "MUNBYN", "PANTUM", "GPRINTER", "TEXT"
                ]
                best_match = None
                
                # Primero buscar coincidencias que contengan el nombre original
                if name:
                    name_up = name.upper()
                    for p in all_printers:
                        p_up = p.upper()
                        if name_up in p_up or p_up in name_up:
                            best_match = p
                            _log(f"Coincidencia parcial con nombre original: {p}")
                            break
                
                # Si no, buscar por palabras clave
                if not best_match:
                    for p in all_printers:
                        p_upper = p.upper()
                        if any(k in p_upper for k in keywords):
                            best_match = p
                            _log(f"Coincidencia por palabra clave: {p}")
                            break

                # Si sigue sin haber match, usar difflib para el más parecido al configurado
                if not best_match and name and all_printers:
                    import difflib
                    matches = difflib.get_close_matches(name, all_printers, n=1, cutoff=0.4)
                    if matches:
                        best_match = matches[0]
                        _log(f"Coincidencia difusa (difflib): {best_match}")
                
                if not best_match and not name:
                    try:
                        best_match = win32print.GetDefaultPrinter()
                        _log(f"Usando impresora predeterminada de Windows: {best_match}")
                    except:
                        pass
                
                if best_match:
                    _log(f"Auto-detectada impresora: {best_match} (configurada era: {name})")
                    self.printer_name = best_match
                    self.connected = True
                    
                    if best_match != name:
                        self._save_auto_detected_name(best_match)
                    return True
                
                _log("ERROR: No se encontró ninguna impresora que coincida con los criterios.")
                self.connected = False
                return False

            from escpos import printer as ep
            if printer_type == "usb":
                # Lista de VIDs/PIDs comunes de impresoras POS
                common_vids = [
                    (0x04b8, 0x0202), # Epson
                    (0x0416, 0x5011), # ZJiang / Generic
                    (0x1fc9, 0x2016), # Generic
                    (0x0fe6, 0x811e), # ZJiang
                    (0x1ee1, 0x0001), # Xprinter
                    (0x0483, 0x5740), # Xprinter / ST
                    (0x0519, 0x0001), # Star
                    (0x1504, 0x0001), # Bixolon
                ]
                
                success = False
                # 1. Intentar con el default/hardcoded primero
                try:
                    self.printer = ep.Usb(0x04b8, 0x0202)
                    success = True
                except:
                    # 2. Intentar con otros comunes
                    for vid, pid in common_vids:
                        if vid == 0x04b8 and pid == 0x0202: continue # ya probado
                        try:
                            self.printer = ep.Usb(vid, pid)
                            success = True
                            _log(f"Auto-detectada impresora USB: VID={hex(vid)} PID={hex(pid)}")
                            break
                        except:
                            continue
                
                if not success:
                    # 3. Intentar buscar CUALQUIER impresora USB usando pyusb directamente si es posible
                    try:
                        import usb.core
                        import usb.util
                        # Buscar dispositivos de clase 7 (Printer)
                        dev = usb.core.find(custom_match=lambda d: any(i.bInterfaceClass == 7 for c in d for i in c))
                        if dev:
                            self.printer = ep.Usb(dev.idVendor, dev.idProduct)
                            success = True
                            _log(f"Auto-detectada impresora USB por clase: VID={hex(dev.idVendor)} PID={hex(dev.idProduct)}")
                    except:
                        pass
                
                if not success:
                    raise Exception("No se encontró ninguna impresora USB compatible")
                    
            elif printer_type == "serial":
                self.printer = ep.Serial(port or "COM1", baudrate=9600)
            elif printer_type == "network":
                host, p = (port or "192.168.1.100:9100").split(":")
                self.printer = ep.Network(host, int(p))
            self.connected = True
            return True
        except Exception as e:
            _log(f"Error conectando: {e}")
            self.connected = False
            return False

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

        try:
            _log(f"Imprimiendo via tipo={self.printer_type} nombre={self.printer_name}")
            if self.printer_type == "windows":
                result = self._print_windows(venta_data, farmacia_config)
                if not result:
                    # Reintento: forzar reconexión y volver a intentar
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
                # Reintento ESC/POS
                _log("Fallo ESC/POS, reintentando con reconexion...")
                self.connected = False
                self.connect(tipo, puerto or None)
                return self._print_escpos(venta_data, farmacia_config)

        except Exception:
            _log(f"EXCEPCION FINAL: {traceback.format_exc()}")
            return False

    # ── Construcción del ticket ───────────────────────────────────────────────

    def _build_ticket(self, venta_data: dict, farmacia_config: dict) -> str:
        cfg_d = farmacia_config or {}
        nombre    = _s(cfg_d.get("farmacia_nombre",    cfg.PHARMACY_NAME))
        direccion = _s(cfg_d.get("farmacia_direccion", cfg.PHARMACY_ADDRESS))
        telefono  = _s(cfg_d.get("farmacia_telefono",  cfg.PHARMACY_PHONE))
        rfc       = _s(cfg_d.get("farmacia_rfc",       cfg.PHARMACY_RFC))
        W = self.width

        sep  = "=" * W
        sep2 = "-" * W

        # Precio derecho: $1,234.56 → máx 9 chars
        PRICE_W = 9

        def ctr(txt):
            return _s(str(txt)).center(W)

        def money(amount):
            return f"${amount:,.2f}"

        def tot(label, value):
            val_str = money(value) if isinstance(value, float) else str(value)
            lbl_w = W - PRICE_W
            return f"{label:>{lbl_w}}{val_str:>{PRICE_W}}"

        # ── Encabezado ────────────────────────────────────────────────────────
        lines = [sep, ctr(nombre)]
        if direccion:
            lines.append(ctr(direccion))
        if telefono:
            lines.append(ctr(telefono))
        if rfc:
            lines.append(ctr(rfc))
        lines.append(sep)

        # Cajero centrado
        cajero = _s(venta_data.get("cajero", "N/A")).upper()
        lines.append(f"CAJERO: {cajero}".center(W))
        if venta_data.get("cliente"):
            lines.append(f"CLIENTE: {_s(venta_data['cliente']).upper()}".center(W))
        lines.append(sep)

        # ── Tabla de productos (estilo Guadalajara) ───────────────────────────
        # CANT  DESCRIPCION        PRECIO
        # Columnas: qty_prefix(6) + name(W-6-PRICE_W) + price(PRICE_W)
        NAME_W = W - 6 - PRICE_W
        lines.append(f"{'CANT':<6}{'DESCRIPCION':<{NAME_W}}{'PRECIO':>{PRICE_W}}")
        lines.append(sep2)

        num_articulos = 0
        for item in venta_data.get("items", []):
            cant      = item["cantidad"]
            sub       = item["subtotal"]
            pu        = sub / cant if cant else 0
            num_articulos += cant
            prod_full = _s(item["nombre"]).upper()

            qty_prefix = f"{cant:>2} PZ "          # "  1 PZ " — 6 chars
            price_str  = money(sub)

            # Nombre encaja en una línea
            if len(prod_full) <= NAME_W:
                lines.append(f"{qty_prefix}{prod_full:<{NAME_W}}{price_str:>{PRICE_W}}")
            else:
                # Primera línea: cantidad + inicio del nombre + precio
                lines.append(f"{qty_prefix}{prod_full[:NAME_W]:<{NAME_W}}{price_str:>{PRICE_W}}")
                # Líneas de continuación (sin precio)
                resto = prod_full[NAME_W:]
                while resto:
                    chunk = resto[:NAME_W]
                    resto  = resto[NAME_W:]
                    lines.append(f"{'':6}{chunk}")

        # ── Totales ───────────────────────────────────────────────────────────
        lines.append(sep)
        subtotal = venta_data.get("subtotal", 0.0)
        descuento = venta_data.get("descuento", 0.0)
        iva       = venta_data.get("iva", 0.0)
        total     = venta_data.get("total", 0.0)
        pagado    = venta_data.get("monto_pagado", 0.0)
        cambio    = venta_data.get("cambio", 0.0)
        metodo    = _s(venta_data.get("metodo_pago", "efectivo")).upper()

        if descuento > 0:
            lines.append(tot("SUBTOTAL", subtotal))
            lines.append(tot("DESCUENTO", descuento))
        if iva > 0:
            lines.append(tot("IVA (16%)", iva))

        lines.append(tot("TOTAL", total))
        lines.append(tot(metodo, pagado))
        lines.append(sep2)
        lines.append(tot("CAMBIO", cambio))
        lines.append(sep)
        lines.append(f"NUMERO DE ARTICULOS: {num_articulos}")
        lines.append(f"FOLIO: {venta_data.get('folio', 'N/A')}")
        lines.append(f"FECHA: {datetime.now().strftime('%d/%m/%Y  %H:%M')}")

        # ── Pie ───────────────────────────────────────────────────────────────
        lines += [
            sep,
            "!GRACIAS POR SU COMPRA!".center(W),
            "CONSERVE SU TICKET".center(W),
            sep,
            "", "", "",
        ]
        return "\n".join(lines)

    # ── Rutas de impresión ────────────────────────────────────────────────────

    def _print_windows(self, venta_data: dict, farmacia_config: dict) -> bool:
        try:
            import win32print
            import win32ui
            import win32con

            ticket = self._build_ticket(venta_data, farmacia_config)
            
            # Usar GDI para imprimir como texto estándar, más compatible que el modo RAW
            hDC = win32ui.CreateDC()
            hDC.CreatePrinterDC(self.printer_name)
            
            # Configuración de fuente básica para tickets (Courier para monoespaciado)
            font_size = 10
            if self.width > 40: # 80mm
                font_size = 10
            else: # 58mm
                font_size = 8

            hDC.StartDoc("Ticket Farmacia")
            hDC.StartPage()
            
            font = win32ui.CreateFont({
                "name": "Courier New",
                "height": -int(font_size * 1.5), # Ajuste de tamaño de fuente
                "weight": 400,
            })
            hDC.SelectObject(font)
            
            # Dibujar línea por línea
            y = 10
            for line in ticket.split("\n"):
                hDC.TextOut(10, y, line)
                y += int(font_size * 2) # Espaciado entre líneas
            
            hDC.EndPage()
            hDC.EndDoc()
            hDC.DeleteDC()
            
            return True
        except Exception:
            _log(f"EXCEPCION _print_windows: {traceback.format_exc()}")
            # Fallback al modo RAW si GDI falla
            return self._print_windows_raw(venta_data, farmacia_config)

    def _print_windows_raw(self, venta_data: dict, farmacia_config: dict) -> bool:
        try:
            import win32print
            ESC = b'\x1b'
            GS  = b'\x1d'

            ticket = self._build_ticket(venta_data, farmacia_config)
            raw = (
                ESC + b'@' +
                ticket.encode("ascii", errors="replace") +
                b'\n\n\n' +
                GS + b'V\x00'
            )

            hPrinter = win32print.OpenPrinter(self.printer_name)
            try:
                win32print.StartDocPrinter(hPrinter, 1, ("Ticket Farmacia", None, "RAW"))
                try:
                    win32print.StartPagePrinter(hPrinter)
                    win32print.WritePrinter(hPrinter, raw)
                    win32print.EndPagePrinter(hPrinter)
                finally:
                    win32print.EndDocPrinter(hPrinter)
            finally:
                win32print.ClosePrinter(hPrinter)
            return True
        except Exception:
            _log(f"EXCEPCION _print_windows_raw: {traceback.format_exc()}")
            return False

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
