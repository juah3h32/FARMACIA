from fastapi import APIRouter, HTTPException, Request, status, Depends, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from app.database.connection import get_db_session, SessionLocal
from app.database.models import Usuario, PasswordReset, Configuracion, AuditoriaLog
from app.auth.auth_service import (verify_password, create_api_token, verify_api_token, hash_password,
                                   DUMMY_HASH, es_password_por_defecto, generar_codigos_respaldo,
                                   hash_codigo, normalizar_codigo)
import app.config as cfg
import hmac, secrets, json, time, threading
from collections import defaultdict

router = APIRouter()
security = HTTPBearer()

PASSWORD_MIN = 8

# ── Límite de intentos: por IP (10 en 5 min) y por usuario (5 fallos → 15 min bloqueado) ──
_attempts: dict[str, list] = defaultdict(list)
_fallos_usuario: dict[str, list] = defaultdict(list)
_attempts_lock = threading.Lock()


def _check_rate_limit(ip: str, clave: str = ""):
    now = time.time()
    with _attempts_lock:
        recent = [t for t in _attempts[ip] if now - t < 300]
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera 5 minutos.")
        recent.append(now)
        _attempts[ip] = recent
        if clave:
            fallos = [t for t in _fallos_usuario[clave] if now - t < 900]
            _fallos_usuario[clave] = fallos
            if len(fallos) >= 5:
                raise HTTPException(status_code=429, detail="Demasiados intentos para esta cuenta. Espera 15 minutos.")


def _registrar_fallo(clave: str):
    with _attempts_lock:
        _fallos_usuario[clave].append(time.time())


def _clear_attempts(ip: str, clave: str = ""):
    with _attempts_lock:
        _attempts.pop(ip, None)
        _fallos_usuario.pop(clave, None)


def _client_ip(request: Request) -> str:
    # Solo detrás del proxy de Vercel se usa X-Forwarded-For (lo pone Vercel). En las PCs
    # cualquiera podría inventarse ese encabezado para saltarse el límite de intentos.
    if cfg._ON_VERCEL:
        real = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
        if real:
            return real.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _auditar(usuario_id, accion: str, detalles: str = ""):
    db = get_db_session()
    try:
        db.add(AuditoriaLog(usuario_id=usuario_id, accion=accion, tabla="usuarios",
                            registro_id=usuario_id, detalles=detalles))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _sync_bg(bg: BackgroundTasks | None):
    if cfg.TURSO_SYNC and bg is not None:
        from app.database.sync_service import sync_to_turso
        bg.add_task(sync_to_turso)


def _validar_nueva(nueva: str, username: str = ""):
    if len(nueva or "") < PASSWORD_MIN:
        raise HTTPException(status_code=400, detail=f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres")
    if es_password_por_defecto(nueva) or (username and nueva.lower() == username.lower()):
        raise HTTPException(status_code=400, detail="Elige una contraseña distinta (no la de fábrica ni tu usuario)")


def cambiar_password_de(user: Usuario, nueva: str):
    """Pone la contraseña nueva y cierra todas las sesiones abiertas de ese usuario."""
    user.password_hash = hash_password(nueva)
    user.token_version = (user.token_version or 0) + 1
    user.debe_cambiar_password = False
    user.actualizado_en = datetime.now()


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_id: int
    username: str
    nombre: str = ""
    rol: str
    foto_url: Optional[str] = None
    debe_cambiar_password: bool = False
    sin_codigos_respaldo: bool = False


def get_current_api_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = verify_api_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    # Un token de cliente de la app (o uno viejo sin "typ" con rol de cliente)
    # nunca es un empleado — su `sub` es un id de clientes_app, no de usuarios.
    if payload.get("typ", "pos") != "pos" or payload.get("rol") in ("cliente_app", "admin_web"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    # Revalidar contra la BD: un usuario desactivado (o con rol cambiado) no debe
    # seguir teniendo acceso solo porque su JWT viejo aún no expiró. Siempre la
    # BD LOCAL: quien inició sesión es un usuario de esta PC aunque esté
    # administrando otra sucursal (ver sucursales.py).
    db = SessionLocal()
    try:
        user = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        if not user or not user.activo:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario inactivo o eliminado")
        # Al cambiar o restablecer la contraseña se cierran todas las sesiones anteriores
        if int(payload.get("tv", 0)) != int(user.token_version or 0):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión se cerró: vuelve a iniciar sesión")
        payload["rol"] = user.rol.value
        return payload
    finally:
        db.close()


@router.post("/login", response_model=TokenResponse)
def api_login(body: LoginRequest, request: Request, bg: BackgroundTasks):
    ip = _client_ip(request)
    clave = (body.username or "").strip().lower()
    _check_rate_limit(ip, clave)
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(
            Usuario.username == body.username,
            Usuario.activo == True
        ).first()
        # Siempre se verifica un hash (aunque el usuario no exista) para no revelar por tiempo
        # de respuesta qué usuarios existen.
        ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
        if not user or not ok:
            _registrar_fallo(clave)
            if user:
                _auditar(user.id, "LOGIN_FALLIDO", f"IP {ip}")
            # En la PC del punto de venta se dice cuál falló (más fácil para el usuario); en la web,
            # abierta a internet, no se revela qué usuarios existen.
            if cfg._ON_VERCEL:
                detalle = "Usuario o contraseña incorrectos"
            else:
                detalle = "La contraseña no es correcta" if user else "Ese usuario no existe. Revisa cómo está escrito."
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detalle)
        _clear_attempts(ip, clave)
        # La contraseña de fábrica (admin123/cajero123) es pública: se obliga a cambiarla
        if es_password_por_defecto(body.password) and not user.debe_cambiar_password:
            user.debe_cambiar_password = True
            user.actualizado_en = datetime.now()
            db.commit()
        token = create_api_token(user.id, user.username, user.nombre, user.rol.value,
                                 token_version=user.token_version or 0)
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user_id=user.id,
            username=user.username,
            nombre=user.nombre,
            rol=user.rol.value,
            foto_url=user.foto_url,
            debe_cambiar_password=bool(user.debe_cambiar_password),
            sin_codigos_respaldo=user.rol.value == "admin" and not user.recovery_codes,
        )
    finally:
        db.close()


@router.get("/me")
def api_me(payload: dict = Depends(get_current_api_user)):
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        if not user:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return {"id": user.id, "username": user.username, "nombre": user.nombre, "rol": user.rol.value,
                "foto_url": user.foto_url, "email": user.email,
                "debe_cambiar_password": bool(user.debe_cambiar_password),
                "codigos_respaldo": len(json.loads(user.recovery_codes or "[]"))}
    finally:
        db.close()


# ── Cambiar mi contraseña ─────────────────────────────────────────────────────
class CambiarPasswordIn(BaseModel):
    actual: str
    nueva: str


@router.post("/cambiar-password")
def cambiar_password(body: CambiarPasswordIn, request: Request, bg: BackgroundTasks,
                     payload: dict = Depends(get_current_api_user)):
    _check_rate_limit(_client_ip(request))
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        if not user or not verify_password(body.actual, user.password_hash):
            raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
        _validar_nueva(body.nueva, user.username)
        cambiar_password_de(user, body.nueva)
        db.commit()
        token = create_api_token(user.id, user.username, user.nombre, user.rol.value,
                                 token_version=user.token_version)
        sin_codigos = user.rol.value == "admin" and not user.recovery_codes
        uid = user.id
    finally:
        db.close()
    _auditar(uid, "PASSWORD_CAMBIADA", "El usuario cambió su contraseña")
    _sync_bg(bg)
    # token nuevo: el de esta sesión sigue funcionando; las demás sesiones se cierran
    return {"ok": True, "access_token": token, "sin_codigos_respaldo": sin_codigos}


# ── Códigos de respaldo (admin): sirven para recuperar la cuenta sin internet ──
class PasswordIn(BaseModel):
    password: str


@router.post("/codigos-respaldo")
def crear_codigos_respaldo(body: PasswordIn, request: Request, bg: BackgroundTasks,
                           payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    _check_rate_limit(_client_ip(request))
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=400, detail="La contraseña no es correcta")
        codigos = generar_codigos_respaldo()
        user.recovery_codes = json.dumps([hash_codigo(c) for c in codigos])
        user.actualizado_en = datetime.now()
        db.commit()
        uid = user.id
    finally:
        db.close()
    _auditar(uid, "CODIGOS_RESPALDO", "Se generaron códigos de respaldo nuevos (los anteriores ya no sirven)")
    _sync_bg(bg)
    return {"codigos": codigos}


# ── Recuperación por correo: a qué correo llega y con qué cuenta se envía (admin) ──
_SMTP_POR_DOMINIO = {"gmail.com": "smtp.gmail.com", "googlemail.com": "smtp.gmail.com",
                     "outlook.com": "smtp-mail.outlook.com", "hotmail.com": "smtp-mail.outlook.com",
                     "live.com": "smtp-mail.outlook.com", "yahoo.com": "smtp.mail.yahoo.com"}


@router.get("/recuperacion-correo")
def ver_recuperacion_correo(payload: dict = Depends(get_current_api_user)):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    from app.services.correo_recuperacion import smtp_propio
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        propio = smtp_propio(db)
        return {"email": user.email or "", "modo": "propio" if propio else "sistema",
                "smtp_user": (propio or {}).get("email_smtp_user", "")}
    finally:
        db.close()


class RecuperacionCorreoIn(BaseModel):
    password: str            # contraseña actual del admin (confirma que es él)
    email: str               # a dónde llega el código
    smtp_password: str = ""  # opcional: contraseña de aplicación para enviar con el Gmail propio


@router.post("/recuperacion-correo")
def guardar_recuperacion_correo(body: RecuperacionCorreoIn, request: Request, bg: BackgroundTasks,
                                payload: dict = Depends(get_current_api_user)):
    """Guarda el correo del admin y manda un correo de prueba. Sin más datos se envía con el
    servicio del sistema; con contraseña de aplicación, desde el propio Gmail de la farmacia."""
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    _check_rate_limit(_client_ip(request))
    import re as _re
    from app.services.correo_recuperacion import enviar, nombre_farmacia, smtp_propio, contacto_farmacia, CorreoError
    email = body.email.strip().lower()
    if not _re.fullmatch(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+", email):
        raise HTTPException(status_code=400, detail="Escribe un correo válido")
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(Usuario.id == int(payload["sub"])).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=400, detail="La contraseña no es correcta")
        clave = "".join(body.smtp_password.split())          # Google la muestra con espacios
        smtp = smtp_propio(db)
        nuevo_smtp = None
        if clave:
            host = _SMTP_POR_DOMINIO.get(email.split("@")[-1], "smtp." + email.split("@")[-1])
            nuevo_smtp = {"email_smtp_host": host, "email_smtp_port": "587", "email_smtp_user": email,
                          "email_smtp_password": clave}
            smtp = nuevo_smtp
        farmacia = nombre_farmacia(db)
        try:
            modo = enviar("prueba", email, farmacia, user.nombre, user.username, smtp=smtp,
                          contacto=contacto_farmacia(db))
        except CorreoError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            msg = str(e)
            if "535" in msg or "Username and Password not accepted" in msg or "BadCredentials" in msg:
                msg = ("Gmail no aceptó la contraseña de aplicación (myaccount.google.com/apppasswords). "
                       "Déjala vacía para usar el servicio de correo del sistema.")
            raise HTTPException(status_code=400, detail=f"No se pudo enviar el correo de prueba: {msg[:200]}")
        for k, v in (nuevo_smtp or {}).items():
            row = db.query(Configuracion).filter(Configuracion.clave == k).first()
            if row:
                row.valor = v
            else:
                db.add(Configuracion(clave=k, valor=v))
        user.email = email
        user.actualizado_en = datetime.now()
        db.commit()
        uid = user.id
    finally:
        db.close()
    _auditar(uid, "RECUPERACION_CORREO", f"Correo de recuperación: {_ocultar_correo(email)} ({modo})")
    _sync_bg(bg)
    return {"ok": True, "email": email, "modo": modo}


# ── ¿Olvidaste tu contraseña? ────────────────────────────────────────────────
_MSG_GENERICO = ("Si es la cuenta del administrador y tiene correo registrado, le enviamos un código. "
                 "Revisa el correo (también la carpeta de spam).")


def _admin_por_usuario(db, username: str):
    from app.database.models import RolUsuario
    return db.query(Usuario).filter(Usuario.username == (username or "").strip(), Usuario.activo == True,
                                    Usuario.rol == RolUsuario.admin).first()


class SolicitarIn(BaseModel):
    username: str


def _smtp(db) -> dict:
    claves = ("email_smtp_host", "email_smtp_port", "email_smtp_user", "email_smtp_password")
    d = {r.clave: r.valor for r in db.query(Configuracion).filter(Configuracion.clave.in_(claves)).all()}
    return d


def _ocultar_correo(email: str) -> str:
    u, _, dom = (email or "").partition("@")
    return (u[:2] + "•••@" + dom) if dom else ""


def _correos_ultima_hora(db, usuario_id) -> int:
    return db.query(PasswordReset).filter(PasswordReset.usuario_id == usuario_id, PasswordReset.canal == "email",
                                          PasswordReset.creado_en > datetime.now() - timedelta(hours=1)).count()


@router.post("/recuperar/solicitar")
def recuperar_solicitar(body: SolicitarIn, request: Request):
    ip = _client_ip(request)
    _check_rate_limit(ip)
    from app.services.correo_recuperacion import enviar, nombre_farmacia, smtp_propio, contacto_farmacia, CorreoError
    db = get_db_session()
    try:
        user = _admin_por_usuario(db, body.username)
        # Solo el administrador recupera su cuenta por correo (los cajeros se la piden al admin).
        if not user or not (user.email or "").strip():
            return {"ok": True, "mensaje": _MSG_GENERICO}
        if _correos_ultima_hora(db, user.id) >= 3:
            return {"ok": True, "mensaje": _MSG_GENERICO}
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        db.query(PasswordReset).filter(PasswordReset.usuario_id == user.id,
                                       PasswordReset.usado_en.is_(None)).update({"usado_en": datetime.now()})
        db.add(PasswordReset(usuario_id=user.id, code_hash=hash_password(codigo), canal="email",
                             expira_en=datetime.now() + timedelta(minutes=15), intentos=0, ip=ip))
        db.commit()
        destino, uid, nombre, usuario = user.email.strip(), user.id, user.nombre, user.username
        smtp, farmacia, contacto = smtp_propio(db), nombre_farmacia(db), contacto_farmacia(db)
    finally:
        db.close()
    try:
        modo = enviar("codigo", destino, farmacia, nombre, usuario, codigo, smtp=smtp, contacto=contacto)
    except CorreoError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo enviar el correo (¿sin internet?). Usa un código de respaldo.")
    _auditar(uid, "RECUPERAR_SOLICITADO", f"Código enviado a {_ocultar_correo(destino)} ({modo}) desde IP {ip}")
    return {"ok": True, "mensaje": _MSG_GENERICO}


class ConfirmarIn(BaseModel):
    username: str
    codigo: str
    nueva: str


_MSG_CODIGO_MAL = "El código no es válido o ya venció. Pide uno nuevo."


@router.post("/recuperar/confirmar")
def recuperar_confirmar(body: ConfirmarIn, request: Request, bg: BackgroundTasks):
    ip = _client_ip(request)
    _check_rate_limit(ip, (body.username or "").strip().lower())
    db = get_db_session()
    try:
        user = _admin_por_usuario(db, body.username)
        pr = None
        if user:
            pr = (db.query(PasswordReset)
                  .filter(PasswordReset.usuario_id == user.id, PasswordReset.usado_en.is_(None),
                          PasswordReset.canal == "email", PasswordReset.expira_en > datetime.now())
                  .order_by(PasswordReset.id.desc()).first())
        if not pr or (pr.intentos or 0) >= 5:
            _registrar_fallo((body.username or "").strip().lower())
            raise HTTPException(status_code=400, detail=_MSG_CODIGO_MAL)
        if not verify_password(body.codigo.strip(), pr.code_hash):
            pr.intentos = (pr.intentos or 0) + 1
            db.commit()
            _registrar_fallo((body.username or "").strip().lower())
            raise HTTPException(status_code=400, detail=_MSG_CODIGO_MAL)
        _validar_nueva(body.nueva, user.username)
        cambiar_password_de(user, body.nueva)
        pr.usado_en = datetime.now()
        db.commit()
        uid = user.id
    finally:
        db.close()
    _auditar(uid, "PASSWORD_RESTABLECIDA", f"Con código por correo, IP {ip}")
    _sync_bg(bg)
    return {"ok": True}


@router.post("/recuperar/codigo-admin")
def recuperar_con_codigo_admin(body: ConfirmarIn, request: Request, bg: BackgroundTasks):
    """Empleado que olvidó su contraseña: el código de acceso que le generó el admin."""
    ip = _client_ip(request)
    clave = (body.username or "").strip().lower()
    _check_rate_limit(ip, clave)
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(Usuario.username == body.username.strip(), Usuario.activo == True).first()
        datos = {}
        try:
            datos = json.loads(user.codigo_acceso or "{}") if user else {}
        except Exception:
            datos = {}
        vigente = bool(datos.get("h")) and datos.get("vence", "") > datetime.now().isoformat(timespec="seconds") \
            and int(datos.get("intentos", 0)) < 5
        if not vigente or not verify_password(normalizar_codigo(body.codigo), datos["h"]):
            if user and vigente:
                datos["intentos"] = int(datos.get("intentos", 0)) + 1
                user.codigo_acceso = json.dumps(datos)
                db.commit()
            _registrar_fallo(clave)
            raise HTTPException(status_code=400, detail="El código no es válido o ya venció. Pídele uno nuevo al administrador.")
        _validar_nueva(body.nueva, user.username)
        cambiar_password_de(user, body.nueva)
        user.codigo_acceso = None
        db.commit()
        uid = user.id
    finally:
        db.close()
    _auditar(uid, "PASSWORD_RESTABLECIDA", f"Con código de acceso del administrador, IP {ip}")
    _sync_bg(bg)
    return {"ok": True}


@router.post("/recuperar/respaldo")
def recuperar_con_respaldo(body: ConfirmarIn, request: Request, bg: BackgroundTasks):
    """Admin sin internet: uno de sus códigos de respaldo (cada uno sirve una sola vez)."""
    ip = _client_ip(request)
    clave = (body.username or "").strip().lower()
    _check_rate_limit(ip, clave)
    db = get_db_session()
    try:
        user = _admin_por_usuario(db, body.username)
        hashes = json.loads(user.recovery_codes or "[]") if user else []
        h = hash_codigo(normalizar_codigo(body.codigo))
        usado = next((x for x in hashes if hmac.compare_digest(x, h)), None)
        if not usado:
            _registrar_fallo(clave)
            raise HTTPException(status_code=400, detail="El código de respaldo no es válido o ya se usó")
        _validar_nueva(body.nueva, user.username)
        hashes.remove(usado)
        user.recovery_codes = json.dumps(hashes)
        cambiar_password_de(user, body.nueva)
        db.commit()
        uid, quedan = user.id, len(hashes)
    finally:
        db.close()
    _auditar(uid, "PASSWORD_RESTABLECIDA", f"Con código de respaldo (quedan {quedan}), IP {ip}")
    _sync_bg(bg)
    return {"ok": True, "codigos_restantes": quedan}


# ── Recuperación en un solo flujo (lo que usa la pantalla) ───────────────────
@router.post("/recuperar/iniciar")
def recuperar_iniciar(body: SolicitarIn, request: Request):
    """Paso 1. Admin: el código SOLO llega a su correo de recuperación (escribir "admin" no basta para
    obtener un código). Empleado (o usuario que no existe, misma respuesta): se lo pide al admin."""
    db = get_db_session()
    try:
        user = _admin_por_usuario(db, body.username)
        existe = user is not None or db.query(Usuario.id).filter(
            Usuario.username == (body.username or "").strip(), Usuario.activo == True).first() is not None
        email = (user.email or "").strip() if user else ""
        agotado = bool(email) and _correos_ultima_hora(db, user.id) >= 3
    finally:
        db.close()
    if not user:
        _check_rate_limit(_client_ip(request))
        if not existe and not cfg._ON_VERCEL:
            raise HTTPException(status_code=404, detail="Ese usuario no existe. Revisa cómo está escrito.")
        return {"tipo": "empleado"}
    if not email:
        _check_rate_limit(_client_ip(request))
        return {"tipo": "admin", "via": "sin_correo"}
    if agotado:
        _check_rate_limit(_client_ip(request))
        return {"tipo": "admin", "via": "correo", "destino": _ocultar_correo(email), "reenviado": False}
    recuperar_solicitar(body, request)        # si no se pudo enviar responde el error (sin internet, etc.)
    return {"tipo": "admin", "via": "correo", "destino": _ocultar_correo(email), "reenviado": True}


@router.post("/recuperar/restablecer")
def recuperar_restablecer(body: ConfirmarIn, request: Request, bg: BackgroundTasks):
    """Paso 2: una sola casilla para cualquier código. Por su forma se sabe cuál es:
    6 dígitos = correo o archivo de la PC · XXXX-XXXX = el que dio el admin · XXXX-XXXX-XX = respaldo."""
    n = normalizar_codigo(body.codigo)
    if len(n) == 6 and n.isdigit():
        return recuperar_confirmar(body, request, bg)
    if len(n) == 8:
        return recuperar_con_codigo_admin(body, request, bg)
    if len(n) == 10:
        return recuperar_con_respaldo(body, request, bg)
    _check_rate_limit(_client_ip(request), (body.username or "").strip().lower())
    raise HTTPException(status_code=400, detail="Revisa el código: no tiene el formato correcto")
