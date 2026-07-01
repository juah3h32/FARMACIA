from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, RedirectResponse
from pydantic import BaseModel
from datetime import datetime, date
from pathlib import Path

from app.database.connection import get_db_session
from app.database.models import Venta, EstadoVenta, CfdiFacturaGlobal, Configuracion, FacturaCompra
from app.api.routes.auth_routes import get_current_api_user
from app.services import facturama_service
import app.config as cfg

router = APIRouter()

_FACT_KEYS = [
    "facturama_user", "facturama_password", "facturama_sandbox",
    "emisor_razon_social", "emisor_rfc", "emisor_regimen_fiscal", "emisor_cp",
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
        "facturama_user":       d.get("facturama_user", ""),
        "facturama_password":   d.get("facturama_password", ""),
        "facturama_sandbox":    d.get("facturama_sandbox", "1") == "1",
        "emisor_razon_social":  d.get("emisor_razon_social") or cfg.PHARMACY_RAZON_SOCIAL_FISCAL,
        "emisor_rfc":           d.get("emisor_rfc") or cfg.PHARMACY_RFC,
        "emisor_regimen_fiscal": d.get("emisor_regimen_fiscal") or cfg.PHARMACY_REGIMEN_FISCAL,
        "emisor_cp":            d.get("emisor_cp") or cfg.PHARMACY_CP_FISCAL,
    }


def _cfdi_dir() -> Path:
    d = cfg.DATA_DIR / "cfdi"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
        faltantes = [
            campo for campo, label in [
                ("facturama_user", "usuario Facturama"), ("facturama_password", "contraseña Facturama"),
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
                "rfc": facturama_service.RFC_PUBLICO_GENERAL,
                "nombre": "PUBLICO EN GENERAL",
                "uso_cfdi": "S01",
                "regimen_fiscal": "616",
            },
            "concepto": {
                "clave_prod_serv": "01010101",
                "descripcion": f"Venta de mercancías periodo {mes:02d}/{anio} (factura global)",
                "clave_unidad": "ACT",
            },
            "sandbox": fconf["facturama_sandbox"],
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
            resultado = facturama_service.crear_factura_global(
                user=fconf["facturama_user"], password=fconf["facturama_password"],
                sandbox=fconf["facturama_sandbox"],
                mes=body.mes, anio=body.anio,
                subtotal=subtotal, iva=iva, total=total,
                emisor_rfc=fconf["emisor_rfc"], emisor_razon_social=fconf["emisor_razon_social"],
                emisor_regimen_fiscal=fconf["emisor_regimen_fiscal"], emisor_cp=fconf["emisor_cp"],
            )
        except facturama_service.FacturamaError as e:
            registro = CfdiFacturaGlobal(
                mes=body.mes, anio=body.anio, subtotal=subtotal, iva=iva, total=total,
                num_ventas=len(ventas), estado="error", error_mensaje=str(e),
                usuario_id=int(payload["sub"]) if payload.get("sub") else None,
            )
            db.add(registro)
            db.commit()
            raise HTTPException(status_code=502, detail=str(e))

        cfdi_dir = _cfdi_dir()
        pdf_path = cfdi_dir / f"{body.anio}-{body.mes:02d}.pdf"
        xml_path = cfdi_dir / f"{body.anio}-{body.mes:02d}.xml"
        pdf_path.write_bytes(resultado["pdf_bytes"])
        xml_path.write_bytes(resultado["xml_bytes"])

        # Respaldo en la nube (Cloudinary) — no debe tumbar el timbrado si falla,
        # el CFDI ya quedó fiscalmente válido en este punto.
        pdf_url = xml_url = None
        try:
            from app.services.cloudinary_service import upload_documento
            public_id = f"{body.anio}-{body.mes:02d}"
            pdf_url = upload_documento(str(pdf_path), "FARMACIA/CFDI_GLOBAL", f"{public_id}.pdf")
            xml_url = upload_documento(str(xml_path), "FARMACIA/CFDI_GLOBAL", f"{public_id}.xml")
        except Exception:
            pass

        registro = CfdiFacturaGlobal(
            mes=body.mes, anio=body.anio, subtotal=subtotal, iva=iva, total=total,
            num_ventas=len(ventas), estado="timbrada",
            facturama_id=resultado["facturama_id"], uuid_fiscal=resultado["uuid"],
            serie=resultado["serie"], folio=resultado["folio"],
            pdf_path=str(pdf_path), xml_path=str(xml_path),
            pdf_url=pdf_url, xml_url=xml_url,
            usuario_id=int(payload["sub"]) if payload.get("sub") else None,
        )
        db.add(registro)
        db.flush()
        for v in ventas:
            v.facturada = True
            v.cfdi_global_id = registro.id
        db.commit()
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
                "num_ventas": r.num_ventas, "estado": r.estado,
                "uuid": r.uuid_fiscal, "serie": r.serie, "folio": r.folio,
                "error_mensaje": r.error_mensaje,
                "creado_en": r.creado_en.isoformat() if r.creado_en else None,
                "cancelado_en": r.cancelado_en.isoformat() if r.cancelado_en else None,
            }
            for r in rows
        ]
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
            facturama_service.cancelar_cfdi(
                user=fconf["facturama_user"], password=fconf["facturama_password"],
                sandbox=fconf["facturama_sandbox"],
                facturama_id=r.facturama_id, motivo=body.motivo,
            )
        except facturama_service.FacturamaError as e:
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
