"""Servicio de envío de correos de recuperación para los POS que no configuraron su propio correo.

Vive en la web del sistema (Vercel). No recibe HTML: solo el tipo de correo y sus datos, y arma el
correo con las mismas plantillas del POS, así no sirve para mandar otra cosa. Limita los envíos por
destinatario y por IP. Requiere las variables de entorno RELAY_SMTP_USER y RELAY_SMTP_PASSWORD
(cuenta de Gmail del sistema + contraseña de aplicación)."""
import base64
import io
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.database.connection import get_db_session
from app.database.models import RelayEnvio

router = APIRouter()

_POR_DESTINO_HORA = 5
_POR_IP_HORA = 20
_POR_DIA = 400            # Gmail permite ~500 al día por cuenta


class CorreoIn(BaseModel):
    tipo: str
    destinatario: str
    farmacia: str
    nombre: str
    usuario: str
    codigo: str = ""
    portada: str = ""     # PNG en base64 (logo de esa farmacia); opcional
    telefono: str = ""
    direccion: str = ""


def _ip(request: Request) -> str:
    real = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
    return real.split(",")[0].strip() if real else (request.client.host if request.client else "?")


def _portada_segura(b64: str, farmacia: str) -> bytes:
    from app.services.correo_recuperacion import portada_png
    if b64 and len(b64) < 900_000:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(base64.b64decode(b64)))
            if im.format == "PNG" and im.width <= 1600 and im.height <= 800:
                out = io.BytesIO()
                im.convert("RGB").save(out, "PNG", optimize=True)     # se vuelve a codificar: nada extra
                return out.getvalue()
        except Exception:
            pass
    return portada_png(farmacia, logo=False)


@router.post("/correo-recuperacion")
def correo_recuperacion(body: CorreoIn, request: Request):
    usuario_smtp = os.getenv("RELAY_SMTP_USER", "")
    clave_smtp = os.getenv("RELAY_SMTP_PASSWORD", "")
    if not (usuario_smtp and clave_smtp):
        raise HTTPException(status_code=503, detail="El servicio de correo del sistema no está disponible. "
                                                    "Usa un código de respaldo o configura tu propio correo.")
    from app.services.correo_recuperacion import validar_datos, construir, CorreoError
    destino = body.destinatario.strip().lower()
    try:
        validar_datos(body.tipo, body.farmacia.strip(), body.nombre.strip(), body.usuario.strip(),
                      body.codigo.strip(), destino)
    except CorreoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ip = _ip(request)
    ahora = datetime.now()
    db = get_db_session()
    try:
        hora = ahora - timedelta(hours=1)
        if db.query(RelayEnvio).filter(RelayEnvio.destinatario == destino, RelayEnvio.creado_en > hora).count() >= _POR_DESTINO_HORA \
                or db.query(RelayEnvio).filter(RelayEnvio.ip == ip, RelayEnvio.creado_en > hora).count() >= _POR_IP_HORA \
                or db.query(RelayEnvio).filter(RelayEnvio.creado_en > ahora - timedelta(days=1)).count() >= _POR_DIA:
            raise HTTPException(status_code=429, detail="Se enviaron demasiados correos. Espera una hora e intenta de nuevo.")
        db.add(RelayEnvio(destinatario=destino, ip=ip, tipo=body.tipo, creado_en=ahora))
        db.commit()
    finally:
        db.close()
    asunto, html_txt, texto = construir(body.tipo, body.farmacia.strip(), body.nombre.strip(),
                                        body.usuario.strip(), body.codigo.strip(), destino,
                                        {"telefono": body.telefono, "direccion": body.direccion})
    from app.services.email_service import enviar_email_html
    try:
        enviar_email_html(smtp_host=os.getenv("RELAY_SMTP_HOST", "smtp.gmail.com"),
                          smtp_port=int(os.getenv("RELAY_SMTP_PORT", "587")),
                          smtp_user=usuario_smtp, smtp_password=clave_smtp, destinatario=destino,
                          asunto=asunto, html_txt=html_txt, texto=texto,
                          remitente_nombre=body.farmacia.strip()[:60],
                          imagenes={"portada": _portada_segura(body.portada, body.farmacia.strip())})
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo enviar el correo. Intenta más tarde.")
    return {"ok": True}
