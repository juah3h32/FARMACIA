"""
Cuenta de Turso (Platform API) — conecta sucursales a la nube como un POS grande:

- Una sucursal SIEMPRE funciona local desde el primer minuto (SQLite).
- Al conectar la cuenta (token de API de Turso, uno para toda la cuenta), se
  busca la BD de la sucursal (`farmacia-<clave>`); SOLO si no existe se crea,
  se le copia el esquema y se sube todo lo local. Reconectar o reinstalar
  nunca crea otra BD.
- Con el mismo token, cualquier PC de admin descubre sola las demás
  sucursales de la cuenta (cada BD guarda su sucursal_clave/sucursal_nombre
  en configuracion) y las agrega al selector.

El token de la cuenta vive SOLO en esta PC (DATA_DIR/turso_cuenta.json).
API: https://docs.turso.tech/api-reference
"""
import json
import re
import threading
import time

import requests

import app.config as cfg

API = "https://api.turso.tech/v1"
_FILE = cfg.DATA_DIR / "turso_cuenta.json"
_lock = threading.Lock()


class TursoCuentaError(Exception):
    pass


# ── Persistencia local ───────────────────────────────────────────────────────
def cargar() -> dict:
    try:
        return json.loads(_FILE.read_text(encoding="utf-8")) if _FILE.exists() else {}
    except Exception:
        return {}


def _guardar(data: dict) -> None:
    _FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def guardar_cuenta(api_token: str, org: str) -> None:
    d = cargar()
    d.update({"token": api_token, "org": org})
    _guardar(d)


# ── Platform API ─────────────────────────────────────────────────────────────
def _api(method: str, path: str, token: str, **kw) -> requests.Response:
    try:
        r = requests.request(method, API + path, headers={"Authorization": f"Bearer {token}"},
                             timeout=30, **kw)
    except requests.RequestException as e:
        raise TursoCuentaError(f"Sin conexión con Turso: {e}")
    if r.status_code in (401, 403):
        raise TursoCuentaError(
            "Ese token no es el de la CUENTA de Turso. Si copiaste el token de UNA base de datos "
            "(botón 'Create Token' dentro de la base), pega también su URL (libsql://...). "
            "El de la cuenta está en Turso → Settings → API Tokens.")
    return r


def detectar_org(api_token: str) -> str:
    r = _api("GET", "/organizations", api_token)
    if not r.ok:
        raise TursoCuentaError(f"Turso respondió {r.status_code} al listar organizaciones")
    data = r.json()
    orgs = data if isinstance(data, list) else data.get("organizations", [])
    if not orgs:
        raise TursoCuentaError("La cuenta de Turso no tiene organizaciones")
    # Con un token de organización solo se ve esa; con uno personal, la personal primero
    orgs.sort(key=lambda o: o.get("type") != "personal")
    return orgs[0].get("slug") or orgs[0].get("name")


def nombre_db(clave: str) -> str:
    n = re.sub(r"[^a-z0-9-]", "-", f"farmacia-{clave}".lower())
    return re.sub(r"-+", "-", n).strip("-")[:64]


def obtener_db(api_token: str, org: str, nombre: str) -> dict | None:
    r = _api("GET", f"/organizations/{org}/databases/{nombre}", api_token)
    if r.status_code == 404:
        return None
    if not r.ok:
        raise TursoCuentaError(f"Turso respondió {r.status_code} al buscar la BD {nombre}")
    return r.json().get("database")


def crear_db(api_token: str, org: str, nombre: str) -> dict:
    r = _api("GET", f"/organizations/{org}/groups", api_token)
    grupos = r.json().get("groups", []) if r.ok else []
    if not grupos:
        raise TursoCuentaError("La cuenta de Turso no tiene ningún grupo; crea uno en turso.tech (p. ej. 'default')")
    grupo = next((g["name"] for g in grupos if g.get("name") == "default"), grupos[0]["name"])
    r = _api("POST", f"/organizations/{org}/databases", api_token, json={"name": nombre, "group": grupo})
    if r.status_code == 409:  # ya existía (carrera) — usar la existente
        return obtener_db(api_token, org, nombre)
    if not r.ok:
        raise TursoCuentaError(f"No se pudo crear la BD {nombre}: {r.status_code} {r.text[:200]}")
    return r.json().get("database")


def token_db(api_token: str, org: str, nombre: str) -> str:
    r = _api("POST", f"/organizations/{org}/databases/{nombre}/auth/tokens",
             api_token, params={"authorization": "full-access"})
    if not r.ok:
        raise TursoCuentaError(f"No se pudo generar el token de {nombre}: {r.status_code}")
    return r.json()["jwt"]


def listar_dbs(api_token: str, org: str) -> list[dict]:
    r = _api("GET", f"/organizations/{org}/databases", api_token)
    if not r.ok:
        raise TursoCuentaError(f"Turso respondió {r.status_code} al listar bases de datos")
    return r.json().get("databases", [])


def url_de(db: dict) -> str:
    return "libsql://" + (db.get("Hostname") or db.get("hostname"))


# ── SQL contra una BD concreta ───────────────────────────────────────────────
def pipeline(url: str, token: str, stmts: list[dict]) -> list[dict]:
    from app.database.sync_service import _py_to_turso
    endpoint = url.replace("libsql://", "https://").rstrip("/") + "/v2/pipeline"
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out = []
    for i in range(0, max(1, len(stmts)), 200):
        chunk = stmts[i:i + 200]
        body = {"requests": [{"type": "execute", "stmt": {
            "sql": s["sql"], "args": [_py_to_turso(a) for a in s.get("args", [])]}} for s in chunk]
            + [{"type": "close"}]}
        try:
            r = requests.post(endpoint, headers=hdrs, json=body, timeout=60)
        except requests.RequestException as e:
            raise TursoCuentaError(f"Sin conexión con la BD: {e}")
        if not r.ok:
            raise TursoCuentaError(f"La BD respondió {r.status_code}: {r.text[:200]}")
        out += r.json().get("results", [])[:len(chunk)]
    return out


def _valor(res: dict):
    if not res or res.get("type") != "ok":
        return None
    rows = res.get("response", {}).get("result", {}).get("rows", [])
    return rows[0][0].get("value") if rows and rows[0] else None


_NO_ES_POS = "no_es_pos"
_SIN_IDENTIDAD = "sin_identidad"


def leer_identidad(url: str, token: str):
    """{clave, nombre} de la sucursal dueña de esa BD. None si todavía no se
    sabe (sin red, o BD del POS de una versión anterior que aún no guarda su
    sucursal — se vuelve a revisar después). _NO_ES_POS si la BD no es del POS
    (otra base de la cuenta): esa se ignora para siempre."""
    try:
        res = pipeline(url, token, [
            {"sql": "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='productos'"},
            {"sql": "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"},
            {"sql": "SELECT valor FROM configuracion WHERE clave='sucursal_clave'"},
            {"sql": "SELECT valor FROM configuracion WHERE clave='sucursal_nombre'"},
        ])
    except TursoCuentaError:
        return None
    tiene_productos = int(_valor(res[0]) or 0)
    n_tablas = int(_valor(res[1]) or 0)
    if not tiene_productos:
        # Con tablas pero sin productos = otra base de la cuenta. Totalmente
        # vacía = puede ser una sucursal recién creada que aún se está llenando.
        return _NO_ES_POS if n_tablas else None
    clave = _valor(res[2])
    if not clave:
        return _SIN_IDENTIDAD  # BD del POS de una versión anterior (aún no guarda su sucursal)
    return {"clave": str(clave).strip().lower(), "nombre": _valor(res[3]) or str(clave).title()}


def esquema_local_ddl() -> list[dict]:
    """CREATE TABLE/INDEX IF NOT EXISTS de la BD LOCAL real (incluye columnas
    agregadas por migraciones que models.py no trae)."""
    import sqlite3
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
            sql = re.sub(r"^CREATE TABLE (IF NOT EXISTS )?", "CREATE TABLE IF NOT EXISTS ", sql, flags=re.I)
        elif tipo == "index":
            sql = re.sub(r"^CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?",
                         lambda m: f"CREATE {m.group(1) or ''}INDEX IF NOT EXISTS ", sql, flags=re.I)
        else:
            continue
        ddl.append({"sql": sql})
    from app.database.sync_service import _TOMB_DDL
    ddl.append({"sql": _TOMB_DDL})
    return ddl


# ── Descubrir sucursales de la cuenta ────────────────────────────────────────
def sucursales_de_cuenta(api_token: str, org: str, conocidas: dict | None = None,
                         incluir_sin_identidad: bool = False) -> list[dict]:
    """[{clave, nombre, url, token}] de cada BD de la cuenta que pertenezca a una
    sucursal del POS. `conocidas` = {url: token} ya guardados, para no generar
    un token nuevo cada vez."""
    conocidas = conocidas or {}
    d = cargar()
    ignoradas = set(d.get("ignoradas", []))
    out = []
    for db in listar_dbs(api_token, org):
        nombre = db.get("Name") or db.get("name")
        if not nombre or nombre in ignoradas:
            continue
        url = url_de(db)
        tok = conocidas.get(url) or token_db(api_token, org, nombre)
        ident = leer_identidad(url, tok)
        if ident == _NO_ES_POS:
            ignoradas.add(nombre)  # no es del POS: no volver a generarle token
            continue
        if ident == _SIN_IDENTIDAD and incluir_sin_identidad:
            # La BD de siempre (la matriz) antes de actualizar: se ofrece como Matriz
            out.append({"clave": "matriz", "nombre": f"Matriz ({nombre})", "url": url, "token": tok, "db": nombre})
            continue
        if not isinstance(ident, dict):
            continue  # sin identidad todavía (versión vieja) o sin red — reintentar después
        out.append({**ident, "url": url, "token": tok, "db": nombre})
    d["ignoradas"] = sorted(ignoradas)
    _guardar(d)
    return out


_ultimo_descubrimiento = 0.0


def descubrir_y_registrar(forzar: bool = False) -> int:
    """Agrega al selector (sucursales.json) las sucursales de la cuenta que esta
    PC aún no conoce. Throttled a 1 vez cada 5 min salvo `forzar`."""
    global _ultimo_descubrimiento
    d = cargar()
    if not d.get("token") or not d.get("org"):
        return 0
    with _lock:
        if not forzar and time.time() - _ultimo_descubrimiento < 300:
            return 0
        _ultimo_descubrimiento = time.time()
        from app.database import sucursales as suc
        registradas = suc.listar()
        conocidas = {s["url"]: s["token"] for s in registradas}
        propia = (cfg.TURSO_DATABASE_URL or "").rstrip("/")
        nuevas = 0
        for s in sucursales_de_cuenta(d["token"], d["org"], conocidas):
            if s["clave"] == cfg.SUCURSAL_CLAVE or s["url"].rstrip("/") == propia:
                continue
            previa = next((r for r in registradas if r["clave"] == s["clave"]), None)
            if previa and previa["url"] == s["url"] and previa["nombre"] == s["nombre"]:
                continue
            suc.registrar(s["clave"], s["nombre"], s["url"], s["token"])
            nuevas += 1
        return nuevas


# ── Conectar ESTA sucursal a la nube ─────────────────────────────────────────
def _con_reintentos(fn, intentos: int = 10, espera: float = 2.0):
    """Una BD recién creada tarda unos segundos en responder (DNS/arranque)."""
    ultimo = None
    for _ in range(intentos):
        try:
            return fn()
        except TursoCuentaError as e:
            ultimo = e
            time.sleep(espera)
    raise ultimo


def conectar_esta_sucursal(api_token: str, org: str | None = None, progreso=print) -> dict:
    """Busca la BD de esta sucursal en la cuenta; si no existe la crea (UNA sola
    vez — reconectar o reinstalar reutiliza la misma), le copia el esquema, sube
    todo lo que la sucursal ya tenía en local y deja la sincronización activa."""
    from app.database import sync_service as S
    api_token = api_token.strip()
    progreso("Verificando la cuenta de Turso…")
    org = (org or "").strip() or detectar_org(api_token)
    guardar_cuenta(api_token, org)

    # PC que ya sincroniza con su BD (p. ej. la matriz, conectada con URL/token
    # a mano): no se crea nada, solo se guarda la cuenta para descubrir sucursales.
    if cfg.SYNC_MODE == "turso" and cfg.TURSO_DATABASE_URL and cfg.TURSO_AUTH_TOKEN:
        ident = leer_identidad(cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN)
        if isinstance(ident, dict) and ident["clave"] != cfg.SUCURSAL_CLAVE:
            raise TursoCuentaError(f"La BD configurada es de la sucursal '{ident['clave']}', no de esta PC")
        progreso("Buscando otras sucursales…")
        nuevas = descubrir_y_registrar(forzar=True)
        return {"ok": True, "accion": "ya_conectada", "org": org, "sucursales_nuevas": nuevas}

    nombre = nombre_db(cfg.SUCURSAL_CLAVE)
    progreso(f"Buscando la base de datos de esta sucursal ({nombre})…")
    db = obtener_db(api_token, org, nombre)
    creada = db is None
    if creada:
        progreso("No existe todavía — creando la base de datos en la nube…")
        db = crear_db(api_token, org, nombre)
    url = url_de(db)
    tok = token_db(api_token, org, nombre)

    if not creada:
        ident = leer_identidad(url, tok)
        if isinstance(ident, dict) and ident["clave"] != cfg.SUCURSAL_CLAVE:
            raise TursoCuentaError(f"La BD {nombre} ya pertenece a la sucursal '{ident['clave']}'")

    progreso("Preparando tablas en la nube…")
    _con_reintentos(lambda: pipeline(url, tok, esquema_local_ddl()))

    # Credenciales de la BD de esta sucursal + modo nube (sin perder la sucursal de setup.json)
    (cfg.DATA_DIR / "turso_url.key").write_text(url, encoding="utf-8")
    (cfg.DATA_DIR / "turso.key").write_text(tok, encoding="utf-8")
    cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN = url, tok
    setup = cfg._load_setup()
    setup["sync_mode"] = "turso"
    cfg.SETUP_FILE.write_text(json.dumps(setup), encoding="utf-8")
    cfg.reload_setup()

    progreso("Subiendo inventario, ventas y caja de esta sucursal…")
    with S._lock:
        S._watermarks.clear()
        S._ts_watermarks.clear()
        S._sucursal_ok = False
    S.sync_to_turso()
    S.sync_from_turso()
    S.asegurar_background_sync()

    progreso("Buscando otras sucursales de la cuenta…")
    try:
        nuevas = descubrir_y_registrar(forzar=True)
    except TursoCuentaError:
        nuevas = 0
    return {"ok": True, "accion": "creada" if creada else "vinculada", "db": nombre,
            "org": org, "sucursales_nuevas": nuevas}


def unir_caja_a_sucursal(suc: dict, api_token: str, org: str, progreso=print) -> None:
    """Instalación nueva como OTRA caja de una sucursal que ya está en la nube:
    guarda la cuenta y la BD de esa sucursal y baja su inventario, ventas y
    usuarios (sus cajeros — nunca los de otra sucursal)."""
    from app.database import sync_service as S
    from app.database.connection import init_db, get_db
    from app.database.models import Usuario
    if org:  # con token de la cuenta (no con el token de una sola base)
        guardar_cuenta(api_token, org)
    (cfg.DATA_DIR / "turso_url.key").write_text(suc["url"], encoding="utf-8")
    (cfg.DATA_DIR / "turso.key").write_text(suc["token"], encoding="utf-8")
    cfg.TURSO_DATABASE_URL, cfg.TURSO_AUTH_TOKEN = suc["url"], suc["token"]
    setup = cfg._load_setup()
    setup.update({"sync_mode": "turso", "sucursal": {"clave": suc["clave"], "nombre": suc["nombre"]}})
    cfg.SETUP_FILE.write_text(json.dumps(setup), encoding="utf-8")
    cfg.reload_setup()
    progreso(f"Preparando caja de Sucursal {suc['nombre']}...")
    init_db()
    # Sin las cuentas por defecto recién sembradas: admin y cajeros vienen de la
    # BD de ESTA sucursal en la nube.
    with get_db() as db:
        db.query(Usuario).delete()
    progreso("Descargando inventario, ventas y cajeros...")
    S.import_from_turso()
    progreso("Sincronizando cambios recientes...")
    S.sync_from_turso()


def sucursal_por_token_de_bd(url: str, token: str) -> dict:
    """Alternativa sin token de cuenta: URL + token de UNA base de datos (el que
    da el botón 'Create Token' de esa base en turso.tech)."""
    url = url.strip()
    if not url.startswith(("libsql://", "https://", "http://127.0.0.1", "http://localhost")):
        raise TursoCuentaError("La URL debe empezar con libsql:// (cópiala de 'Database URL' en Turso)")
    ident = leer_identidad(url, token.strip())
    nombre_bd = url.split("://", 1)[-1].split(".")[0]
    if ident is None:
        raise TursoCuentaError("No se pudo leer esa base de datos: revisa que la URL y el token sean de la misma base")
    if ident == _NO_ES_POS:
        raise TursoCuentaError("Esa base de datos no es del punto de venta")
    if ident == _SIN_IDENTIDAD:
        return {"clave": "matriz", "nombre": f"Matriz ({nombre_bd})", "url": url, "token": token.strip(), "db": nombre_bd}
    return {**ident, "url": url, "token": token.strip(), "db": nombre_bd}
