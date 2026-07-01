"""Integración con Facturama (PAC autorizado SAT) para timbrar CFDI 4.0."""
import base64
import requests

SANDBOX_BASE = "https://apisandbox.facturama.mx"
PROD_BASE = "https://api.facturama.mx"

RFC_PUBLICO_GENERAL = "XAXX010101000"


class FacturamaError(Exception):
    pass


def _base_url(sandbox: bool) -> str:
    return SANDBOX_BASE if sandbox else PROD_BASE


def _auth_header(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _raise_for_facturama(r: requests.Response):
    if r.ok:
        return
    try:
        data = r.json()
        msg = data.get("ModelState") or data.get("Message") or data.get("message") or str(data)
    except Exception:
        msg = r.text
    raise FacturamaError(f"Facturama {r.status_code}: {msg}")


def crear_factura_global(
    *, user: str, password: str, sandbox: bool,
    mes: int, anio: int, subtotal: float, iva: float, total: float,
    emisor_rfc: str, emisor_razon_social: str, emisor_regimen_fiscal: str, emisor_cp: str,
) -> dict:
    """Timbra un CFDI 4.0 de factura global mensual (receptor Público en General).
    Regresa dict con: facturama_id, uuid, serie, folio, pdf_bytes, xml_bytes."""
    if not (user and password):
        raise FacturamaError("Credenciales de Facturama no configuradas")
    if not (emisor_rfc and emisor_regimen_fiscal and emisor_cp):
        raise FacturamaError("Datos fiscales del emisor incompletos (RFC/régimen/CP)")

    payload = {
        "CfdiType": "I",
        "NameId": "1",
        "ExpeditionPlace": emisor_cp,
        "Exportation": "01",  # Catálogo c_Exportacion — obligatorio en CFDI 4.0, "01" = No aplica
        "PaymentForm": "99",
        "PaymentMethod": "PUE",
        "Currency": "MXN",
        "GlobalInformation": {
            "Periodicity": "04",  # Mensual (catálogo SAT c_Periodicidad) — único válido para RESICO
            "Months": f"{mes:02d}",
            "Year": str(anio),
        },
        "Receiver": {
            "Rfc": RFC_PUBLICO_GENERAL,
            "Name": "PUBLICO EN GENERAL",
            "CfdiUse": "S01",
            "FiscalRegime": "616",
            "TaxZipCode": emisor_cp,
        },
        "Items": [
            {
                "ProductCode": "01010101",
                "IdentificationNumber": f"GLOBAL-{anio}{mes:02d}",
                "Description": f"Venta de mercancías periodo {mes:02d}/{anio} (factura global)",
                "Unit": "Unidad de servicio",
                "UnitCode": "ACT",
                "UnitPrice": round(subtotal, 2),
                "Quantity": 1,
                "Subtotal": round(subtotal, 2),
                "TaxObject": "02",  # Catálogo c_ObjetoImp — obligatorio en CFDI 4.0, "02" = Sí objeto de impuesto
                "Taxes": [
                    {"Total": round(iva, 2), "Name": "IVA", "Base": round(subtotal, 2), "Rate": 0.16, "IsRetention": False}
                ] if iva > 0 else [],
                "Total": round(total, 2),
            }
        ],
    }

    r = requests.post(
        f"{_base_url(sandbox)}/3/cfdis",
        headers=_auth_header(user, password),
        json=payload, timeout=30,
    )
    _raise_for_facturama(r)
    data = r.json()

    facturama_id = data.get("Id")
    complemento = data.get("Complement", {}) or {}
    stamp = complemento.get("TaxStamp", {}) or {}
    uuid_fiscal = stamp.get("Uuid", "")
    serie = data.get("Serie", "")
    folio = data.get("Folio", "")

    pdf_bytes = descargar_pdf(user, password, sandbox, facturama_id)
    xml_bytes = descargar_xml(user, password, sandbox, facturama_id)

    return {
        "facturama_id": facturama_id,
        "uuid": uuid_fiscal,
        "serie": serie,
        "folio": folio,
        "pdf_bytes": pdf_bytes,
        "xml_bytes": xml_bytes,
    }


def descargar_pdf(user: str, password: str, sandbox: bool, facturama_id: str) -> bytes:
    r = requests.get(
        f"{_base_url(sandbox)}/api/Cfdi/pdf/issued/{facturama_id}",
        headers=_auth_header(user, password), timeout=30,
    )
    _raise_for_facturama(r)
    data = r.json()
    return base64.b64decode(data.get("Content", ""))


def descargar_xml(user: str, password: str, sandbox: bool, facturama_id: str) -> bytes:
    r = requests.get(
        f"{_base_url(sandbox)}/api/Cfdi/xml/issued/{facturama_id}",
        headers=_auth_header(user, password), timeout=30,
    )
    _raise_for_facturama(r)
    data = r.json()
    return base64.b64decode(data.get("Content", ""))


def cancelar_cfdi(*, user: str, password: str, sandbox: bool, facturama_id: str, motivo: str = "02") -> None:
    """motivo: catálogo SAT c_MotivoCancelacion. '02' = CFDI con errores sin relación (default seguro).
    '01' (relacionada) requeriría uuidReplacement — no soportado aquí porque la factura global no tiene sustituta."""
    if not (user and password):
        raise FacturamaError("Credenciales de Facturama no configuradas")
    r = requests.delete(
        f"{_base_url(sandbox)}/cfdi/{facturama_id}",
        headers=_auth_header(user, password),
        params={"type": "issued", "motive": motivo},
        timeout=30,
    )
    _raise_for_facturama(r)
