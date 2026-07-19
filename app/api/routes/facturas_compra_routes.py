from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import Response, RedirectResponse
from typing import Optional
from datetime import date, datetime
from pathlib import Path

from app.database.connection import get_db_session
from app.database.models import FacturaCompra
from app.api.routes.auth_routes import get_current_api_user
from app.database import sync_service
import app.config as cfg

router = APIRouter()


def _require_admin(payload):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


def _dir() -> Path:
    d = cfg.DATA_DIR / "facturas_compra"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.get("")
def listar_facturas_compra(
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    proveedor_rfc: Optional[str] = Query(None),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        q = db.query(FacturaCompra)
        if fecha_inicio:
            q = q.filter(FacturaCompra.fecha_factura >= fecha_inicio)
        if fecha_fin:
            q = q.filter(FacturaCompra.fecha_factura <= fecha_fin)
        if proveedor_rfc:
            q = q.filter(FacturaCompra.proveedor_rfc == proveedor_rfc.strip().upper())
        rows = q.order_by(FacturaCompra.fecha_factura.desc(), FacturaCompra.creado_en.desc()).all()
        return [
            {
                "id": r.id,
                "proveedor_nombre": r.proveedor_nombre,
                "proveedor_rfc": r.proveedor_rfc or "",
                "folio_fiscal": r.folio_fiscal or "",
                "fecha_factura": r.fecha_factura.isoformat() if r.fecha_factura else None,
                "subtotal": r.subtotal or 0.0,
                "iva": r.iva or 0.0,
                "total": r.total or 0.0,
                "concepto": r.concepto or "",
                "tiene_xml": bool(r.xml_path or r.xml_url),
                "tiene_pdf": bool(r.pdf_path or r.pdf_url),
                "creado_en": r.creado_en.isoformat() if r.creado_en else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@router.get("/resumen")
def resumen_facturas_compra(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        rows = db.query(FacturaCompra).filter(
            FacturaCompra.fecha_factura >= fecha_inicio,
            FacturaCompra.fecha_factura <= fecha_fin,
        ).all()
        return {
            "num_facturas": len(rows),
            "subtotal": sum(r.subtotal or 0.0 for r in rows),
            "iva": sum(r.iva or 0.0 for r in rows),
            "total": sum(r.total or 0.0 for r in rows),
        }
    finally:
        db.close()


@router.post("")
async def crear_factura_compra(
    proveedor_nombre: str = Form(...),
    proveedor_rfc: str = Form(""),
    folio_fiscal: str = Form(""),
    fecha_factura: date = Form(...),
    subtotal: float = Form(0.0),
    iva: float = Form(0.0),
    total: float = Form(...),
    concepto: str = Form(""),
    xml: Optional[UploadFile] = File(None),
    pdf: Optional[UploadFile] = File(None),
    payload: dict = Depends(get_current_api_user),
):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = FacturaCompra(
            proveedor_nombre=proveedor_nombre.strip(),
            proveedor_rfc=proveedor_rfc.strip().upper() or None,
            folio_fiscal=folio_fiscal.strip() or None,
            fecha_factura=fecha_factura,
            subtotal=subtotal, iva=iva, total=total,
            concepto=concepto.strip() or None,
            usuario_id=int(payload["sub"]) if payload.get("sub") else None,
        )
        db.add(r)
        db.commit()
        db.refresh(r)

        d = _dir()
        if xml is not None and xml.filename:
            p = d / f"{r.id}.xml"
            p.write_bytes(await xml.read())
            r.xml_path = str(p)
        if pdf is not None and pdf.filename:
            p = d / f"{r.id}.pdf"
            p.write_bytes(await pdf.read())
            r.pdf_path = str(p)

        # Respaldo en la nube (Cloudinary) — falla en silencio, no bloquea el registro
        try:
            from app.services.cloudinary_service import upload_documento
            if r.xml_path:
                r.xml_url = upload_documento(r.xml_path, "FARMACIA/FACTURAS_COMPRA", f"{r.id}.xml")
            if r.pdf_path:
                r.pdf_url = upload_documento(r.pdf_path, "FARMACIA/FACTURAS_COMPRA", f"{r.id}.pdf")
        except Exception:
            pass
        db.commit()
        return {"ok": True, "id": r.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/{fid}/xml")
def descargar_xml(fid: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(FacturaCompra).filter(FacturaCompra.id == fid).first()
        if not r or (not r.xml_path and not r.xml_url):
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.xml_path) if r.xml_path else None
        if p and p.exists():
            return Response(content=p.read_bytes(), media_type="application/xml", headers={
                "Content-Disposition": f'attachment; filename="factura_compra_{r.id}.xml"'
            })
        if r.xml_url:
            return RedirectResponse(r.xml_url)
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco ni en la nube")
    finally:
        db.close()


@router.get("/{fid}/pdf")
def descargar_pdf(fid: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(FacturaCompra).filter(FacturaCompra.id == fid).first()
        if not r or (not r.pdf_path and not r.pdf_url):
            raise HTTPException(status_code=404, detail="No encontrado")
        p = Path(r.pdf_path) if r.pdf_path else None
        if p and p.exists():
            return Response(content=p.read_bytes(), media_type="application/pdf", headers={
                "Content-Disposition": f'attachment; filename="factura_compra_{r.id}.pdf"'
            })
        if r.pdf_url:
            return RedirectResponse(r.pdf_url)
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco ni en la nube")
    finally:
        db.close()


@router.delete("/{fid}")
def eliminar_factura_compra(fid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(FacturaCompra).filter(FacturaCompra.id == fid).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        for path_str in (r.xml_path, r.pdf_path):
            if path_str:
                p = Path(path_str)
                if p.exists():
                    p.unlink()
        try:
            from app.services.cloudinary_service import delete_documento
            if r.xml_url:
                delete_documento("FARMACIA/FACTURAS_COMPRA", f"{r.id}.xml")
            if r.pdf_url:
                delete_documento("FARMACIA/FACTURAS_COMPRA", f"{r.id}.pdf")
        except Exception:
            pass
        db.delete(r)
        db.commit()
        # "facturas_compra" está en _NO_TURSO_DELETE: el sync periódico nunca borra por
        # ausencia (cada PC puede tener un subconjunto), así que sin esta purga explícita
        # el siguiente sync_from_turso() resucitaría el registro recién eliminado.
        if cfg.TURSO_SYNC:
            def _purgar():
                try:
                    sync_service.delete_ids_from_turso("facturas_compra", [fid])
                except Exception as e:
                    print(f"[FacturasCompra] No se pudo borrar factura {fid} en Turso: {e}")
            bg.add_task(_purgar)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
