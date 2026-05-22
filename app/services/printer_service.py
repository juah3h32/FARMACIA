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
        try:
            if printer_type == "windows":
                import win32print
                name = port or win32print.GetDefaultPrinter()
                self.printer_name = name
                self.connected = True
                return True

            from escpos import printer as ep
            if printer_type == "usb":
                self.printer = ep.Usb(0x04b8, 0x0202)
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
        try:
            import win32print
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            return [p[2] for p in win32print.EnumPrinters(flags)]
        except Exception:
            return []

    # ── Impresión ─────────────────────────────────────────────────────────────

    def print_receipt(self, venta_data: dict, farmacia_config: dict = None):
        if farmacia_config is None:
            farmacia_config = self._load_farmacia_config()

        w = farmacia_config.get("impresora_ancho", "32")
        self.width = int(w) if str(w).isdigit() else 32

        if not self.connected:
            tipo   = farmacia_config.get("impresora_tipo",   "windows")
            puerto = farmacia_config.get("impresora_nombre") or farmacia_config.get("impresora_puerto", "")
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
                _log(f"resultado: {result}")
                return result
            if not self.printer:
                _log("ESC/POS: printer es None")
                self._print_to_console(venta_data, farmacia_config)
                return False
            return self._print_escpos(venta_data, farmacia_config)
        except Exception:
            _log(f"EXCEPCION: {traceback.format_exc()}")
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
            ESC = b'\x1b'
            GS  = b'\x1d'

            ticket = self._build_ticket(venta_data, farmacia_config)
            # ASCII puro — no necesita codepage especial
            raw = (
                ESC + b'@' +
                ticket.encode("ascii", errors="replace") +
                b'\n\n\n' +
                GS + b'V\x00'
            )

            hPrinter = win32print.OpenPrinter(self.printer_name)
            try:
                hJob = win32print.StartDocPrinter(hPrinter, 1, ("Ticket Farmacia", None, "RAW"))
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
            _log(f"EXCEPCION _print_windows: {traceback.format_exc()}")
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

    def test_printer(self) -> bool:
        if not self.connected:
            return False
        try:
            if self.printer_type == "windows":
                import win32print
                ESC = b'\x1b'
                GS  = b'\x1d'
                raw = ESC + b'@' + b"Test de impresion OK\n\n\n" + GS + b'V\x00'
                hPrinter = win32print.OpenPrinter(self.printer_name)
                try:
                    hJob = win32print.StartDocPrinter(hPrinter, 1, ("Test", None, "RAW"))
                    try:
                        win32print.StartPagePrinter(hPrinter)
                        win32print.WritePrinter(hPrinter, raw)
                        win32print.EndPagePrinter(hPrinter)
                    finally:
                        win32print.EndDocPrinter(hPrinter)
                finally:
                    win32print.ClosePrinter(hPrinter)
                return True
            if self.printer:
                self.printer.text("Test de impresion OK\n")
                self.printer.cut()
                return True
        except Exception:
            _log(f"test_printer error: {traceback.format_exc()}")
        return False


printer_service = PrinterService()
