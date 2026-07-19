from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date, timedelta
from app.database.connection import get_db_session
from app.database.models import Cita, EstadoCita
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()

# No hay campo de duración en el modelo Cita — se asume un slot fijo para
# detectar traslapes. Ajusta si tus citas normalmente duran otra cosa.
DURACION_CITA_MIN = 30


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

        # Traslape: mismo usuario_id (doctor/encargado) con otra cita activa
        # dentro de la misma ventana de tiempo (no hay campo de duración —
        # se usa un slot fijo DURACION_CITA_MIN).
        ventana = timedelta(minutes=DURACION_CITA_MIN)
        nueva_inicio = data["fecha_hora"]
        conflicto = (
            db.query(Cita)
            .filter(
                Cita.usuario_id == data["usuario_id"],
                Cita.estado.in_([EstadoCita.programada, EstadoCita.completada]),
                Cita.fecha_hora > nueva_inicio - ventana,
                Cita.fecha_hora < nueva_inicio + ventana,
            )
            .first()
        )
        if conflicto:
            raise HTTPException(
                status_code=409,
                detail=f"Ya hay una cita a las {conflicto.fecha_hora.strftime('%H:%M')} para este mismo horario/encargado — "
                       f"elige otra hora (mínimo {DURACION_CITA_MIN} min de diferencia)",
            )

        c = Cita(**data)
        db.add(c)
        db.commit()
        db.refresh(c)
        return _cita_dict(c)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()


@router.patch("/{cid}/estado")
def cambiar_estado(cid: int, estado: str, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        if estado not in EstadoCita._value2member_map_:
            raise HTTPException(400, f"Estado inválido: {estado}")
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
def eliminar_cita(cid: int, bg: BackgroundTasks, payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        c = db.query(Cita).filter(Cita.id == cid).first()
        if not c:
            raise HTTPException(404, "Cita no encontrada")
        db.delete(c)
        db.commit()
        import app.config as _cfg
        if _cfg.TURSO_SYNC:
            from app.database.sync_service import sync_to_turso, delete_ids_from_turso
            # citas está en _NO_TURSO_DELETE (sync normal nunca borra por ausencia) —
            # sin este delete explícito la cita borrada reaparecía en el próximo pull.
            # Síncrono (no bg.add_task): si la app cierra justo después de borrar
            # (p.ej. para instalar una actualización), una tarea en background se
            # pierde antes de llegar a Turso y el borrado "resucita" en el próximo pull.
            delete_ids_from_turso("citas", [cid])
            bg.add_task(sync_to_turso)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, str(e))
    finally:
        db.close()
