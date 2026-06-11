import os
import sys
from pathlib import Path

# Mock config to point to the right data dir
os.environ["DATA_DIR"] = os.path.join(os.environ["APPDATA"], "FarmaciaEbenEzer")

from app.services.printer_service import printer_service
import app.config as cfg

print(f"Versión: {cfg.VERSION}")
print(f"Data Dir: {cfg.DATA_DIR}")

# Simular venta
venta = {
    "folio": "TEST-001",
    "cajero": "ADMIN",
    "items": [{"nombre": "PRODUCTO DE PRUEBA", "cantidad": 1, "subtotal": 10.0}],
    "total": 10.0,
    "monto_pagado": 10.0,
    "cambio": 0.0,
    "metodo_pago": "efectivo"
}

print("\nIntentando imprimir ticket de prueba...")
# Forzar carga de config de la DB
res = printer_service.print_receipt(venta)
print(f"Resultado print_receipt: {res}")

if not res:
    print("\nLogs recientes del printer.log:")
    log_path = Path(os.environ["DATA_DIR"]) / "printer.log"
    if log_path.exists():
        print(log_path.read_text()[-500:])
