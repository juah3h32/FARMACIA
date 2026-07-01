from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from datetime import datetime, date
from pathlib import Path

from app.database.connection import get_db_session
from app.database.models import Venta, EstadoVenta, CfdiFacturaGlobal, Configuracion
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


def _leer_config_facturacion(db) -> dict:
    rows = db.query(Configuracion).filter(Configuracion.clave.in_(_FACT_KEYS)).all()
    d = {r.clave: r.valor for r in rows}
    return {
        "facturama_user":       d.get("facturama_user", ""),
        "facturama_password":   d.get("facturama_password", ""),
        "facturama_sandbox":    d.get("facturama_sandbox", "1") == "1",
        "emisor_razon_social":  d.get("emisor_razon_social") or cfg.PHARMACY_NAME,
        "emisor_rfc":           d.get("emisor_rfc") or cfg.PHARMACY_RFC,
        "emisor_regimen_fiscal": d.get("emisor_regimen_fiscal", ""),
        "emisor_cp":            d.get("emisor_cp", ""),
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
        return {
            "mes": mes, "anio": anio,
            "num_ventas": len(ventas),
            "subtotal": round(subtotal, 2),
            "iva": round(iva, 2),
            "total": round(total, 2),
            "ya_facturado": bool(ya_existe),
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

        registro = CfdiFacturaGlobal(
            mes=body.mes, anio=body.anio, subtotal=subtotal, iva=iva, total=total,
            num_ventas=len(ventas), estado="timbrada",
            facturama_id=resultado["facturama_id"], uuid_fiscal=resultado["uuid"],
            serie=resultado["serie"], folio=resultado["folio"],
            pdf_path=str(pdf_path), xml_path=str(xml_path),
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
        if not r or not r.pdf_path:
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.pdf_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Archivo PDF no encontrado en disco")
        return Response(content=p.read_bytes(), media_type="application/pdf", headers={
            "Content-Disposition": f'attachment; filename="factura_global_{r.anio}-{r.mes:02d}.pdf"'
        })
    finally:
        db.close()


@router.get("/{cfdi_id}/xml")
def descargar_xml(cfdi_id: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(CfdiFacturaGlobal).filter(CfdiFacturaGlobal.id == cfdi_id).first()
        if not r or not r.xml_path:
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.xml_path)
        if not p.exists():
            raise HTTPException(status_code=404, detail="Archivo XML no encontrado en disco")
        return Response(content=p.read_bytes(), media_type="application/xml", headers={
            "Content-Disposition": f'attachment; filename="factura_global_{r.anio}-{r.mes:02d}.xml"'
        })
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
