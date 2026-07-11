"""Integración con Factura.com (PAC autorizado SAT) para timbrar CFDI 4.0 global mensual."""
import base64
import requests

SANDBOX_BASE = "https://sandbox.factura.com/api"
PROD_BASE = "https://api.factura.com"
F_PLUGIN = "9d4095c8f7ed5785cb14c0e3b033eeb8252416ed"  # identificador público de integración, no es secreto de cuenta

RFC_PUBLICO_GENERAL = "XAXX010101000"


class FacturaComError(Exception):
    pass


def _base_url(sandbox: bool) -> str:
    return SANDBOX_BASE if sandbox else PROD_BASE


def _headers(api_key: str, secret_key: str) -> dict:
    return {
        "Content-Type": "application/json",
        "F-PLUGIN": F_PLUGIN,
        "F-Api-Key": api_key,
        "F-Secret-Key": secret_key,
    }


def _get(url: str, headers: dict, timeout: int):
    try:
        return requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise FacturaComError(f"Error de red al conectar con Factura.com: {e}") from e


def _post(url: str, headers: dict, json_body: dict, timeout: int):
    try:
        return requests.post(url, headers=headers, json=json_body, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise FacturaComError(f"Error de red al conectar con Factura.com: {e}") from e


def _post_timbrado(url: str, headers: dict, json_body: dict):
    """POST específico del timbrado (create). Si la conexión se cae ANTES de recibir
    respuesta, no hay forma de saber si Factura.com sí llegó a generar el CFDI del
    lado del SAT — el mensaje debe dejarlo explícito para que un humano verifique
    antes de reintentar (un reintento ciego puede generar un CFDI real duplicado)."""
    try:
        return requests.post(url, headers=headers, json=json_body, timeout=30)
    except requests.exceptions.RequestException as e:
        raise FacturaComError(
            "No se recibió respuesta de Factura.com al timbrar (posible corte de red). "
            "IMPORTANTE: el CFDI pudo haberse generado igual del lado de Factura.com/SAT. "
            "Antes de reintentar, revisa tu cuenta de Factura.com o usa 'Verificar con SAT' "
            f"para confirmar si ya existe. Detalle técnico: {e}"
        ) from e


def _raise_for_facturacom(r: requests.Response):
    try:
        data = r.json()
    except Exception:
        data = None
    # Factura.com no es consistente: unos endpoints regresan {"response":"error"},
    # otros {"status":"error"} — hay que checar ambos o un error real se cuela sin detectarse.
    es_error = data is not None and (data.get("response") == "error" or data.get("status") == "error")
    if r.ok and not es_error:
        return
    msg = data.get("message") if data else r.text
    raise FacturaComError(f"Factura.com {r.status_code}: {msg}")


def _serie_id_factura(api_key: str, secret_key: str, sandbox: bool) -> int:
    r = _get(f"{_base_url(sandbox)}/v1/series", headers=_headers(api_key, secret_key), timeout=20)
    _raise_for_facturacom(r)
    for s in r.json().get("data", []):
        if s.get("SerieType") == "F":
            return s["SerieID"]
    raise FacturaComError("No se encontró una serie de tipo Factura (F) configurada en la cuenta")


def _get_or_create_receptor_publico_general(api_key: str, secret_key: str, sandbox: bool, emisor_cp: str) -> str:
    base = _base_url(sandbox)
    headers = _headers(api_key, secret_key)

    r = _get(f"{base}/v1/clients/rfc/{RFC_PUBLICO_GENERAL}", headers=headers, timeout=20)
    if r.ok:
        data = r.json().get("Data") or []
        if data:
            return data[0]["UID"]

    r = _post(f"{base}/v1/clients/create", headers=headers, json_body={
        "rfc": RFC_PUBLICO_GENERAL,
        "razons": "PUBLICO EN GENERAL",
        "codpos": emisor_cp,
        "email": "",
        "regimen": "616",
        "pais": "MEX",
        "usocfdi": "S01",
    }, timeout=20)
    _raise_for_facturacom(r)
    return r.json()["Data"]["UID"]


def crear_factura_global(
    *, api_key: str, secret_key: str, sandbox: bool,
    mes: int, anio: int, subtotal: float, iva: float, total: float,
    emisor_cp: str,
) -> dict:
    """Timbra un CFDI 4.0 de factura global mensual (receptor Público en General).
    Regresa dict con: facturacom_id, uuid, serie, folio, pdf_bytes, xml_bytes."""
    if not (api_key and secret_key):
        raise FacturaComError("Credenciales de Factura.com no configuradas")

    client_uid = _get_or_create_receptor_publico_general(api_key, secret_key, sandbox, emisor_cp)
    serie_id = _serie_id_factura(api_key, secret_key, sandbox)

    # El mes puede mezclar ventas gravadas (16%, TAX_RATE) y exentas (0%, medicinas —
    # Art. 2-A LIVA). Un solo Concepto no puede llevar dos tasas distintas sobre su
    # propio importe, así que se separan en dos Conceptos: uno con la base gravada
    # (recuperada de iva/0.16, ya que así se calculó al vender) y otro con el resto
    # como base exenta a tasa 0% — ambos ObjetoImp=02 (sí objeto) con su Traslado,
    # nunca ObjetoImp=01 ni un Traslado faltante.
    base_gravada = round(iva / 0.16, 2) if iva > 0 else 0.0
    base_exenta = round(subtotal - base_gravada, 2)

    conceptos = []
    if base_gravada > 0:
        conceptos.append({
            "ClaveProdServ": "01010101", "Cantidad": 1, "ClaveUnidad": "ACT",
            "Unidad": "Unidad de servicio", "ValorUnitario": base_gravada,
            "Descripcion": f"Venta de mercancías gravadas periodo {mes:02d}/{anio} (factura global)",
            "ObjetoImp": "02",
            "Impuestos": {"Traslados": [{
                "Base": base_gravada, "Impuesto": "002", "TipoFactor": "Tasa",
                "TasaOCuota": "0.160000", "Importe": round(iva, 2),
            }]},
        })
    if base_exenta > 0 or not conceptos:
        conceptos.append({
            "ClaveProdServ": "01010101", "Cantidad": 1, "ClaveUnidad": "ACT",
            "Unidad": "Unidad de servicio", "ValorUnitario": base_exenta,
            "Descripcion": f"Venta de mercancías tasa 0% periodo {mes:02d}/{anio} (factura global)",
            "ObjetoImp": "02",
            "Impuestos": {"Traslados": [{
                "Base": base_exenta, "Impuesto": "002", "TipoFactor": "Tasa",
                "TasaOCuota": "0.000000", "Importe": 0.00,
            }]},
        })

    payload = {
        "Receptor": {"UID": client_uid},
        "TipoDocumento": "factura",
        "GlobalInformation": {"Periodicity": "04", "Months": f"{mes:02d}", "Year": str(anio)},
        "Conceptos": conceptos,
        "UsoCFDI": "S01",
        "Serie": serie_id,
        "FormaPago": "99",
        "MetodoPago": "PUE",
        "Moneda": "MXN",
        "EnviarCorreo": False,
    }

    r = _post_timbrado(f"{_base_url(sandbox)}/v4/cfdi40/create", headers=_headers(api_key, secret_key), json_body=payload)
    _raise_for_facturacom(r)
    data = r.json()

    facturacom_id = data.get("uid") or data.get("invoice_uid")
    uuid_fiscal = data.get("UUID", "")
    inv = data.get("INV", {}) or {}

    # El CFDI ya quedó timbrado y es fiscalmente válido en este punto — la descarga
    # de PDF/XML es un paso aparte e independiente (ver descargar_documentos) para
    # que un fallo de red aquí no se confunda con "no se timbró" y dispare un reintento
    # que generaría un SEGUNDO CFDI global real duplicado ante el SAT.
    return {
        "facturacom_id": facturacom_id,
        "uuid": uuid_fiscal,
        "serie": inv.get("Serie", ""),
        "folio": inv.get("Folio", ""),
    }


def _get_or_create_cliente(
    api_key: str, secret_key: str, sandbox: bool,
    rfc: str, nombre: str, cp: str, regimen_fiscal: str, uso_cfdi: str, email: str = "",
) -> str:
    base = _base_url(sandbox)
    headers = _headers(api_key, secret_key)
    rfc = rfc.strip().upper()

    r = _get(f"{base}/v1/clients/rfc/{rfc}", headers=headers, timeout=20)
    if r.ok:
        data = r.json().get("Data") or []
        if data:
            return data[0]["UID"]

    # Factura.com exige email no vacío para crear un cliente (a diferencia del
    # receptor genérico "Público en General"), aunque el campo sea opcional en el POS.
    email_final = email.strip() if email and email.strip() else f"sin-email-{rfc.lower()}@facturacion.local"

    r = _post(f"{base}/v1/clients/create", headers=headers, json_body={
        "rfc": rfc, "razons": nombre.strip().upper(), "codpos": cp,
        "email": email_final, "regimen": regimen_fiscal, "pais": "MEX", "usocfdi": uso_cfdi,
    }, timeout=20)
    _raise_for_facturacom(r)
    return r.json()["Data"]["UID"]


def crear_factura_individual(
    *, api_key: str, secret_key: str, sandbox: bool,
    cliente_rfc: str, cliente_nombre: str, cliente_regimen_fiscal: str, cliente_cp: str,
    cliente_email: str, uso_cfdi: str, forma_pago: str,
    items: list[dict],
) -> dict:
    """Timbra un CFDI 4.0 de ingreso para una venta específica, a nombre del cliente real
    (no Público en General). items: [{descripcion, cantidad, precio_unitario, aplica_iva}].
    Regresa dict con: facturacom_id, uuid, serie, folio."""
    if not (api_key and secret_key):
        raise FacturaComError("Credenciales de Factura.com no configuradas")
    if not items:
        raise FacturaComError("La venta no tiene artículos para facturar")

    client_uid = _get_or_create_cliente(
        api_key, secret_key, sandbox,
        rfc=cliente_rfc, nombre=cliente_nombre, cp=cliente_cp,
        regimen_fiscal=cliente_regimen_fiscal, uso_cfdi=uso_cfdi, email=cliente_email,
    )
    serie_id = _serie_id_factura(api_key, secret_key, sandbox)

    # Todo artículo de farmacia es "sí objeto de impuesto" (ObjetoImp=02) — los que no
    # llevan IVA (medicinas, Art. 2-A LIVA) son tasa 0%, no "no objeto" (01). Usar "01"
    # incorrectamente omite el Traslado obligatorio y clasifica mal casi toda la venta.
    conceptos = []
    for it in items:
        base_imp = round(it["cantidad"] * it["precio_unitario"], 2)
        aplica_iva = bool(it.get("aplica_iva"))
        concepto = {
            "ClaveProdServ": "01010101",
            "ClaveUnidad": "ACT",
            "Unidad": "Unidad de servicio",
            "Cantidad": it["cantidad"],
            "ValorUnitario": round(it["precio_unitario"], 2),
            "Descripcion": it["descripcion"],
            "ObjetoImp": "02",
            "Impuestos": {"Traslados": [{
                "Base": base_imp, "Impuesto": "002", "TipoFactor": "Tasa",
                "TasaOCuota": "0.160000" if aplica_iva else "0.000000",
                "Importe": round(base_imp * 0.16, 2) if aplica_iva else 0.00,
            }]},
        }
        conceptos.append(concepto)

    payload = {
        "Receptor": {"UID": client_uid},
        "TipoDocumento": "factura",
        "Conceptos": conceptos,
        "UsoCFDI": uso_cfdi,
        "Serie": serie_id,
        "FormaPago": forma_pago,
        "MetodoPago": "PUE",
        "Moneda": "MXN",
        "EnviarCorreo": False,
    }

    r = _post_timbrado(f"{_base_url(sandbox)}/v4/cfdi40/create", headers=_headers(api_key, secret_key), json_body=payload)
    _raise_for_facturacom(r)
    data = r.json()

    facturacom_id = data.get("uid") or data.get("invoice_uid")
    uuid_fiscal = data.get("UUID", "")
    inv = data.get("INV", {}) or {}

    return {
        "facturacom_id": facturacom_id,
        "uuid": uuid_fiscal,
        "serie": inv.get("Serie", ""),
        "folio": inv.get("Folio", ""),
    }


def descargar_documentos(*, api_key: str, secret_key: str, sandbox: bool, facturacom_id: str) -> dict:
    """Descarga PDF y XML de un CFDI ya timbrado. Puede reintentarse tantas veces
    como sea necesario sin riesgo — no vuelve a timbrar nada."""
    return {
        "pdf_bytes": _descargar(api_key, secret_key, sandbox, facturacom_id, "pdf"),
        "xml_bytes": _descargar(api_key, secret_key, sandbox, facturacom_id, "xml"),
    }


def _descargar(api_key: str, secret_key: str, sandbox: bool, facturacom_id: str, tipo: str) -> bytes:
    r = _get(f"{_base_url(sandbox)}/v4/cfdi40/{facturacom_id}/{tipo}", headers=_headers(api_key, secret_key), timeout=30)
    _raise_for_facturacom(r)
    ctype = r.headers.get("Content-Type", "")
    if "application/json" in ctype:
        data = r.json()
        contenido_b64 = data.get("content") or data.get("Content") or data.get("file") or ""
        return base64.b64decode(contenido_b64) if contenido_b64 else b""
    return r.content


def consultar_estatus_sat(*, api_key: str, secret_key: str, sandbox: bool, facturacom_id: str) -> dict:
    """Consulta el estatus real ante el SAT (no solo el registro local de Factura.com).
    Regresa dict con: estado ('Vigente'/'Cancelado'), es_cancelable, estatus_cancelacion, codigo_estatus.
    El SAT puede tardar en reflejar cancelaciones recientes — un CFDI recién cancelado
    puede seguir apareciendo como 'Vigente' por un rato (limitación documentada del SAT)."""
    if not (api_key and secret_key):
        raise FacturaComError("Credenciales de Factura.com no configuradas")
    r = _get(
        f"{_base_url(sandbox)}/v4/cfdi40/{facturacom_id}/cancel_status",
        headers=_headers(api_key, secret_key), timeout=30,
    )
    _raise_for_facturacom(r)
    data = r.json()
    return {
        "estado": data.get("Estado", ""),
        "es_cancelable": data.get("EsCancelable", ""),
        "estatus_cancelacion": data.get("EstatusCancelacion", ""),
        "codigo_estatus": data.get("CodigoEstatus", ""),
    }


def cancelar_cfdi(*, api_key: str, secret_key: str, sandbox: bool, facturacom_id: str, motivo: str = "02") -> None:
    """motivo: catálogo SAT c_MotivoCancelacion. '02' = CFDI con errores sin relación (default seguro)."""
    if not (api_key and secret_key):
        raise FacturaComError("Credenciales de Factura.com no configuradas")
    r = _post(
        f"{_base_url(sandbox)}/v4/cfdi40/{facturacom_id}/cancel",
        headers=_headers(api_key, secret_key),
        json_body={"motivo": motivo},
        timeout=30,
    )
    _raise_for_facturacom(r)
