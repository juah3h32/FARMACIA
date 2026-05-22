from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from app.database.connection import get_db_session
from app.database.models import Usuario
from app.auth.auth_service import verify_password, create_api_token, verify_api_token
import time, threading
from collections import defaultdict

router = APIRouter()
security = HTTPBearer()

# ── Rate limiting: max 10 failed attempts per IP in 5 minutes ─────────────────
_attempts: dict[str, list] = defaultdict(list)
_attempts_lock = threading.Lock()

def _check_rate_limit(ip: str):
    now = time.time()
    with _attempts_lock:
        recent = [t for t in _attempts[ip] if now - t < 300]
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera 5 minutos.")
        recent.append(now)
        _attempts[ip] = recent

def _clear_attempts(ip: str):
    with _attempts_lock:
        _attempts.pop(ip, None)


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


def get_current_api_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = verify_api_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o expirado")
    return payload


@router.post("/login", response_model=TokenResponse)
def api_login(body: LoginRequest, request: Request):
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)
    db = get_db_session()
    try:
        user = db.query(Usuario).filter(
            Usuario.username == body.username,
            Usuario.activo == True
        ).first()
        if not user or not verify_password(body.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")
        _clear_attempts(ip)  # reset on success
        token = create_api_token(user.id, user.username, user.nombre, user.rol.value)
        return TokenResponse(
            access_token=token,
            token_type="bearer",
            user_id=user.id,
            username=user.username,
            nombre=user.nombre,
            rol=user.rol.value,
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
        return {"id": user.id, "username": user.username, "nombre": user.nombre, "rol": user.rol.value}
    finally:
        db.close()
