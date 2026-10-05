"""Sucursales que esta PC puede administrar (selector del admin). Siempre usa la
BD LOCAL y el registro local sucursales.json — ver app/database/sucursales.py."""
import sqlite3

import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import app.config as cfg
from app.api.routes.auth_routes import get_current_api_user
from app.database import sucursales as suc

router = APIRouter()


def _admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")


def _pipeline(url: str, token: str, stmts: list[dict]) -> list[dict]:
    """Ejecuta sentencias en la BD de Turso de una sucursal (pipeline HTTP)."""
    from app.database.sync_service import _py_to_turso
    endpoint = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resultados = []
    for i in range(0, max(1, len(stmts)), 200):
        chunk = stmts[i:i + 200]
        body = {"requests": [{"type": "execute", "stmt": {
            "sql": s["sql"], "args": [_py_to_turso(a) for a in s.get("args", [])]}} for s in chunk]
            + [{"type": "close"}]}
        r = requests.post(endpoint, headers=hdrs, json=body, timeout=60)
        if r.status_code in (401, 403):
            raise HTTPException(status_code=400, detail="Token de Turso inválido para esa base de datos")
        if not r.ok:
            raise HTTPException(status_code=400, detail=f"Turso respondió {r.status_code}: {r.text[:200]}")
        resultados += r.json().get("results", [])[:len(chunk)]
    return resultados


def _valor(res: dict):
    rows = res.get("response", {}).get("result", {}).get("rows", [])
    return rows[0][0].get("value") if rows and rows[0] else None


def _nombre_local() -> str:
    from app.database.connection import SessionLocal
    from app.database.models import Configuracion
    db = SessionLocal()
    try:
        row = db.query(Configuracion).filter(Configuracion.clave == "sucursal_nombre").first()
        return (row.valor if row and row.valor else "Matriz")
    finally:
        db.close()


@router.get("/")
def listar(payload: dict = Depends(get_current_api_user)):
    """La sucursal de esta PC primero + las registradas. Nunca devuelve tokens."""
    _admin(payload)
    # Descubrir en segundo plano sucursales nuevas de la cuenta de Turso (si esta
    # PC tiene la cuenta conectada) — aparecen solas en el selector en la
    # siguiente consulta, sin copiar URLs ni tokens a mano. Throttled a 5 min.
    import threading
    from app.services import turso_cuenta
    def _bg():
        try:
            turso_cuenta.descubrir_y_registrar()
        except Exception as e:
            print(f"[Sucursales] descubrir: {e}")
    threading.Thread(target=_bg, daemon=True, name="DescubrirSucursales").start()
    return [{"clave": cfg.SUCURSAL_CLAVE, "nombre": _nombre_local(), "local": True}] + [
        {"clave": s["clave"], "nombre": s["nombre"], "local": False}
        for s in suc.listar() if s["clave"] != cfg.SUCURSAL_CLAVE
    ]


class SucursalIn(BaseModel):
    nombre: str
    url: str
    token: str
    direccion: str = ""


@router.post("/")
def registrar(body: SucursalIn, payload: dict = Depends(get_current_api_user)):
    """Registra otra sucursal (URL + token de SU base de datos en Turso). Prueba
    la conexión y que la BD no sea la de esta misma sucursal."""
    _admin(payload)
    nombre = body.nombre.strip()
    clave = suc.normalizar_clave(nombre)
    url, token = body.url.strip(), body.token.strip()
    if not clave or not url.startswith(("libsql://", "https://", "http://127.0.0.1", "http://localhost")) or not token:
        raise HTTPException(status_code=400, detail="Faltan nombre, URL (libsql://...) o token")
    if clave == cfg.SUCURSAL_CLAVE:
        raise HTTPException(status_code=400, detail="Ese nombre es el de la sucursal de esta PC")
    if url.rstrip("/") == (cfg.TURSO_DATABASE_URL or "").rstrip("/"):
        raise HTTPException(status_code=400, detail="Esa URL es la base de datos de ESTA sucursal — cada sucursal necesita la suya")
    res = _pipeline(url, token, [
        {"sql": "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='productos'"},
        {"sql": "SELECT valor FROM configuracion WHERE clave='sucursal_clave'"},
    ])
    tiene_tablas = bool(int(_valor(res[0]) or 0)) if res and res[0].get("type") == "ok" else False
    clave_nube = _valor(res[1]) if len(res) > 1 and res[1].get("type") == "ok" else None
    if clave_nube and clave_nube != clave:
        raise HTTPException(status_code=400, detail=f"Esa base de datos ya pertenece a la sucursal '{clave_nube}'")
    suc.registrar(clave, nombre, url, token)
    return {"ok": True, "clave": clave, "nombre": nombre, "inicializada": tiene_tablas and bool(clave_nube)}


@router.delete("/{clave}")
def quitar(clave: str, payload: dict = Depends(get_current_api_user)):
    """Solo la quita del selector de esta PC — no borra nada de su base de datos."""
    _admin(payload)
    suc.eliminar(clave)
    return {"ok": True}


# Tablas que una sucursal nueva hereda de esta (catálogo y administradores). Ventas,
# caja, lotes y movimientos NO: cada sucursal empieza con su propio historial.
_COPIAR = ["categorias", "proveedores", "usuarios", "productos"]
_CONFIG_COPIAR = ("farmacia_nombre", "farmacia_rfc", "tasa_iva", "stock_minimo_alerta",
                  "dias_vencimiento_alerta", "pesos_por_punto", "purge_password_hash")


class InicializarIn(BaseModel):
    direccion: str = ""
    telefono: str = ""


@router.post("/{clave}/inicializar")
def inicializar(clave: str, body: InicializarIn, payload: dict = Depends(get_current_api_user)):
    """Prepara la BD VACÍA de una sucursal nueva: crea todas las tablas, copia el
    catálogo de productos (con existencias en 0 — cada sucursal tiene su propio
    inventario), categorías, proveedores y usuarios, y la marca con su clave.
    Se niega si esa BD ya tiene productos o ventas."""
    _admin(payload)
    s = suc.obtener(clave)
    if not s:
        raise HTTPException(status_code=404, detail="Sucursal no registrada en esta PC")

    # Esquema copiado de la BD LOCAL (no de models.py): incluye las columnas que
    # se agregaron después vía migraciones (ALTER TABLE) y que el modelo no trae.
    import re as _re
    lc = sqlite3.connect(str(cfg.DB_PATH))
    try:
        esquema = lc.execute(
            "SELECT type, sql FROM sqlite_master WHERE sql IS NOT NULL "
            "AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END"
        ).fetchall()
    finally:
        lc.close()
    ddl = []
    for tipo, sql in esquema:
        if tipo == "table":
            sql = _re.sub(r"^CREATE TABLE (IF NOT EXISTS )?", "CREATE TABLE IF NOT EXISTS ", sql, flags=_re.I)
        elif tipo == "index":
            sql = _re.sub(r"^CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?", lambda m: f"CREATE {m.group(1) or ''}INDEX IF NOT EXISTS ", sql, flags=_re.I)
        else:
            continue
        ddl.append({"sql": sql})
    from app.database.sync_service import _TOMB_DDL
    ddl.append({"sql": _TOMB_DDL})
    _pipeline(s["url"], s["token"], ddl)

    chequeo = _pipeline(s["url"], s["token"], [
        {"sql": "SELECT COUNT(*) FROM productos"}, {"sql": "SELECT COUNT(*) FROM ventas"}])
    if int(_valor(chequeo[0]) or 0) or int(_valor(chequeo[1]) or 0):
        raise HTTPException(status_code=409, detail="Esa base de datos ya tiene productos o ventas — no se inicializa encima")

    lconn = sqlite3.connect(str(cfg.DB_PATH))
    lconn.row_factory = sqlite3.Row
    try:
        stmts = []
        for tabla in _COPIAR:
            # Usuarios: solo administradores — cada sucursal da de alta SUS
            # cajeros; un cajero de una sucursal no debe poder entrar a otra.
            filtro = " WHERE rol = 'admin'" if tabla == "usuarios" else ""
            filas = lconn.execute(f"SELECT * FROM {tabla}{filtro}").fetchall()
            if not filas:
                continue
            cols = list(filas[0].keys())
            sql = f"INSERT OR IGNORE INTO {tabla} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
            for f in filas:
                vals = dict(f)
                if tabla == "productos":
                    vals["stock"] = 0
                    if "piezas_sueltas" in vals:
                        vals["piezas_sueltas"] = 0
                stmts.append({"sql": sql, "args": [vals[c] for c in cols]})
        cfg_rows = lconn.execute(
            f"SELECT clave, valor FROM configuracion WHERE clave IN ({', '.join('?' for _ in _CONFIG_COPIAR)})",
            _CONFIG_COPIAR).fetchall()
    finally:
        lconn.close()
    propios = {"sucursal_clave": clave, "sucursal_nombre": s["nombre"],
               "farmacia_direccion": body.direccion.strip(), "farmacia_telefono": body.telefono.strip()}
    for k, v in list((r["clave"], r["valor"]) for r in cfg_rows) + list(propios.items()):
        stmts.append({"sql": "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
                             "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor", "args": [k, v]})
    res = _pipeline(s["url"], s["token"], stmts)
    errores = [r for r in res if r.get("type") == "error"]
    return {"ok": not errores, "copiados": len(stmts) - len(errores), "errores": len(errores),
            "detalle_errores": [e.get("error", {}).get("message", "") for e in errores[:5]]}


@router.post("/{clave}/asignar-esta-pc")
def asignar_esta_pc(clave: str, payload: dict = Depends(get_current_api_user)):
    """Convierte ESTA PC en una caja de otra sucursal (p. ej. la PC nueva que va
    a López Mateos): guarda la URL/token de su BD, marca la sucursal en
    setup.json y, al reiniciar, cambia la BD local por la de esa sucursal.
    Solo se permite si esta PC todavía no tiene ventas — nunca se tira historial."""
    _admin(payload)
    if cfg._ON_VERCEL:
        raise HTTPException(status_code=400, detail="No disponible en la versión web")
    s = suc.obtener(clave)
    if not s:
        raise HTTPException(status_code=404, detail="Primero registra esa sucursal en esta PC")
    lc = sqlite3.connect(str(cfg.DB_PATH))
    try:
        n_ventas = lc.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
    finally:
        lc.close()
    if n_ventas:
        raise HTTPException(status_code=409, detail=(
            f"Esta PC ya tiene {n_ventas} ventas de la sucursal actual — no se puede convertir. "
            "Usa una PC nueva para la otra sucursal, o adminístrala desde el selector de arriba."))
    import json as _json
    (cfg.DATA_DIR / "turso_url.key").write_text(s["url"], encoding="utf-8")
    (cfg.DATA_DIR / "turso.key").write_text(s["token"], encoding="utf-8")
    setup = cfg._load_setup()
    setup["sync_mode"] = "turso"
    setup["sucursal"] = {"clave": clave, "nombre": s["nombre"]}
    cfg.SETUP_FILE.write_text(_json.dumps(setup), encoding="utf-8")
    (cfg.DATA_DIR / "cambiar_sucursal.pendiente").write_text(clave, encoding="utf-8")
    return {"ok": True, "reiniciar": True,
            "mensaje": f"Listo: esta PC será Sucursal {s['nombre']}. Cierra y vuelve a abrir el programa."}


# ── Nube: conectar ESTA sucursal con la cuenta de Turso ─────────────────────
@router.get("/nube")
def estado_nube(payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    from app.services import turso_cuenta
    d = turso_cuenta.cargar()
    return {
        "sucursal": cfg.SUCURSAL_CLAVE,
        "sincronizando": bool(cfg.TURSO_SYNC and cfg.TURSO_DATABASE_URL),
        "bd": (cfg.TURSO_DATABASE_URL or "").replace("libsql://", "").split(".")[0] or None,
        "cuenta_conectada": bool(d.get("token")),
        "org": d.get("org"),
    }


class ConectarNubeIn(BaseModel):
    api_token: str
    org: str = ""


@router.post("/nube/conectar")
def conectar_nube(body: ConectarNubeIn, payload: dict = Depends(get_current_api_user)):
    """Conecta esta sucursal a la cuenta de Turso: encuentra su BD o la crea UNA
    sola vez, sube todo lo local y deja la sincronización activa. Sirve también
    en una PC ya conectada (solo guarda la cuenta para descubrir sucursales)."""
    _admin(payload)
    if cfg._ON_VERCEL:
        raise HTTPException(status_code=400, detail="No disponible en la versión web")
    if not body.api_token.strip():
        raise HTTPException(status_code=400, detail="Pega el token de API de tu cuenta de Turso")
    from app.services import turso_cuenta
    try:
        return turso_cuenta.conectar_esta_sucursal(body.api_token, body.org)
    except turso_cuenta.TursoCuentaError as e:
        raise HTTPException(status_code=400, detail=str(e))
