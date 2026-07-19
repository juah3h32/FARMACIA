from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from sqlalchemy import or_
from app.database.connection import get_db_session
from app.database.models import Paciente, RegistroClinico, Venta, ItemVenta, Cliente
from sqlalchemy.orm import joinedload
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _require_admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


class PacienteIn(BaseModel):
    nombre: str
    fecha_nacimiento: Optional[date] = None
    sexo: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    direccion: Optional[str] = None
    alergias: Optional[str] = None
    antecedentes: Optional[str] = None
    cliente_id: Optional[int] = None


class RegistroIn(BaseModel):
    fecha: Optional[datetime] = None
    presion_sistolica: Optional[int] = None
    presion_diastolica: Optional[int] = None
    pulso: Optional[int] = None
    temperatura: Optional[float] = None
    peso: Optional[float] = None
    talla: Optional[float] = None
    glucosa: Optional[float] = None
    saturacion_o2: Optional[float] = None
    motivo: Optional[str] = None
    diagnostico: Optional[str] = None
    tratamiento: Optional[str] = None
    notas: Optional[str] = None


def _paciente_dict(p):
    return {
        "id": p.id,
        "nombre": p.nombre,
        "fecha_nacimiento": p.fecha_nacimiento.isoformat() if p.fecha_nacimiento else None,
        "sexo": p.sexo,
        "telefono": p.telefono,
        "email": p.email,
        "direccion": p.direccion,
        "alergias": p.alergias,
        "antecedentes": p.antecedentes,
        "cliente_id": p.cliente_id,
        "cliente_nombre": p.cliente.nombre if p.cliente else None,
        "creado_en": p.creado_en.isoformat() if p.creado_en else None,
    }


def _registro_dict(r):
    return {
        "id": r.id,
        "paciente_id": r.paciente_id,
        "fecha": r.fecha.isoformat() if r.fecha else None,
        "presion_sistolica": r.presion_sistolica,
        "presion_diastolica": r.presion_diastolica,
        "pulso": r.pulso,
        "temperatura": r.temperatura,
        "peso": r.peso,
        "talla": r.talla,
        "glucosa": r.glucosa,
        "saturacion_o2": r.saturacion_o2,
        "motivo": r.motivo,
        "diagnostico": r.diagnostico,
        "tratamiento": r.tratamiento,
        "notas": r.notas,
        "usuario_id": r.usuario_id,
        "usuario_nombre": r.usuario.nombre if r.usuario else None,
        "creado_en": r.creado_en.isoformat() if r.creado_en else None,
    }


@router.get("/pacientes")
def listar_pacientes(q: Optional[str] = None, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        query = db.query(Paciente).filter(Paciente.activo == True)
        if q:
            query = query.filter(Paciente.nombre.ilike(f"%{q}%"))
        return [_paciente_dict(p) for p in query.order_by(Paciente.nombre).all()]
    finally:
        db.close()


@router.post("/pacientes")
def crear_paciente(body: PacienteIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        p = Paciente(**body.model_dump())
        db.add(p)
        db.commit()
        db.refresh(p)
        return _paciente_dict(p)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/pacientes/{pid}")
def obtener_paciente(pid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        p = db.query(Paciente).filter(Paciente.id == pid, Paciente.activo == True).first()
        if not p:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")
        d = _paciente_dict(p)
        d["registros"] = sorted(
            [_registro_dict(r) for r in p.registros],
            key=lambda x: x["fecha"] or x["creado_en"] or "",
            reverse=True,
        )
        return d
    finally:
        db.close()


@router.put("/pacientes/{pid}")
def actualizar_paciente(pid: int, body: PacienteIn, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Paciente).filter(Paciente.id == pid).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        for k, v in body.model_dump().items():
            setattr(p, k, v)
        db.commit()
        return _paciente_dict(p)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/pacientes/{pid}")
def eliminar_paciente(pid: int, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        p = db.query(Paciente).filter(Paciente.id == pid).first()
        if not p:
            raise HTTPException(status_code=404, detail="No encontrado")
        p.activo = False
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/pacientes/{pid}/registros")
def agregar_registro(pid: int, body: RegistroIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        p = db.query(Paciente).filter(Paciente.id == pid, Paciente.activo == True).first()
        if not p:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")
        data = body.model_dump()
        data["paciente_id"] = pid
        data["usuario_id"] = int(payload["sub"])
        r = RegistroClinico(**data)
        db.add(r)
        db.commit()
        db.refresh(r)
        return _registro_dict(r)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.delete("/registros/{rid}")
def eliminar_registro(rid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    _require_admin(payload)
    db = get_db_session()
    try:
        r = db.query(RegistroClinico).filter(RegistroClinico.id == rid).first()
        if not r:
            raise HTTPException(status_code=404, detail="No encontrado")
        db.delete(r)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso, delete_ids_from_turso
            # Síncrono: evita que el borrado se pierda si la app cierra justo
            # después (p.ej. para instalar una actualización) antes de que una
            # tarea en background alcance a llegar a Turso.
            delete_ids_from_turso("registros_clinicos", [rid])
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/pacientes/{pid}/ventas")
def ventas_paciente(pid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        p = db.query(Paciente).filter(Paciente.id == pid, Paciente.activo == True).first()
        if not p:
            raise HTTPException(status_code=404, detail="Paciente no encontrado")
        if not p.cliente_id:
            return []
        ventas = (
            db.query(Venta)
            .filter(Venta.cliente_id == p.cliente_id)
            .options(
                joinedload(Venta.items).joinedload(ItemVenta.producto),
                joinedload(Venta.usuario),
            )
            .order_by(Venta.creado_en.desc())
            .all()
        )
        return [
            {
                "id":             v.id,
                "folio":          v.folio,
                "total":          v.total,
                "subtotal":       v.subtotal,
                "descuento":      v.descuento,
                "iva":            v.iva,
                "metodo_pago":    v.metodo_pago.value,
                "estado":         v.estado.value,
                "creado_en":      v.creado_en.isoformat() if v.creado_en else None,
                "cajero":         v.usuario.nombre if v.usuario else "—",
                "cajero_usuario": v.usuario.username if v.usuario else "—",
                "items": [
                    {
                        "nombre":          i.producto.nombre if i.producto else "—",
                        "cantidad":        i.cantidad,
                        "precio_unitario": i.precio_unitario,
                        "descuento":       i.descuento,
                        "subtotal":        i.subtotal,
                    }
                    for i in v.items
                ],
            }
            for v in ventas
        ]
    finally:
        db.close()


@router.get("/clientes")
def buscar_clientes(q: Optional[str] = None, payload: dict = Depends(get_current_api_user)):
    """Devuelve clientes para el selector en el modal de paciente."""
    db = get_db_session()
    try:
        query = db.query(Cliente).filter(Cliente.activo == True)
        if q:
            query = query.filter(Cliente.nombre.ilike(f"%{q}%"))
        rows = query.order_by(Cliente.nombre).limit(50).all()
        return [{"id": c.id, "nombre": c.nombre, "telefono": c.telefono} for c in rows]
    finally:
        db.close()
