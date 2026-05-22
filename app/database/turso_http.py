"""
Minimal DB-API 2.0 adapter for Turso (LibSQL) HTTP API.
Uses the /v2/pipeline endpoint — no native binary required.
"""
import requests as _requests

# ── Parameter conversion ──────────────────────────────────────────────────────

def _py_to_turso(v):
    if v is None:                    return {"type": "null",    "value": None}
    if isinstance(v, bool):          return {"type": "integer", "value": "1" if v else "0"}
    if isinstance(v, int):           return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        if v != v:  # NaN
            return {"type": "null", "value": None}
        return {"type": "float", "value": v}  # JSON number, not string
    if isinstance(v, bytes):
        import base64
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _turso_to_py(cell):
    if cell is None:                 return None
    t = cell.get("type", "text")
    v = cell.get("value")
    if t == "null" or v is None:     return None
    if t == "integer":               return int(v)
    if t == "float":                 return float(v)
    if t == "blob":
        import base64
        return base64.b64decode(cell.get("base64", b""))
    return v  # text


# SQL statements that are no-ops in HTTP auto-commit mode
_SKIP_SQL = frozenset([
    "BEGIN", "BEGIN DEFERRED", "BEGIN IMMEDIATE", "BEGIN EXCLUSIVE",
    "COMMIT", "ROLLBACK", "END", "END TRANSACTION",
])

def _is_skip(sql: str) -> bool:
    s = sql.strip().rstrip(";").upper()
    if s in _SKIP_SQL:
        return True
    # Skip all PRAGMA and SAVEPOINT statements
    if s.startswith("PRAGMA") or s.startswith("SAVEPOINT") or s.startswith("RELEASE"):
        return True
    return False


# ── Cursor ────────────────────────────────────────────────────────────────────

class TursoCursor:
    arraysize = 1

    def __init__(self, conn: "TursoConnection"):
        self._conn = conn
        self._rows: list = []
        self._pos: int = 0
        self.description = None
        self.rowcount: int = -1
        self.lastrowid = None

    # ── Execute ───────────────────────────────────────────────────────────────

    def execute(self, sql: str, params=None):
        if _is_skip(sql):
            return self

        # Turso tables already exist — make DDL idempotent
        import re as _re
        sql = _re.sub(
            r'\bCREATE TABLE\b',
            'CREATE TABLE IF NOT EXISTS',
            sql,
            flags=_re.IGNORECASE,
        )
        sql = _re.sub(
            r'\bCREATE (UNIQUE )?INDEX\b',
            lambda m: f'CREATE {m.group(1) or ""}INDEX IF NOT EXISTS',
            sql,
            flags=_re.IGNORECASE,
        )

        args = [_py_to_turso(p) for p in (params or [])]
        result = self._conn._http_execute(sql, args)
        self._load(result)
        return self

    def executemany(self, sql: str, seq_of_params):
        total = 0
        for p in seq_of_params:
            self.execute(sql, p)
            total += max(self.rowcount, 0)
        self.rowcount = total

    def _load(self, result: dict):
        cols = result.get("cols", [])
        rows = result.get("rows", [])
        self.description = (
            [(c["name"], None, None, None, None, None, None) for c in cols]
            if cols else None
        )
        self._rows = [tuple(_turso_to_py(cell) for cell in row) for row in rows]
        self._pos = 0
        self.rowcount = result.get("affected_row_count", len(self._rows))
        lr = result.get("last_insert_rowid")
        self.lastrowid = int(lr) if lr is not None else None

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def fetchone(self):
        if self._pos < len(self._rows):
            row = self._rows[self._pos]
            self._pos += 1
            return row
        return None

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def fetchmany(self, size=None):
        size = size or self.arraysize
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    def close(self): pass
    def setinputsizes(self, *a): pass
    def setoutputsize(self, *a): pass

    def __iter__(self):
        return iter(self.fetchall())


# ── Connection ────────────────────────────────────────────────────────────────

class TursoConnection:
    # sqlite3-compatible attributes SQLAlchemy may touch
    text_factory = str
    row_factory  = None

    def __init__(self, url: str, token: str):
        http = url.replace("libsql://", "https://").replace("wss://", "https://")
        self._url     = http.rstrip("/") + "/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
        }
        self._isolation_level: str | None = None

    # SQLAlchemy may get/set isolation_level on the raw connection
    @property
    def isolation_level(self):
        return self._isolation_level

    @isolation_level.setter
    def isolation_level(self, value):
        self._isolation_level = value  # no-op for Turso

    def cursor(self) -> TursoCursor:
        return TursoCursor(self)

    def _http_execute(self, sql: str, args: list) -> dict:
        payload = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": args}},
                {"type": "close"},
            ]
        }
        resp = _requests.post(self._url, headers=self._headers, json=payload, timeout=30)
        if not resp.ok:
            body = resp.text[:800]
            print(f"[Turso] HTTP {resp.status_code} | SQL: {sql[:300]} | Body: {body}")
            raise DatabaseError(f"HTTP {resp.status_code}: {body}")
        data = resp.json()
        results = data.get("results", [])
        first = results[0] if results else {}
        if first.get("type") == "error":
            msg = first.get("error", {}).get("message", "Turso error")
            print(f"[Turso] SQL error: {msg} | SQL: {sql[:300]}")
            raise DatabaseError(msg)
        return first.get("response", {}).get("result", {"cols": [], "rows": []})

    def create_function(self, *a, **kw): pass  # pysqlite dialect stub
    def commit(self):   pass
    def rollback(self): pass
    def close(self):    pass

    # DB-API 2.0 exceptions on the connection class
    Warning          = Exception
    Error            = Exception
    InterfaceError   = Exception
    DatabaseError    = Exception
    DataError        = Exception
    OperationalError = Exception
    IntegrityError   = Exception
    InternalError    = Exception
    ProgrammingError = Exception
    NotSupportedError= Exception


# ── DB-API 2.0 module-level ───────────────────────────────────────────────────

apilevel    = "2.0"
threadsafety = 1
paramstyle  = "qmark"


class DatabaseError(Exception): pass
class OperationalError(DatabaseError): pass
class IntegrityError(DatabaseError): pass


def connect(url: str, token: str) -> TursoConnection:
    return TursoConnection(url, token)
