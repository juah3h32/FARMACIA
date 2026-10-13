"""
Marketing → Video promocional (solo admin, solo en la versión de escritorio).
Arma un video 1920x1080 para la pantalla de la farmacia con productos del inventario.
"""
import io
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

import app.config as cfg
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()


def _admin(payload: dict):
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    if cfg._ON_VERCEL:
        raise HTTPException(status_code=400, detail="El video promocional solo está disponible en la versión de escritorio.")


def _svc():
    try:
        from app.services.video_promo import servicio
        return servicio
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Falta una librería para el video: {e}")


def _productos(ids):
    from app.database.connection import get_db_session
    from app.database.models import Producto
    db = get_db_session()
    try:
        prods = db.query(Producto).filter(Producto.id.in_(list(ids))).all() if ids else []
        for p in prods: db.expunge(p)
        return {p.id: p for p in prods}
    finally:
        db.close()


# ── logo de la farmacia (para la barra lateral; no es información privada) ──
@router.get("/logo")
def logo():
    from app.services.video_promo.servicio import LOGO
    if not LOGO.exists():
        raise HTTPException(status_code=404, detail="Sin logo")
    return FileResponse(str(LOGO), media_type="image/png")


# ── estado del proyecto ───────────────────────────────────────────────────────
@router.get("")
def estado(payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    s = _svc()
    proy = s.cargar_proyecto()
    prods = _productos({it["producto_id"] for it in proy["items"]})
    cache = s.ia_cache()
    items = []
    for it in proy["items"]:
        p = prods.get(it["producto_id"])
        if not p:
            continue                       # producto eliminado del inventario
        c = cache.get(str(p.id))
        origen = "ia" if c else "inventario"          # sin IA: descripción armada con los datos del inventario
        c = c or s.texto_inventario(p)
        items.append(dict(it, nombre=p.nombre, precio=p.precio_venta, imagen_url=p.imagen_url or "",
                          tiene_foto=bool(p.imagen_url), activo=bool(p.activo),
                          ia_desc=c.get("desc", ""), ia_bens=c.get("bens", ["", "", ""]), ia_origen=origen,
                          precio_tachado=p.precio_tachado, precio_pieza=p.precio_pieza if p.venta_fraccionada else None))
    return {"config": proy["config"], "items": items, "estilos": s.ESTILOS,
            "ia_lista": bool(getattr(cfg, "ANTHROPIC_API_KEY", "")), "tarea": s.estado_tarea(),
            "drive_sugerido": s.drive_sugerido()}


class TerminalIn(BaseModel):
    enabled: bool = True
    posicion: str = "inicio"          # inicio | final | intercalado
    cada: int = 3
    diseno: str = "terminal"           # diseño de la vista previa: terminal | persona | abanico | contacto
    disenos: list[str] = []            # diseños que salen en el video (uno o varios)
    titulo: str = ""
    subtitulo: str = ""
    marcas: list[str] = []
    chips: list[str] = []


class ConfigIn(BaseModel):
    seconds: int = 8
    intro: bool = True
    quality: str = "Alta"
    repeat: int = 1
    default_style: str = "destacado"
    footer_left: str = ""
    footer_right: str = ""
    out_dir: str = ""
    drive_dir: Optional[str] = None         # None = no cambiar; "" = no copiar a Drive
    terminal: Optional[TerminalIn] = None


def _terminal_limpio(t: TerminalIn) -> dict:
    from app.services.video_promo.estilos import MARCAS, DISENOS_TERMINAL
    d = t.dict()
    if d["diseno"] not in DISENOS_TERMINAL: d["diseno"] = "terminal"
    d["disenos"] = [x for x in dict.fromkeys(d["disenos"]) if x in DISENOS_TERMINAL] or [d["diseno"]]
    if d["posicion"] not in ("inicio", "final", "intercalado"): d["posicion"] = "inicio"
    d["cada"] = max(1, min(20, d["cada"]))
    d["titulo"] = d["titulo"].strip()[:60] or "Aceptamos todas las tarjetas"
    d["subtitulo"] = d["subtitulo"].strip()[:120]
    d["marcas"] = [m for m in d["marcas"] if m in MARCAS]
    d["chips"] = [c.strip()[:20] for c in d["chips"] if c.strip()][:3]
    return d


@router.put("/config")
def guardar_config(body: ConfigIn, payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    c = body.dict()
    c["seconds"] = max(4, min(15, c["seconds"]))
    c["repeat"] = max(1, min(10, c["repeat"]))
    if c["quality"] not in ("Ligera", "Alta", "Máxima"): c["quality"] = "Alta"
    if c["default_style"] not in _svc().ESTILOS: c["default_style"] = "destacado"
    if not c["out_dir"]: c.pop("out_dir")
    if c["drive_dir"] is None: c.pop("drive_dir")
    else: c["drive_dir"] = c["drive_dir"].strip().strip('"')
    if body.terminal is None: c.pop("terminal")
    else: c["terminal"] = _terminal_limpio(body.terminal)
    return _svc().guardar_proyecto(config=c)["config"]


class ItemIn(BaseModel):
    producto_id: int
    style: str = "destacado"
    enabled: bool = True
    desc: str = ""
    bens: list[str] = ["", "", ""]
    tag: str = ""
    old_price: str = ""
    show_piece: bool = True
    unit: str = ""


@router.put("/items")
def guardar_items(items: list[ItemIn], payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    _svc().guardar_proyecto(items=[i.dict() for i in items])
    return {"ok": True}


# ── IA: descripción corta y beneficios (una sola vez por producto) ────────────
@router.post("/ia/{producto_id}")
def descripcion_ia(producto_id: int, forzar: bool = False, payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    s = _svc()
    p = _productos({producto_id}).get(producto_id)
    if not p:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    from app.services.video_promo.ia import IAError
    try:
        r, nuevo = s.texto_ia(p, getattr(cfg, "ANTHROPIC_API_KEY", ""), forzar)
    except IAError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"desc": r["desc"], "bens": r["bens"], "uso_ia": nuevo}


# ── vista previa ──────────────────────────────────────────────────────────────
class PreviewIn(BaseModel):
    item: ItemIn
    t: float = 4.0


@router.post("/vista-previa")
def vista_previa(body: PreviewIn, payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    s = _svc()
    p = _productos({body.item.producto_id}).get(body.item.producto_id)
    if not p:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    try:
        img = s.vista_previa(p, body.item.dict(), s.cargar_proyecto()["config"], body.t)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo dibujar la vista previa: {e}")
    buf = io.BytesIO()
    img.resize((960, 540)).save(buf, "JPEG", quality=88)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


class PreviewTerminalIn(BaseModel):
    terminal: TerminalIn
    t: float = 4.0


@router.post("/vista-previa-terminal")
def vista_previa_terminal(body: PreviewTerminalIn, payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    s = _svc()
    try:
        img = s.vista_previa_terminal(_terminal_limpio(body.terminal), s.cargar_proyecto()["config"], body.t)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo dibujar la vista previa: {e}")
    buf = io.BytesIO()
    img.resize((960, 540)).save(buf, "JPEG", quality=88)
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/jpeg")


# ── generar video ─────────────────────────────────────────────────────────────
class GenerarIn(BaseModel):
    nombre: Optional[str] = None
    solo_terminal: bool = False      # video solo con el anuncio de pago con tarjeta


@router.post("/generar")
def generar(body: GenerarIn, payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    s = _svc()
    proy = s.cargar_proyecto()
    if body.solo_terminal:
        try:
            out = s.generar(s.anuncios_terminal(proy["config"]["terminal"]), proy["config"],
                            body.nombre or "PAGO_CON_TARJETA")
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        return {"archivo": out}
    items = [it for it in proy["items"] if it.get("enabled", True)]
    if not items and not proy["config"]["terminal"].get("enabled"):
        raise HTTPException(status_code=400, detail="Agrega al menos un producto al video.")
    prods = _productos({it["producto_id"] for it in items})
    cache = s.ia_cache()
    slides, sin_foto = [], []
    for it in items:
        p = prods.get(it["producto_id"])
        if not p:
            continue
        try:
            sl = s.slide(p, it, cache)
        except Exception:
            sl = None
        if not sl or not sl["file"]:
            sin_foto.append(p.nombre); continue
        slides.append(sl)
    if sin_foto:
        raise HTTPException(status_code=400, detail="Estos productos no tienen foto (agrégala en Inventario o quítalos del video): "
                                                    + ", ".join(sin_foto[:8]))
    slides = s.con_terminal(slides, proy["config"])
    try:
        out = s.generar(slides, proy["config"], body.nombre)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"archivo": out}


@router.get("/progreso")
def progreso(payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    return _svc().estado_tarea()


@router.post("/cancelar")
def cancelar(payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    _svc().cancelar()
    return {"ok": True}


@router.get("/descargar")
def descargar(payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    t = _svc().estado_tarea()
    if t.get("state") != "listo" or not os.path.isfile(t.get("file", "")):
        raise HTTPException(status_code=404, detail="Todavía no hay un video listo.")
    return FileResponse(t["file"], media_type="video/mp4", filename=os.path.basename(t["file"]))


class AbrirIn(BaseModel):
    que: str = "video"     # video | carpeta


@router.post("/abrir")
def abrir(body: AbrirIn, payload: dict = Depends(get_current_api_user)):
    """Abre el video o su carpeta en esta computadora (el POS corre local)."""
    _admin(payload)
    s = _svc()
    t = s.estado_tarea()
    destino = t.get("file") if body.que == "video" else os.path.dirname(t.get("file") or "") or s.cargar_proyecto()["config"]["out_dir"]
    if not destino or not os.path.exists(destino):
        destino = s.cargar_proyecto()["config"]["out_dir"]
        os.makedirs(destino, exist_ok=True)
    try:
        os.startfile(destino)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo abrir: {e}")
    return {"ok": True}


# ── clave de Claude (se guarda igual que las demás integraciones: archivo en DATA_DIR) ──
class ClaveIn(BaseModel):
    api_key: str


@router.put("/clave")
def guardar_clave(body: ClaveIn, payload: dict = Depends(get_current_api_user)):
    _admin(payload)
    k = body.api_key.strip()
    if not k.startswith("sk-ant-"):
        raise HTTPException(status_code=400, detail="La clave de Claude empieza con sk-ant-…")
    (cfg.DATA_DIR / "anthropic.key").write_text(k, encoding="utf-8")
    cfg.ANTHROPIC_API_KEY = k
    return {"ok": True}
