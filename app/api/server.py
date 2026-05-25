from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pathlib import Path
from app.api.routes import auth_routes, products_routes, sales_routes, inventory_routes
from app.api.routes import dashboard_routes, pos_routes, customers_routes, employees_routes
from app.api.routes import admin_routes, reports_routes, cortes_routes
import uvicorn
import app.config as cfg

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
)

_cors_origins = ["http://127.0.0.1", "http://localhost"]
# En Vercel el frontend es same-origin, pero permitir *.vercel.app para previews
_cors_regex = r"https://.*\.vercel\.app" if cfg._ON_VERCEL else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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
async def serve_logo():
    logo = _WEB_DIR / "logo.png"
    if logo.exists():
        return FileResponse(str(logo), media_type="image/png")
    from fastapi import HTTPException
    raise HTTPException(status_code=404)


@app.get("/")
@app.get("/{path:path}")
async def serve_spa(path: str = ""):
    if path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404)
    index = _WEB_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"error": "SPA not found"}


def start_api_server():
    # log_config=None avoids uvicorn trying isatty() on stdout=None (windowed EXE)
    uvicorn.run(app, host=cfg.API_HOST, port=cfg.API_PORT,
                log_level="error", log_config=None)
