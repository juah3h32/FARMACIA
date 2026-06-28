import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from app.api.routes import auth_routes, products_routes, sales_routes, inventory_routes
from app.api.routes import dashboard_routes, pos_routes, customers_routes, employees_routes
from app.api.routes import admin_routes, reports_routes, cortes_routes, ai_routes, suppliers_routes
from app.api.routes import historial_routes, marketing_routes, config_routes
from app.api.routes import public_routes, app_auth_routes, pedidos_web_routes, catalogo_web_routes
import uvicorn
import app.config as cfg

_logger = logging.getLogger("pos.scheduler")


def _run_cierre_cortes_viejos(motivo: str = "Cierre automático") -> int:
    """Close all open shifts from previous days. Returns count closed. Synchronous."""
    from app.database.connection import get_db_session
    from app.database.models import CortesCaja
    from app.api.routes.cortes_routes import _auto_cerrar_turno
    today = datetime.now().date()
    db = get_db_session()
    try:
        cortes = db.query(CortesCaja).filter(CortesCaja.cerrado_en == None).all()
        cerrados = 0
        for c in cortes:
            if c.abierto_en and c.abierto_en.date() < today:
                _auto_cerrar_turno(db, c, motivo)
                _logger.info(f"Startup/scheduler: closed stale shift id={c.id} user={c.usuario_id}")
                cerrados += 1
        if cerrados:
            db.commit()
            import app.config as _cfg
            if _cfg.TURSO_SYNC:
                from app.database.sync_service import sync_to_turso
                sync_to_turso()
        return cerrados
    except Exception as exc:
        _logger.error(f"_run_cierre_cortes_viejos error: {exc}")
        db.rollback()
        return 0
    finally:
        db.close()


def _run_cierre_todos_hoy(motivo: str = "Cierre automático 21:00") -> int:
    """Close ALL open shifts (including today's) at end of day. Returns count closed."""
    from app.database.connection import get_db_session
    from app.database.models import CortesCaja
    from app.api.routes.cortes_routes import _auto_cerrar_turno
    db = get_db_session()
    try:
        cortes = db.query(CortesCaja).filter(CortesCaja.cerrado_en == None).all()
        cerrados = 0
        for c in cortes:
            _auto_cerrar_turno(db, c, motivo)
            _logger.info(f"Scheduler 21:00: closed shift id={c.id} user={c.usuario_id}")
            cerrados += 1
        if cerrados:
            db.commit()
            import app.config as _cfg
            if _cfg.TURSO_SYNC:
                from app.database.sync_service import sync_to_turso
                sync_to_turso()
        return cerrados
    except Exception as exc:
        _logger.error(f"_run_cierre_todos_hoy error: {exc}")
        db.rollback()
        return 0
    finally:
        db.close()


async def _scheduler_cierre_automatico():
    """
    Background task:
    - On every tick: close open shifts from PREVIOUS days (handles server restart after missed 9pm).
    - At exactly 21:00 each day: close ALL open shifts for end-of-day.
    """
    _eod_done_on: set = set()  # dates where 21:00 close was already executed

    # On startup: close any stale shifts from previous days immediately
    await asyncio.sleep(5)  # brief delay so DB is ready
    stale = _run_cierre_cortes_viejos("Cierre automático — servidor reiniciado")
    if stale:
        _logger.info(f"Startup: closed {stale} stale shift(s) from previous days")

    # If server starts after 21:00 today, mark today's EOD as done so we don't re-close
    _now = datetime.now()
    if _now.hour >= 21:
        _eod_done_on.add(_now.date())
        # But still close any open shifts right now
        _run_cierre_todos_hoy("Cierre automático — servidor iniciado después de 21:00")

    while True:
        await asyncio.sleep(60)
        try:
            now = datetime.now()
            today = now.date()

            # Always close stale shifts from previous days (handles any missed nights)
            _run_cierre_cortes_viejos("Cierre automático — jornada anterior")

            # At 21:00 sharp, close today's shifts too
            if now.hour == 21 and now.minute < 2 and today not in _eod_done_on:
                _eod_done_on.add(today)
                n = _run_cierre_todos_hoy("Cierre automático 21:00")
                if n:
                    _logger.info(f"Scheduler 21:00: closed {n} shift(s)")
        except Exception as exc:
            _logger.error(f"Scheduler tick error: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_scheduler_cierre_automatico())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# Disable interactive docs in production (frozen EXE)
_docs    = "/docs"        if cfg.DEV_MODE else None
_redoc   = "/redoc"       if cfg.DEV_MODE else None
_openapi = "/openapi.json" if cfg.DEV_MODE else None

app = FastAPI(
    title="FarmaciaPOS API",
    description="API REST - Farmacia Eben-Ezer",
    version="1.0.0",
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
    lifespan=lifespan,
)

_cors_origins = ["http://127.0.0.1", "http://localhost"]
_cors_regex = r"https://(.*\.vercel\.app|farmacia-ebenezer\.com|.*\.farmacia-ebenezer\.com)"

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_routes.router,      prefix="/api/auth",       tags=["Auth"])
app.include_router(products_routes.router,  prefix="/api/productos",  tags=["Productos"])
app.include_router(sales_routes.router,     prefix="/api/ventas",     tags=["Ventas"])
app.include_router(inventory_routes.router, prefix="/api/inventario", tags=["Inventario"])
app.include_router(dashboard_routes.router, prefix="/api/dashboard",  tags=["Dashboard"])
app.include_router(pos_routes.router,       prefix="/api/pos",        tags=["POS"])
app.include_router(customers_routes.router, prefix="/api/clientes",   tags=["Clientes"])
app.include_router(employees_routes.router, prefix="/api/empleados",  tags=["Empleados"])
app.include_router(admin_routes.router,     prefix="/api/admin",      tags=["Admin"])
app.include_router(reports_routes.router,   prefix="/api/reportes",   tags=["Reportes"])
app.include_router(cortes_routes.router,    prefix="/api/cortes",     tags=["Cortes"])
app.include_router(ai_routes.router,        prefix="/api/ai",         tags=["AI"])
app.include_router(suppliers_routes.router, prefix="/api/proveedores", tags=["Proveedores"])
app.include_router(historial_routes.router,    prefix="/api/historial",   tags=["Historial"])
app.include_router(marketing_routes.router,    prefix="/api/marketing",   tags=["Marketing"])
app.include_router(config_routes.router,       prefix="/api/config",      tags=["Config"])
# App móvil/web — público (sin auth)
app.include_router(public_routes.router,       prefix="/api/public",      tags=["Público"])
# App móvil/web — clientes autenticados
app.include_router(app_auth_routes.router,     prefix="/api/app/auth",    tags=["App Auth"])
app.include_router(pedidos_web_routes.router,   prefix="/api/app/pedidos",  tags=["App Pedidos"])
app.include_router(catalogo_web_routes.router,  prefix="/api/app/catalogo", tags=["App Catálogo Admin"])


@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": cfg.VERSION, "app": cfg.APP_NAME}


@app.get("/api/dev/stamp")
def dev_stamp():
    if not cfg.DEV_MODE:
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    import hashlib
    try:
        index = _WEB_DIR / "index.html"
        h = hashlib.md5(index.read_bytes()).hexdigest()
    except Exception:
        h = "0"
    return {"v": h, "dev": cfg.DEV_MODE}


_WEB_DIR = cfg.BASE_DIR / "app" / "web"


@app.get("/logo.png")
async def serve_logo_png():
    logo = _WEB_DIR / "logo.png"
    if logo.exists():
        return FileResponse(str(logo), media_type="image/png")
    from fastapi import HTTPException
    raise HTTPException(status_code=404)

@app.get("/logo.svg")
async def serve_logo_svg():
    logo = _WEB_DIR / "logo.svg"
    if logo.exists():
        return FileResponse(str(logo), media_type="image/svg+xml")
    from fastapi import HTTPException
    raise HTTPException(status_code=404)

@app.get("/logo_sistema.webp")
async def serve_logo_sistema():
    logo = _WEB_DIR / "logo_sistema.webp"
    if logo.exists():
        return FileResponse(str(logo), media_type="image/webp")
    from fastapi import HTTPException
    raise HTTPException(status_code=404)


@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    if path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    
    # Intenta servir archivo estático si existe
    file_path = _WEB_DIR / path
    if path and file_path.exists() and file_path.is_file():
        return FileResponse(str(file_path))

    index = _WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "SPA not found"}


def start_api_server():
    # log_config=None avoids uvicorn trying isatty() on stdout=None (windowed EXE)
    uvicorn.run(app, host=cfg.API_HOST, port=cfg.API_PORT,
                log_level="error", log_config=None)
