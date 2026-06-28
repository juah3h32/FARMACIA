from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from app.database.connection import get_db_session
from app.database.models import Cita
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


class CitaIn(BaseModel):
    paciente_id: Optional[int] = None
    fecha_hora: datetime
    tipo_servicio: Optional[str] = None
    nombre_paciente: Optional[str] = None
    telefono: Optional[str] = None
    notas: Optional[str] = None
    usuario_id: Optional[int] = None


def _cita_dict(c):
    return {
        "id": c.id,
        "paciente_id": c.paciente_id,
        "paciente_nombre": c.paciente.nombre if c.paciente else c.nombre_paciente,
        "nombre_paciente": c.nombre_paciente,
        "telefono": c.telefono,
        "usuario_id": c.usuario_id,
        "usuario_nombre": c.usuario.nombre if c.usuario else None,
        "fecha_hora": c.fecha_hora.isoformat() if c.fecha_hora else None,
        "tipo_servicio": c.tipo_servicio,
        "estado": c.estado.value if hasattr(c.estado, "value") else c.estado,
        "notas": c.notas,
        "creado_en": c.creado_en.isoformat() if c.creado_en else None,
    }


@router.get("")
def listar_citas(fecha: Optional[str] = None, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        q = db.query(Cita)
        if fecha:
            d = date.fromisoformat(fecha)
            q = q.filter(
                Cita.fecha_hora >= datetime.combine(d, datetime.min.time()),
                Cita.fecha_hora < datetime.combine(d, datetime.max.time()),
            )
        citas = q.order_by(Cita.fecha_hora).all()
        return [_cita_dict(c) for c in citas]
    finally:
        db.close()


@router.post("")
def crear_cita(body: CitaIn, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        data = body.model_dump()
        if not data.get("usuario_id"):
            data["usuario_id"] = int(payload["sub"])
        c = Cita(**data)
        db.add(c)
        db.commit()
        db.refresh(c)
        return _cita_dict(c)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.patch("/{cid}/estado")
def cambiar_estado(cid: int, estado: str, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = db.query(Cita).filter(Cita.id == cid).first()
        if not c:
            raise HTTPException(404, "Cita no encontrada")
        c.estado = estado
        db.commit()
        return _cita_dict(c)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.delete("/{cid}")
def eliminar_cita(cid: int, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = db.query(Cita).filter(Cita.id == cid).first()
        if not c:
            raise HTTPException(404, "Cita no encontrada")
        db.delete(c)
        db.commit()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()
