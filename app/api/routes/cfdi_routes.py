import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, RedirectResponse
from pydantic import BaseModel
from datetime import datetime, date
from pathlib import Path

from app.database.connection import get_db_session
from app.database.models import Venta, EstadoVenta, CfdiFacturaGlobal, CfdiFacturaIndividual, Configuracion, FacturaCompra, ItemVenta
from app.api.routes.auth_routes import get_current_api_user
from app.services import facturacom_service
from app.database import sync_service
import app.config as cfg

router = APIRouter()

# Serializa timbrado (global e individual) dentro de este proceso: sin este lock,
# dos requests casi simultáneas (doble clic, dos pestañas) pueden pasar ambas el
# check "ya existe/ya facturada" antes de que la primera haga commit, y terminar
# timbrando el mismo periodo o la misma venta dos veces ante el SAT (CFDI duplicado
# real, no solo un registro local duplicado). El sync con Turso ya reduce la ventana
# entre PCs distintas; este lock cierra la ventana dentro de la misma PC/proceso.
_timbrado_lock = threading.Lock()


def _purgar_de_turso(tabla: str, ids: list[int]) -> None:
    """Best-effort: borra en Turso los ids ya eliminados localmente.
    No bloquea la respuesta si falla (Turso puede estar offline) — la
    fuente de verdad es la BD local; el intento de borrado remoto es
    para que un pull posterior no resucite el registro eliminado."""
    if not (cfg.TURSO_SYNC and ids):
        return
    try:
        sync_service.delete_ids_from_turso(tabla, ids)
    except Exception as e:
        print(f"[CFDI] No se pudo borrar {tabla} {ids} en Turso: {e}")

_FACT_KEYS = [
    "facturacom_api_key", "facturacom_secret_key", "facturacom_sandbox",
    "emisor_razon_social", "emisor_rfc", "emisor_regimen_fiscal", "emisor_cp",
    "email_smtp_host", "email_smtp_port", "email_smtp_user", "email_smtp_password",
]

MESES_ES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _require_admin(payload):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


def _rango(mes: int, anio: int):
    fi = datetime(anio, mes, 1)
    ff = datetime(anio + 1, 1, 1) if mes == 12 else datetime(anio, mes + 1, 1)
    return fi, ff


# Tabla ISR RESICO personas físicas (Art. 113-E LISR) — tasa sobre ingreso ACUMULADO
# desde enero (no marginal: se aplica una sola tasa a todo el acumulado según el rango).
_ISR_BRACKETS = [
    (25_000.00, 0.010),
    (50_000.00, 0.011),
    (83_333.33, 0.015),
    (208_333.33, 0.020),
    (291_666.67, 0.025),
]


def _tasa_isr(acumulado: float) -> float:
    for limite, tasa in _ISR_BRACKETS:
        if acumulado <= limite:
            return tasa
    return _ISR_BRACKETS[-1][1]  # arriba del tope RESICO — igual se usa la tasa máxima como referencia


def _leer_config_facturacion(db) -> dict:
    rows = db.query(Configuracion).filter(Configuracion.clave.in_(_FACT_KEYS)).all()
    d = {r.clave: r.valor for r in rows}
    return {
        "facturacom_api_key":    d.get("facturacom_api_key", ""),
        "facturacom_secret_key": d.get("facturacom_secret_key", ""),
        "facturacom_sandbox":    d.get("facturacom_sandbox", "1") == "1",
        "emisor_razon_social":  d.get("emisor_razon_social") or cfg.PHARMACY_RAZON_SOCIAL_FISCAL,
        "emisor_rfc":           d.get("emisor_rfc") or cfg.PHARMACY_RFC,
        "emisor_regimen_fiscal": d.get("emisor_regimen_fiscal") or cfg.PHARMACY_REGIMEN_FISCAL,
        "emisor_cp":            d.get("emisor_cp") or cfg.PHARMACY_CP_FISCAL,
        "email_smtp_host":      d.get("email_smtp_host", ""),
        "email_smtp_port":      d.get("email_smtp_port", "587"),
        "email_smtp_user":      d.get("email_smtp_user", ""),
        "email_smtp_password":  d.get("email_smtp_password", ""),
    }


def _cfdi_dir() -> Path:
    d = cfg.DATA_DIR / "cfdi"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extraer_fe(xml_path: str | None) -> str | None:
    """Últimos 8 caracteres del sello digital (parámetro 'fe' del validador SAT)
    — sin esto el validador puede dar match ambiguo en vez de encontrar el CFDI exacto."""
    if not xml_path:
        return None
    try:
        import re
        from urllib.parse import quote
        contenido = Path(xml_path).read_text(encoding="utf-8", errors="ignore")
        m = re.search(r'Sello="([^"]+)"', contenido)
        if not m:
            return None
        return quote(m.group(1)[-8:], safe="")
    except Exception:
        return None


def _cfdi_periodo_dir(mes: int, anio: int) -> Path:
    """Carpeta por periodo, ej. 'cfdi/Junio 2026/' — para que todas las facturas
    queden ordenadas por mes y sean fáciles de navegar en el explorador."""
    d = _cfdi_dir() / f"{MESES_ES[mes-1]} {anio}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _descargar_y_guardar_documentos(db, registro: "CfdiFacturaGlobal", fconf: dict) -> bool:
    """Descarga PDF/XML de un CFDI ya timbrado y los guarda. Nunca vuelve a timbrar
    nada — puede reintentarse tantas veces como haga falta si falla la descarga."""
    try:
        docs = facturacom_service.descargar_documentos(
            api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
            sandbox=fconf["facturacom_sandbox"], facturacom_id=registro.facturama_id,
        )
    except facturacom_service.FacturaComError:
        return False

    # El id del registro va en el nombre de archivo — un periodo puede timbrarse más
    # de una vez a lo largo del tiempo (se cancela y se vuelve a timbrar); sin el id,
    # el segundo timbrado sobreescribe silenciosamente el PDF/XML de la factura
    # cancelada anterior, perdiendo la evidencia de lo que realmente se canceló.
    cfdi_dir = _cfdi_periodo_dir(registro.mes, registro.anio)
    pdf_path = cfdi_dir / f"{registro.anio}-{registro.mes:02d}_id{registro.id}.pdf"
    xml_path = cfdi_dir / f"{registro.anio}-{registro.mes:02d}_id{registro.id}.xml"
    pdf_path.write_bytes(docs["pdf_bytes"])
    xml_path.write_bytes(docs["xml_bytes"])

    pdf_url = xml_url = None
    try:
        from app.services.cloudinary_service import upload_documento
        public_id = f"{registro.anio}-{registro.mes:02d}_id{registro.id}"
        pdf_url = upload_documento(str(pdf_path), "FARMACIA/CFDI_GLOBAL", f"{public_id}.pdf")
        xml_url = upload_documento(str(xml_path), "FARMACIA/CFDI_GLOBAL", f"{public_id}.xml")
    except Exception:
        pass

    registro.pdf_path = str(pdf_path)
    registro.xml_path = str(xml_path)
    registro.pdf_url = pdf_url
    registro.xml_url = xml_url
    db.commit()
    return True


def _agregar_ventas_pendientes(db, mes: int, anio: int):
    fi, ff = _rango(mes, anio)
    ventas = (
        db.query(Venta)
        .filter(
            Venta.creado_en >= fi, Venta.creado_en < ff,
            Venta.estado == EstadoVenta.completada,
            Venta.eliminado.is_not(True),
            Venta.facturada.is_not(True),
        )
        .all()
    )
    subtotal = sum(v.subtotal or 0.0 for v in ventas)
    iva = sum(v.iva or 0.0 for v in ventas)
    total = sum(v.total or 0.0 for v in ventas)
    return ventas, subtotal, iva, total


@router.get("/declaracion-mensual")
def declaracion_mensual(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020, le=2100),
    payload: dict = Depends(get_current_api_user),
):
    """Junta ingresos (ventas), compras (facturas de proveedor), IVA neto e ISR
    estimado del mes — para tener en un solo lugar lo que se declara ante el SAT."""
    _require_admin(payload)
    db = get_db_session()
    try:
        fi, ff = _rango(mes, anio)

        # Ingresos del mes: TODAS las ventas completadas (facturadas o no) — el ISR/IVA
        # se causan al cobrar, no al timbrar el CFDI global.
        ventas_mes = (
            db.query(Venta)
            .filter(Venta.creado_en >= fi, Venta.creado_en < ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .all()
        )
        ing_subtotal = sum(v.subtotal or 0.0 for v in ventas_mes)
        ing_iva = sum(v.iva or 0.0 for v in ventas_mes)
        ing_total = sum(v.total or 0.0 for v in ventas_mes)

        # Compras del mes (facturas de proveedor registradas)
        compras_mes = (
            db.query(FacturaCompra)
            .filter(FacturaCompra.fecha_factura >= fi.date(), FacturaCompra.fecha_factura < ff.date())
            .all()
        )
        com_subtotal = sum(c.subtotal or 0.0 for c in compras_mes)
        com_iva = sum(c.iva or 0.0 for c in compras_mes)
        com_total = sum(c.total or 0.0 for c in compras_mes)

        # Ingreso ACUMULADO desde el 1-enero del año hasta fin del mes seleccionado —
        # la tasa ISR de RESICO se determina por el acumulado, no por el mes aislado.
        fi_anio = datetime(anio, 1, 1)
        ventas_acumuladas = (
            db.query(Venta)
            .filter(Venta.creado_en >= fi_anio, Venta.creado_en < ff,
                    Venta.estado == EstadoVenta.completada,
                    Venta.eliminado.is_not(True))
            .all()
        )
        ingreso_acumulado = sum(v.subtotal or 0.0 for v in ventas_acumuladas)
        tasa = _tasa_isr(ingreso_acumulado)
        isr_acumulado_anio = round(ingreso_acumulado * tasa, 2)

        return {
            "mes": mes, "anio": anio,
            "ingresos": {
                "num_ventas": len(ventas_mes),
                "subtotal": round(ing_subtotal, 2),
                "iva": round(ing_iva, 2),
                "total": round(ing_total, 2),
            },
            "compras": {
                "num_facturas": len(compras_mes),
                "subtotal": round(com_subtotal, 2),
                "iva": round(com_iva, 2),
                "total": round(com_total, 2),
            },
            "iva_a_pagar": round(ing_iva - com_iva, 2),
            "isr": {
                "ingreso_acumulado_anio": round(ingreso_acumulado, 2),
                "tasa_aplicable": tasa,
                "isr_acumulado_estimado": isr_acumulado_anio,
                "nota": "Este acumulado es SOLO de lo registrado en este sistema. El ISR real "
                        "de este mes = ISR acumulado − lo ya pagado en meses previos del año, "
                        "dato que este sistema no tiene. Verifica el importe exacto en tu Buzón "
                        "Tributario o con tu contador antes de declarar.",
            },
        }
    finally:
        db.close()


@router.get("/preview")
def preview_factura_global(
    mes: int = Query(..., ge=1, le=12),
    anio: int = Query(..., ge=2020, le=2100),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        ya_existe = (
            db.query(CfdiFacturaGlobal)
            .filter(CfdiFacturaGlobal.mes == mes, CfdiFacturaGlobal.anio == anio,
                    CfdiFacturaGlobal.estado == "timbrada")
            .first()
        )
        ventas, subtotal, iva, total = _agregar_ventas_pendientes(db, mes, anio)
        fconf = _leer_config_facturacion(db)

        # Regla 2.7.1.21 RMF: la factura global debe timbrarse dentro de las 24h
        # siguientes al cierre del periodo. Esto NO bloquea el timbrado (a veces
        # hay que presentarla tarde igual), solo informa si ya se pasó la ventana.
        _, fin_periodo = _rango(mes, anio)
        horas_desde_cierre = (datetime.now() - fin_periodo).total_seconds() / 3600
        fuera_ventana_24h = horas_desde_cierre > 24

        faltantes = [
            campo for campo, label in [
                ("facturacom_api_key", "API key Factura.com"), ("facturacom_secret_key", "Secret key Factura.com"),
                ("emisor_rfc", "RFC emisor"), ("emisor_regimen_fiscal", "régimen fiscal emisor"),
                ("emisor_cp", "código postal emisor"),
            ] if not fconf.get(campo)
        ]
        return {
            "mes": mes, "anio": anio,
            "num_ventas": len(ventas),
            "subtotal": round(subtotal, 2),
            "iva": round(iva, 2),
            "total": round(total, 2),
            "ya_facturado": bool(ya_existe),
            "emisor": {
                "razon_social": fconf["emisor_razon_social"],
                "rfc": fconf["emisor_rfc"],
                "regimen_fiscal": fconf["emisor_regimen_fiscal"],
                "cp": fconf["emisor_cp"],
            },
            "receptor": {
                "rfc": facturacom_service.RFC_PUBLICO_GENERAL,
                "nombre": "PUBLICO EN GENERAL",
                "uso_cfdi": "S01",
                "regimen_fiscal": "616",
            },
            "concepto": {
                "clave_prod_serv": "01010101",
                "descripcion": f"Venta de mercancías periodo {mes:02d}/{anio} (factura global)",
                "clave_unidad": "ACT",
            },
            "sandbox": fconf["facturacom_sandbox"],
            "fuera_ventana_24h": fuera_ventana_24h,
            "datos_incompletos": faltantes,
        }
    finally:
        db.close()


class TimbrarIn(BaseModel):
    mes: int
    anio: int


@router.post("/timbrar-global")
def timbrar_factura_global(body: TimbrarIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    # Igual que en individual: sincroniza con Turso antes de checar si el periodo ya
    # está timbrado, para achicar la ventana de doble-timbrado entre dos PCs.
    if cfg.TURSO_SYNC:
        try:
            sync_service.sync_from_turso()
        except Exception as e:
            print(f"[CFDI] Pre-timbrado: no se pudo sincronizar con Turso: {e}")
    _timbrado_lock.acquire()
    db = get_db_session()
    try:
        existe = (
            db.query(CfdiFacturaGlobal)
            .filter(CfdiFacturaGlobal.mes == body.mes, CfdiFacturaGlobal.anio == body.anio,
                    CfdiFacturaGlobal.estado == "timbrada")
            .first()
        )
        if existe:
            raise HTTPException(status_code=400, detail="Ya existe una factura global timbrada para este periodo")

        ventas, subtotal, iva, total = _agregar_ventas_pendientes(db, body.mes, body.anio)
        if not ventas:
            raise HTTPException(status_code=400, detail="No hay ventas pendientes de facturar en este periodo")

        fconf = _leer_config_facturacion(db)

        try:
            resultado = facturacom_service.crear_factura_global(
                api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
                sandbox=fconf["facturacom_sandbox"],
                mes=body.mes, anio=body.anio,
                subtotal=subtotal, iva=iva, total=total,
                emisor_cp=fconf["emisor_cp"],
            )
        except facturacom_service.FacturaComError as e:
            registro = CfdiFacturaGlobal(
                mes=body.mes, anio=body.anio, subtotal=subtotal, iva=iva, total=total,
                num_ventas=len(ventas), estado="error", error_mensaje=str(e),
                sandbox=fconf["facturacom_sandbox"],
                usuario_id=int(payload["sub"]) if payload.get("sub") else None,
            )
            db.add(registro)
            db.commit()
            raise HTTPException(status_code=502, detail=str(e))

        # El CFDI ya quedó timbrado y es fiscalmente válido — se graba YA como
        # "timbrada" antes de intentar descargar PDF/XML. Si la descarga falla más
        # abajo, NO debe quedar como "error" (eso llevaría a un reintento que
        # generaría un segundo CFDI global real duplicado ante el SAT).
        registro = CfdiFacturaGlobal(
            mes=body.mes, anio=body.anio, subtotal=subtotal, iva=iva, total=total,
            num_ventas=len(ventas), estado="timbrada",
            facturama_id=resultado["facturacom_id"], uuid_fiscal=resultado["uuid"],
            serie=resultado["serie"], folio=resultado["folio"],
            sandbox=fconf["facturacom_sandbox"],
            usuario_id=int(payload["sub"]) if payload.get("sub") else None,
        )
        db.add(registro)
        db.flush()
        for v in ventas:
            v.facturada = True
            v.cfdi_global_id = registro.id
        db.commit()

        _descargar_y_guardar_documentos(db, registro, fconf)

        return {
            "ok": True, "id": registro.id, "uuid": registro.uuid_fiscal,
            "total": registro.total, "num_ventas": registro.num_ventas,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
        _timbrado_lock.release()


@router.get("/historial")
def historial_facturas(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        rows = (
            db.query(CfdiFacturaGlobal)
            .order_by(CfdiFacturaGlobal.anio.desc(), CfdiFacturaGlobal.mes.desc())
            .all()
        )
        return [
            {
                "id": r.id, "mes": r.mes, "anio": r.anio,
                "subtotal": r.subtotal, "iva": r.iva, "total": r.total,
                "num_ventas": r.num_ventas, "estado": r.estado, "sandbox": bool(r.sandbox),
                "uuid": r.uuid_fiscal, "serie": r.serie, "folio": r.folio,
                "error_mensaje": r.error_mensaje,
                "documentos_pendientes": r.estado == "timbrada" and not r.pdf_path and not r.pdf_url,
                "carpeta_periodo": f"Facturas / {MESES_ES[r.mes-1]} {r.anio}" if r.pdf_path else None,
                "creado_en": r.creado_en.isoformat() if r.creado_en else None,
                "cancelado_en": r.cancelado_en.isoformat() if r.cancelado_en else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.post("/abrir-carpeta-todas")
def abrir_carpeta_todas(payload: dict = Depends(get_current_api_user)):
    """Abre la carpeta raíz donde quedan todas las facturas globales, organizadas
    en subcarpetas por periodo (ej. 'Junio 2026')."""
    _require_admin(payload)
    d = _cfdi_dir()
    import subprocess
    subprocess.Popen(["explorer", str(d)])
    return {"ok": True, "path": str(d)}


@router.post("/{cfdi_id}/abrir-carpeta")
def abrir_carpeta_cfdi(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r or not r.pdf_path:
            raise HTTPException(status_code=404, detail="No hay archivo guardado localmente para esta factura")
        p = Path(r.pdf_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="El archivo ya no existe en disco")
        import subprocess
        subprocess.Popen(["explorer", "/select,", str(p)])
        return {"ok": True, "path": str(p)}
    except HTTPException:
        raise
    finally:
        db.close()


@router.post("/{cfdi_id}/redescargar")
def redescargar_documentos(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "timbrada":
            raise HTTPException(status_code=400, detail="Solo aplica a facturas ya timbradas")
        fconf = _leer_config_facturacion(db)
        ok = _descargar_y_guardar_documentos(db, r, fconf)
        if not ok:
            raise HTTPException(status_code=502, detail="No se pudo descargar el PDF/XML todavía, intenta de nuevo más tarde")
        return {"ok": True}
    except HTTPException:
        raise
    finally:
        db.close()


@router.get("/{cfdi_id}/estatus-sat")
def estatus_sat(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    """Consulta el estatus REAL ante el SAT (vía Factura.com) y lo compara contra
    lo que dice la base local — detecta si alguien canceló el CFDI directo en el
    dashboard de Factura.com sin pasar por el botón "Cancelar" del POS."""
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado not in ("timbrada", "cancelada"):
            raise HTTPException(status_code=400, detail="Solo aplica a facturas timbradas o canceladas")

        fconf = _leer_config_facturacion(db)

        # El link al validador público del SAT no depende de que la consulta de estatus
        # de Factura.com funcione — el webservice del SAT es conocido por fallar
        # intermitentemente, pero eso no debe tumbar el link de verificación en sí.
        fe = _extraer_fe(r.xml_path)
        url_verificacion_sat = (
            "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx"
            f"?id={r.uuid_fiscal}&re={fconf['emisor_rfc']}&rr={facturacom_service.RFC_PUBLICO_GENERAL}"
            f"&tt={r.total:.6f}"
            + (f"&fe={fe}" if fe else "")
        )

        try:
            sat = facturacom_service.consultar_estatus_sat(
                api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
                sandbox=fconf["facturacom_sandbox"], facturacom_id=r.facturama_id,
            )
        except facturacom_service.FacturaComError as e:
            return {
                "estado_local": r.estado, "estado_sat": None, "coincide": None,
                "detalle_sat": None, "url_verificacion_sat": url_verificacion_sat,
                "error_consulta": str(e),
            }

        estado_sat = sat["estado"]  # "Vigente" o "Cancelado"
        estado_esperado = "Cancelado" if r.estado == "cancelada" else "Vigente"
        coincide = estado_sat == estado_esperado

        return {
            "estado_local": r.estado,
            "estado_sat": estado_sat,
            "coincide": coincide,
            "detalle_sat": sat,
            "url_verificacion_sat": url_verificacion_sat,
            "error_consulta": None,
        }
    except HTTPException:
        raise
    finally:
        db.close()


@router.delete("/{cfdi_id}")
def eliminar_factura_error(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "error":
            raise HTTPException(status_code=400, detail="Solo se pueden eliminar intentos con error, no facturas timbradas")
        db.delete(r)
        db.commit()
        _purgar_de_turso("cfdi_facturas_globales", [cfdi_id])
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class EliminarLoteIn(BaseModel):
    ids: list[int]


@router.post("/eliminar-lote")
def eliminar_facturas_error_lote(body: EliminarLoteIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if not body.ids:
        raise HTTPException(status_code=400, detail="Sin ids para eliminar")
    db = get_db_session()
    try:
        rows = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id.in_(body.ids)).all()
        borrables = [r for r in rows if r.estado == "error"]
        omitidos = len(body.ids) - len(borrables)
        ids_borrados = [r.id for r in borrables]
        for r in borrables:
            db.delete(r)
        db.commit()
        _purgar_de_turso("cfdi_facturas_globales", ids_borrados)
        return {"eliminados": len(ids_borrados), "omitidos": omitidos}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{cfdi_id}/pdf")
def descargar_pdf(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r or (not r.pdf_path and not r.pdf_url):
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.pdf_path) if r.pdf_path else None
        if p and p.exists():
            return Response(content=p.read_bytes(), media_type="application/pdf", headers={
                "Content-Disposition": f'attachment; filename="factura_global_{r.anio}-{r.mes:02d}.pdf"'
            })
        if r.pdf_url:
            return RedirectResponse(r.pdf_url)
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado en disco ni en la nube")
    finally:
        db.close()


@router.get("/{cfdi_id}/xml")
def descargar_xml(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r or (not r.xml_path and not r.xml_url):
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.xml_path) if r.xml_path else None
        if p and p.exists():
            return Response(content=p.read_bytes(), media_type="application/xml", headers={
                "Content-Disposition": f'attachment; filename="factura_global_{r.anio}-{r.mes:02d}.xml"'
            })
        if r.xml_url:
            return RedirectResponse(r.xml_url)
        raise HTTPException(status_code=404, detail="Archivo XML no encontrado en disco ni en la nube")
    finally:
        db.close()


class CancelarIn(BaseModel):
    motivo: str = "02"


@router.post("/{cfdi_id}/cancelar")
def cancelar_factura(cfdi_id: int, body: CancelarIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "timbrada":
            raise HTTPException(status_code=400, detail="Solo se puede cancelar una factura timbrada")

        fconf = _leer_config_facturacion(db)
        try:
            facturacom_service.cancelar_cfdi(
                api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
                sandbox=fconf["facturacom_sandbox"],
                facturacom_id=r.facturama_id, motivo=body.motivo,
            )
        except facturacom_service.FacturaComError as e:
            raise HTTPException(status_code=502, detail=str(e))

        r.estado = "cancelada"
        r.cancelado_en = datetime.now()
        ventas = db.query(Venta).filter(Venta.cfdi_global_id == r.id).all()
        for v in ventas:
            v.facturada = False
            v.cfdi_global_id = None
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
# FACTURA INDIVIDUAL POR VENTA (CFDI 4.0 de ingreso, a nombre del cliente real)
# ══════════════════════════════════════════════════════════════════════════

def _cfdi_individual_dir(mes: int, anio: int) -> Path:
    d = _cfdi_dir() / "Facturas Individuales" / f"{MESES_ES[mes-1]} {anio}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _descargar_y_guardar_documentos_individual(db, registro: "CfdiFacturaIndividual", fconf: dict) -> bool:
    """Igual que _descargar_y_guardar_documentos pero para factura individual —
    nunca vuelve a timbrar, solo descarga PDF/XML de un CFDI ya emitido."""
    try:
        docs = facturacom_service.descargar_documentos(
            api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
            sandbox=fconf["facturacom_sandbox"], facturacom_id=registro.facturacom_id,
        )
    except facturacom_service.FacturaComError:
        return False

    creado = registro.creado_en or datetime.now()
    cfdi_dir = _cfdi_individual_dir(creado.month, creado.year)
    nombre_base = f"venta-{registro.venta_id}-{registro.folio or registro.id}"
    pdf_path = cfdi_dir / f"{nombre_base}.pdf"
    xml_path = cfdi_dir / f"{nombre_base}.xml"
    pdf_path.write_bytes(docs["pdf_bytes"])
    xml_path.write_bytes(docs["xml_bytes"])

    pdf_url = xml_url = None
    try:
        from app.services.cloudinary_service import upload_documento
        pdf_url = upload_documento(str(pdf_path), "FARMACIA/CFDI_INDIVIDUAL", f"{nombre_base}.pdf")
        xml_url = upload_documento(str(xml_path), "FARMACIA/CFDI_INDIVIDUAL", f"{nombre_base}.xml")
    except Exception:
        pass

    registro.pdf_path = str(pdf_path)
    registro.xml_path = str(xml_path)
    registro.pdf_url = pdf_url
    registro.xml_url = xml_url
    db.commit()
    return True


class TimbrarIndividualIn(BaseModel):
    venta_id: int
    cliente_rfc: str
    cliente_nombre: str
    cliente_regimen_fiscal: str
    cliente_cp: str
    cliente_email: str = ""
    uso_cfdi: str = "G03"
    forma_pago: str = "01"


@router.post("/individual/timbrar")
def timbrar_factura_individual(body: TimbrarIndividualIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    # Trae el estado más reciente de Turso antes de decidir si ya está facturada —
    # reduce (no elimina del todo) la ventana en la que dos PCs timbran la misma
    # venta casi al mismo tiempo antes de que el sync periódico (cada 30s) alcance
    # a avisarle a esta PC que la otra ya la facturó.
    if cfg.TURSO_SYNC:
        try:
            sync_service.sync_from_turso()
        except Exception as e:
            print(f"[CFDI] Pre-timbrado: no se pudo sincronizar con Turso: {e}")
    _timbrado_lock.acquire()
    db = get_db_session()
    try:
        venta = db.query(Venta).filter(Venta.id == body.venta_id).first()
        if not venta:
            raise HTTPException(status_code=404, detail="Venta no encontrada")

        if venta.eliminado:
            raise HTTPException(status_code=400, detail="Esta venta fue eliminada — no se puede facturar")
        if venta.estado != EstadoVenta.completada:
            raise HTTPException(status_code=400, detail=f"Esta venta está en estado '{venta.estado.value}' (no completada) — no se puede facturar")
        if venta.facturada:
            raise HTTPException(status_code=400, detail="Esta venta ya fue facturada (individual o dentro de la factura global del mes) — no se puede facturar dos veces")
        # venta.descuento es un descuento GLOBAL sobre el ticket (no por artículo); los
        # Conceptos del CFDI individual se arman a partir de item.subtotal (precio*cantidad
        # por artículo, sin este descuento) — timbrar así facturaría de más frente al SAT
        # (el CFDI no coincidiría con lo realmente cobrado al cliente). La factura GLOBAL
        # mensual sí es correcta porque suma venta.subtotal/iva/total ya con el descuento
        # aplicado, así que esta venta queda cubierta ahí sin necesidad de más cambios.
        if venta.descuento:
            raise HTTPException(
                status_code=400,
                detail="Esta venta tiene un descuento global aplicado al ticket — no se puede facturar "
                       "individual (el CFDI no podría reflejar el descuento y facturaría de más). "
                       "Quedará cubierta por la factura global mensual del periodo.",
            )

        # Regla comercial estándar en México: si no se facturó al momento de la compra,
        # se puede facturar individual a más tardar el último día del mes de la compra.
        # Después de esa fecha ya debe quedar cubierta por la factura global mensual —
        # facturarla aparte duplicaría el ingreso declarado ante el SAT.
        venta_fecha = venta.creado_en or datetime.now()
        _, fin_mes_venta = _rango(venta_fecha.month, venta_fecha.year)
        if datetime.now() > fin_mes_venta:
            raise HTTPException(
                status_code=400,
                detail=f"Esta venta es de {MESES_ES[venta_fecha.month-1]} {venta_fecha.year} — ya pasó el plazo para "
                       "facturarla individual (hasta el último día de ese mes). Ya debe estar cubierta por la factura global mensual.",
            )

        ya_existe = (
            db.query(CfdiFacturaIndividual)
            .filter(CfdiFacturaIndividual.venta_id == body.venta_id, CfdiFacturaIndividual.estado == "timbrada")
            .first()
        )
        if ya_existe:
            raise HTTPException(status_code=400, detail="Esta venta ya tiene una factura individual timbrada")

        items_venta = db.query(ItemVenta).filter(ItemVenta.venta_id == body.venta_id).all()
        if not items_venta:
            raise HTTPException(status_code=400, detail="La venta no tiene artículos")

        items = [{
            "descripcion": i.producto.nombre if i.producto else f"Producto {i.producto_id}",
            "cantidad": i.cantidad,
            "precio_unitario": i.precio_unitario,
            "aplica_iva": bool(i.producto.aplica_iva) if i.producto else False,
        } for i in items_venta]

        subtotal = sum(i.subtotal or 0.0 for i in items_venta)
        iva = sum((i.subtotal or 0.0) * 0.16 for i in items_venta if i.producto and i.producto.aplica_iva)
        total = subtotal + iva

        fconf = _leer_config_facturacion(db)
        try:
            resultado = facturacom_service.crear_factura_individual(
                api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
                sandbox=fconf["facturacom_sandbox"],
                cliente_rfc=body.cliente_rfc, cliente_nombre=body.cliente_nombre,
                cliente_regimen_fiscal=body.cliente_regimen_fiscal, cliente_cp=body.cliente_cp,
                cliente_email=body.cliente_email, uso_cfdi=body.uso_cfdi, forma_pago=body.forma_pago,
                items=items,
            )
        except facturacom_service.FacturaComError as e:
            registro = CfdiFacturaIndividual(
                venta_id=body.venta_id, cliente_nombre=body.cliente_nombre, cliente_rfc=body.cliente_rfc,
                cliente_regimen_fiscal=body.cliente_regimen_fiscal, cliente_cp=body.cliente_cp,
                cliente_email=body.cliente_email, uso_cfdi=body.uso_cfdi, forma_pago=body.forma_pago,
                subtotal=subtotal, iva=iva, total=total,
                estado="error", error_mensaje=str(e),
                sandbox=fconf["facturacom_sandbox"],
                usuario_id=int(payload["sub"]) if payload.get("sub") else None,
            )
            db.add(registro)
            db.commit()
            raise HTTPException(status_code=502, detail=str(e))

        # Igual que en la factura global: se graba "timbrada" apenas se confirma el
        # timbrado real, ANTES de intentar descargar PDF/XML — un fallo de red en la
        # descarga no debe disparar un reintento que duplicaría el CFDI real.
        registro = CfdiFacturaIndividual(
            venta_id=body.venta_id, cliente_nombre=body.cliente_nombre, cliente_rfc=body.cliente_rfc,
            cliente_regimen_fiscal=body.cliente_regimen_fiscal, cliente_cp=body.cliente_cp,
            cliente_email=body.cliente_email, uso_cfdi=body.uso_cfdi, forma_pago=body.forma_pago,
            subtotal=subtotal, iva=iva, total=total,
            estado="timbrada", facturacom_id=resultado["facturacom_id"], uuid_fiscal=resultado["uuid"],
            serie=resultado["serie"], folio=resultado["folio"],
            sandbox=fconf["facturacom_sandbox"],
            usuario_id=int(payload["sub"]) if payload.get("sub") else None,
        )
        venta.facturada = True
        db.add(registro)
        db.commit()

        _descargar_y_guardar_documentos_individual(db, registro, fconf)

        return {
            "ok": True, "id": registro.id, "uuid": registro.uuid_fiscal,
            "total": registro.total,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
        _timbrado_lock.release()


@router.get("/individual/historial")
def historial_facturas_individuales(payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        rows = (
            db.query(CfdiFacturaIndividual)
            .order_by(CfdiFacturaIndividual.creado_en.desc())
            .limit(200)
            .all()
        )
        return [
            {
                "id": r.id, "venta_id": r.venta_id,
                "cliente_nombre": r.cliente_nombre, "cliente_rfc": r.cliente_rfc,
                "subtotal": r.subtotal, "iva": r.iva, "total": r.total,
                "estado": r.estado, "sandbox": bool(r.sandbox), "uuid": r.uuid_fiscal, "serie": r.serie, "folio": r.folio,
                "error_mensaje": r.error_mensaje,
                "documentos_pendientes": r.estado == "timbrada" and not r.pdf_path and not r.pdf_url,
                "creado_en": r.creado_en.isoformat() if r.creado_en else None,
                "cancelado_en": r.cancelado_en.isoformat() if r.cancelado_en else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.post("/individual/{cfdi_id}/redescargar")
def redescargar_documentos_individual(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "timbrada":
            raise HTTPException(status_code=400, detail="Solo aplica a facturas ya timbradas")
        fconf = _leer_config_facturacion(db)
        ok = _descargar_y_guardar_documentos_individual(db, r, fconf)
        if not ok:
            raise HTTPException(status_code=502, detail="No se pudo descargar el PDF/XML todavía, intenta de nuevo más tarde")
        return {"ok": True}
    except HTTPException:
        raise
    finally:
        db.close()


@router.post("/individual/{cfdi_id}/abrir-carpeta")
def abrir_carpeta_individual(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r or not r.pdf_path:
            raise HTTPException(status_code=404, detail="No hay archivo guardado localmente para esta factura")
        p = Path(r.pdf_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="El archivo ya no existe en disco")
        import subprocess
        subprocess.Popen(["explorer", "/select,", str(p)])
        return {"ok": True, "path": str(p)}
    except HTTPException:
        raise
    finally:
        db.close()


@router.get("/individual/{cfdi_id}/pdf")
def descargar_pdf_individual(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r or (not r.pdf_path and not r.pdf_url):
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.pdf_path) if r.pdf_path else None
        if p and p.exists():
            return Response(content=p.read_bytes(), media_type="application/pdf", headers={
                "Content-Disposition": f'attachment; filename="factura_{r.folio or r.id}.pdf"'
            })
        if r.pdf_url:
            return RedirectResponse(r.pdf_url)
        raise HTTPException(status_code=404, detail="Archivo PDF no encontrado")
    finally:
        db.close()


@router.get("/individual/{cfdi_id}/xml")
def descargar_xml_individual(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r or (not r.xml_path and not r.xml_url):
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.xml_path) if r.xml_path else None
        if p and p.exists():
            return Response(content=p.read_bytes(), media_type="application/xml", headers={
                "Content-Disposition": f'attachment; filename="factura_{r.folio or r.id}.xml"'
            })
        if r.xml_url:
            return RedirectResponse(r.xml_url)
        raise HTTPException(status_code=404, detail="Archivo XML no encontrado")
    finally:
        db.close()


@router.post("/individual/{cfdi_id}/cancelar")
def cancelar_factura_individual(cfdi_id: int, body: CancelarIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "timbrada":
            raise HTTPException(status_code=400, detail="Solo se puede cancelar una factura timbrada")

        fconf = _leer_config_facturacion(db)
        try:
            facturacom_service.cancelar_cfdi(
                api_key=fconf["facturacom_api_key"], secret_key=fconf["facturacom_secret_key"],
                sandbox=fconf["facturacom_sandbox"],
                facturacom_id=r.facturacom_id, motivo=body.motivo,
            )
        except facturacom_service.FacturaComError as e:
            raise HTTPException(status_code=502, detail=str(e))

        r.estado = "cancelada"
        r.cancelado_en = datetime.now()
        venta = db.query(Venta).filter(Venta.id == r.venta_id).first()
        if venta:
            venta.facturada = False
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/individual/{cfdi_id}")
def eliminar_factura_individual_error(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "error":
            raise HTTPException(status_code=400, detail="Solo se pueden eliminar intentos con error")
        db.delete(r)
        db.commit()
        _purgar_de_turso("cfdi_facturas_individuales", [cfdi_id])
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/individual/eliminar-lote")
def eliminar_facturas_individuales_error_lote(body: EliminarLoteIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    if not body.ids:
        raise HTTPException(status_code=400, detail="Sin ids para eliminar")
    db = get_db_session()
    try:
        rows = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id.in_(body.ids)).all()
        borrables = [r for r in rows if r.estado == "error"]
        omitidos = len(body.ids) - len(borrables)
        ids_borrados = [r.id for r in borrables]
        for r in borrables:
            db.delete(r)
        db.commit()
        _purgar_de_turso("cfdi_facturas_individuales", ids_borrados)
        return {"eliminados": len(ids_borrados), "omitidos": omitidos}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


class EnviarWhatsappIn(BaseModel):
    numero: str = ""


@router.post("/individual/{cfdi_id}/enviar-whatsapp")
def enviar_whatsapp_individual(cfdi_id: int, body: EnviarWhatsappIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "timbrada":
            raise HTTPException(status_code=400, detail="Solo se puede enviar una factura timbrada")
        if not r.pdf_url:
            raise HTTPException(status_code=400, detail="Todavía no hay link de descarga en la nube — reintenta la descarga de documentos primero")

        numero = body.numero.strip()
        if not numero:
            raise HTTPException(
                status_code=400,
                detail="Falta el número de WhatsApp del cliente. Nota: CallMeBot exige que "
                       "ese número se haya autorizado antes con el API key configurado — "
                       "no basta con escribirlo aquí si nunca se dio de alta con CallMeBot.",
            )

        from app.database.models import Configuracion
        rows = db.query(Configuracion).filter(Configuracion.clave.in_(["whatsapp_token"])).all()
        wconf = {x.clave: x.valor for x in rows}
        token = wconf.get("whatsapp_token", "")

        mensaje = (
            f"Tu factura CFDI folio {r.folio or r.id}, total ${r.total:.2f}. "
            f"Descárgala aquí: {r.pdf_url}"
        )
        try:
            from app.services.alertas_service import enviar_whatsapp
            enviar_whatsapp(numero, token, mensaje)
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"ok": True}
    except HTTPException:
        raise
    finally:
        db.close()


class EnviarCorreoIn(BaseModel):
    destinatario: str = ""


@router.post("/individual/{cfdi_id}/enviar-correo")
def enviar_correo_individual(cfdi_id: int, body: EnviarCorreoIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaIndividual).filter(CfdiFacturaIndividual.id == cfdi_id).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        if r.estado != "timbrada":
            raise HTTPException(status_code=400, detail="Solo se puede enviar una factura timbrada")
        if not r.pdf_path or not r.xml_path:
            raise HTTPException(status_code=400, detail="Todavía no hay archivos locales — reintenta la descarga de documentos primero")

        destinatario = body.destinatario.strip() or r.cliente_email
        if not destinatario:
            raise HTTPException(status_code=400, detail="Falta el correo del destinatario")

        fconf = _leer_config_facturacion(db)
        pdf_bytes = Path(r.pdf_path).read_bytes()
        xml_bytes = Path(r.xml_path).read_bytes()
        nombre_base = f"factura_{r.folio or r.id}"

        from app.services.email_service import enviar_email, EmailError
        try:
            enviar_email(
                smtp_host=fconf["email_smtp_host"], smtp_port=int(fconf["email_smtp_port"] or 587),
                smtp_user=fconf["email_smtp_user"], smtp_password=fconf["email_smtp_password"],
                destinatario=destinatario,
                asunto=f"Tu factura {nombre_base}",
                cuerpo=f"Adjuntamos tu CFDI folio {r.folio or r.id}, total ${r.total:.2f}.\nUUID: {r.uuid_fiscal}",
                archivos_adjuntos=[(f"{nombre_base}.pdf", pdf_bytes), (f"{nombre_base}.xml", xml_bytes)],
            )
        except EmailError as e:
            raise HTTPException(status_code=502, detail=str(e))
        return {"ok": True}
    except HTTPException:
        raise
    finally:
        db.close()
