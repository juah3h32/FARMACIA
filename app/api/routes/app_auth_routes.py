"""
Auth para clientes de la app móvil/web (ClienteApp).
Independiente del auth del POS (Usuario/admin).
"""
from fastapi import APIRouter, HTTPException, Depends, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional
from app.database.connection import get_db_session
from app.database.models import ClienteApp
from app.auth.auth_service import hash_password, verify_password, verify_api_token, create_api_token
import time, threading
from collections import defaultdict

router = APIRouter()
security = HTTPBearer()

_attempts: dict[str, list] = defaultdict(list)
_lock = threading.Lock()


def _rate_limit(ip: str):
    now = time.time()
    with _lock:
        recent = [t for t in _attempts[ip] if now - t < 300]
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera 5 minutos.")
        recent.append(now)
        _attempts[ip] = recent


def get_current_cliente_app(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = verify_api_token(credentials.credentials)
    if not payload or payload.get("rol") not in ("cliente_app", "admin_web"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
    return payload


class RegisterIn(BaseModel):
    nombre: str
    email: str
    password: str
    telefono: Optional[str] = None


class LoginIn(BaseModel):
    email: str
    password: str


class GoogleIn(BaseModel):
    google_id: str
    name: str
    email: str
    photo: Optional[str] = None


def _token_response(cliente: ClienteApp) -> dict:
    rol = getattr(cliente, "rol", "cliente_app") or "cliente_app"
    token = create_api_token(
        user_id=cliente.id,
        username=cliente.email,
        nombre=cliente.nombre,
        rol=rol,
    )
    return {
        "success": True,
        "access_token": token,
        "token_type": "bearer",
        "data": {
            "id":       cliente.id,
            "nombre":   cliente.nombre,
            "email":    cliente.email,
            "telefono": cliente.telefono,
            "foto_url": cliente.foto_url,
            "rol":      rol,
        },
    }


@router.post("/register")
def register(body: RegisterIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    _rate_limit(ip)
    db = get_db_session()
    try:
        if db.query(ClienteApp).filter(ClienteApp.email == body.email.lower()).first():
            raise HTTPException(status_code=400, detail="Email ya registrado")
        cliente = ClienteApp(
            nombre=body.nombre.strip(),
            email=body.email.lower().strip(),
            password_hash=hash_password(body.password),
            telefono=body.telefono,
        )
        db.add(cliente)
        db.commit()
        db.refresh(cliente)
        return _token_response(cliente)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/login")
def login(body: LoginIn, request: Request):
    ip = request.client.host if request.client else "unknown"
    _rate_limit(ip)
    db = get_db_session()
    try:
        cliente = db.query(ClienteApp).filter(
            ClienteApp.email == body.email.lower(),
            ClienteApp.activo == True,
        ).first()
        if not cliente or not cliente.password_hash:
            raise HTTPException(status_code=401, detail="Credenciales inválidas")
        if not verify_password(body.password, cliente.password_hash):
            raise HTTPException(status_code=401, detail="Credenciales inválidas")
        return _token_response(cliente)
    finally:
        db.close()


@router.post("/google")
def google_login(body: GoogleIn):
    db = get_db_session()
    try:
        cliente = db.query(ClienteApp).filter(ClienteApp.google_id == body.google_id).first()
        if not cliente:
            # Buscar por email
            cliente = db.query(ClienteApp).filter(ClienteApp.email == body.email.lower()).first()
            if cliente:
                cliente.google_id = body.google_id
                if body.photo:
                    cliente.foto_url = body.photo
            else:
                cliente = ClienteApp(
                    nombre=body.name,
                    email=body.email.lower(),
                    google_id=body.google_id,
                    foto_url=body.photo,
                )
                db.add(cliente)
        db.commit()
        db.refresh(cliente)
        return _token_response(cliente)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.get("/me")
def me(payload: dict = Depends(get_current_cliente_app)):
    db = get_db_session()
    try:
        cliente = db.query(ClienteApp).filter(ClienteApp.id == int(payload["sub"])).first()
        if not cliente:
            raise HTTPException(status_code=404, detail="No encontrado")
        return {
            "success": True,
            "data": {
                "id":       cliente.id,
                "nombre":   cliente.nombre,
                "email":    cliente.email,
                "telefono": cliente.telefono,
                "foto_url": cliente.foto_url,
                "rol":      getattr(cliente, "rol", "cliente_app") or "cliente_app",
            },
        }
    finally:
        db.close()
