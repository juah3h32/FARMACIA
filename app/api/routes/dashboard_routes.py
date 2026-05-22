from fastapi import APIRouter, Depends
from app.database.connection import get_db_session
from app.database.models import Venta, Producto, EstadoVenta
from app.api.routes.auth_routes import get_current_api_user
from sqlalchemy import func
from datetime import datetime

router = APIRouter()


@router.get("/stats")
def dashboard_stats(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        now = datetime.utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end   = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        ventas_hoy = db.query(func.count(Venta.id)).filter(
            Venta.creado_en >= day_start,
            Venta.creado_en <= day_end,
            Venta.estado == EstadoVenta.completada,
        ).scalar() or 0

        ingresos_hoy = db.query(func.sum(Venta.total)).filter(
            Venta.creado_en >= day_start,
            Venta.creado_en <= day_end,
            Venta.estado == EstadoVenta.completada,
        ).scalar() or 0.0

        stock_bajo = db.query(func.count(Producto.id)).filter(
            Producto.stock <= Producto.stock_minimo,
            Producto.activo == True,
        ).scalar() or 0

        total_productos = db.query(func.count(Producto.id)).filter(
            Producto.activo == True,
        ).scalar() or 0

        recent = db.query(Venta).order_by(Venta.creado_en.desc()).limit(8).all()
        recent_sales = [
            {
                "folio":      v.folio or str(v.id),
                "total":      v.total,
                "estado":     v.estado.value,
                "metodo_pago": v.metodo_pago.value,
                "creado_en":  v.creado_en.strftime("%d/%m %H:%M") if v.creado_en else "",
                "cajero":     v.usuario.nombre if v.usuario else "",
            }
            for v in recent
        ]

        return {
            "ventas_hoy":     ventas_hoy,
            "ingresos_hoy":   round(float(ingresos_hoy), 2),
            "stock_bajo":     stock_bajo,
            "total_productos": total_productos,
            "recent_sales":   recent_sales,
        }
    finally:
        db.close()
