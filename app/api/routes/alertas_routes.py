from fastapi import APIRouter, Depends, Query
from datetime import date, timedelta

from app.database.connection import get_db_session
from app.database.models import Producto, Lote, Cita, EstadoCita
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


@router.get("/pendientes")
def alertas_pendientes(payload: dict = Depends(get_current_api_user)):
    """Returns stock-bajo + próximos a vencer + citas de hoy."""
    db = get_db_session()
    try:
        hoy = date.today()
        limite_venc = hoy + timedelta(days=30)

        # Stock bajo
        stock_bajo = (
            db.query(Producto)
            .filter(Producto.activo == True, Producto.stock <= Producto.stock_minimo)
            .order_by(Producto.stock.asc())
            .limit(10)
            .all()
        )

        # Vencimientos próximos (30 días) o ya vencidos con stock
        lotes_alerta = (
            db.query(Lote)
            .join(Producto, Lote.producto_id == Producto.id)
            .filter(
                Producto.activo == True,
                Lote.cantidad > 0,
                Lote.fecha_vencimiento != None,
                Lote.fecha_vencimiento <= limite_venc,
            )
            .order_by(Lote.fecha_vencimiento.asc())
            .limit(10)
            .all()
        )

        # Citas de hoy
        from datetime import datetime
        inicio_hoy = datetime.combine(hoy, datetime.min.time())
        fin_hoy = datetime.combine(hoy, datetime.max.time())
        citas_hoy = (
            db.query(Cita)
            .filter(
                Cita.fecha_hora >= inicio_hoy,
                Cita.fecha_hora <= fin_hoy,
                Cita.estado == EstadoCita.programada,
            )
            .order_by(Cita.fecha_hora.asc())
            .all()
        )

        return {
            "stock_bajo": [
                {"id": p.id, "nombre": p.nombre, "stock": p.stock, "stock_minimo": p.stock_minimo}
                for p in stock_bajo
            ],
            "vencimientos": [
                {
                    "lote_id": l.id,
                    "producto": l.producto.nombre if l.producto else "",
                    "numero_lote": l.numero_lote or "",
                    "fecha_vencimiento": l.fecha_vencimiento.isoformat(),
                    "dias_restantes": (l.fecha_vencimiento - hoy).days,
                    "cantidad": l.cantidad,
                    "vencido": l.fecha_vencimiento < hoy,
                }
                for l in lotes_alerta
            ],
            "citas_hoy": [
                {
                    "id": c.id,
                    "paciente": c.nombre_paciente or (c.paciente.nombre if c.paciente else "—"),
                    "hora": c.fecha_hora.strftime("%H:%M"),
                    "tipo": c.tipo_servicio or "",
                }
                for c in citas_hoy
            ],
            "totales": {
                "stock_bajo": len(stock_bajo),
                "vencimientos": len(lotes_alerta),
                "citas_hoy": len(citas_hoy),
            },
        }
    finally:
        db.close()
