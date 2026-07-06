"""Servicio de alertas automáticas por WhatsApp (CallMeBot)."""
import logging
from datetime import date, timedelta

_log = logging.getLogger("pos.alertas")


def _get_config(db):
    from app.database.models import Configuracion
    rows = db.query(Configuracion).filter(
        Configuracion.clave.in_(["whatsapp_token", "whatsapp_numero", "alertas_activas"])
    ).all()
    return {r.clave: r.valor for r in rows}


def _send_whatsapp(numero: str, token: str, mensaje: str):
    try:
        enviar_whatsapp(numero, token, mensaje)
    except Exception as e:
        _log.error(f"Error WhatsApp: {e}")


def enviar_whatsapp(numero: str, token: str, mensaje: str) -> None:
    """Versión que SÍ propaga el error — úsala cuando el caller necesite saber si falló
    (ej. envío de factura), a diferencia de _send_whatsapp que solo loguea y sigue.

    Nota: CallMeBot exige que CADA número destino se haya registrado/autorizado
    manualmente con el API key que se usa para enviar — un apikey vinculado al número
    de la farmacia no sirve automáticamente para mandarle mensajes a un número de
    cliente distinto, aunque la petición HTTP regrese 200 OK. Verifica en la app que
    el mensaje realmente haya llegado la primera vez que uses un número nuevo."""
    import urllib.request, urllib.parse
    if not (numero and token):
        raise ValueError("WhatsApp no configurado (falta número o API key de CallMeBot)")
    url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={numero}&text={urllib.parse.quote(mensaje)}&apikey={token}"
    )
    urllib.request.urlopen(url, timeout=10)
    _log.info(f"WhatsApp enviado a {numero}")


def enviar_alertas_diarias():
    """Genera y envía resumen diario de alertas al número configurado."""
    from app.database.connection import get_db_session
    from app.database.models import Producto, Lote
    db = get_db_session()
    try:
        cfg = _get_config(db)
        if cfg.get("alertas_activas", "0") != "1":
            return
        hoy = date.today()
        prox = hoy + timedelta(days=30)
        bajo = db.query(Producto).filter(
            Producto.activo == True, Producto.stock <= Producto.stock_minimo
        ).count()
        venc = db.query(Lote).filter(
            Lote.fecha_vencimiento != None,
            Lote.fecha_vencimiento <= prox,
            Lote.fecha_vencimiento >= hoy,
            Lote.cantidad > 0,
        ).count()
        vencidos = db.query(Lote).filter(
            Lote.fecha_vencimiento != None,
            Lote.fecha_vencimiento < hoy,
            Lote.cantidad > 0,
        ).count()
        if bajo == 0 and venc == 0 and vencidos == 0:
            return
        msg = f"FarmaciaPOS Alertas {hoy}:\n"
        if bajo:
            msg += f"- {bajo} producto(s) con stock bajo\n"
        if vencidos:
            msg += f"- {vencidos} lote(s) VENCIDOS\n"
        if venc:
            msg += f"- {venc} lote(s) vencen en 30 dias\n"
        numero = cfg.get("whatsapp_numero", "")
        token = cfg.get("whatsapp_token", "")
        if numero and token:
            _send_whatsapp(numero, token, msg)
        _log.info(f"Alertas diarias: {msg.strip()}")
    except Exception as e:
        _log.error(f"enviar_alertas_diarias error: {e}")
    finally:
        db.close()
