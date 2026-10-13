from pathlib import Path
import io
import json
import cloudinary
import cloudinary.uploader
import requests
from PIL import Image
import app.config as cfg


def _configure():
    cloudinary.config(
        cloud_name=cfg.CLOUDINARY_CLOUD_NAME,
        api_key=cfg.CLOUDINARY_API_KEY,
        api_secret=cfg.CLOUDINARY_API_SECRET,
        secure=True,
    )


def _cloudinary_configured() -> bool:
    return bool(cfg.CLOUDINARY_CLOUD_NAME and cfg.CLOUDINARY_API_KEY and cfg.CLOUDINARY_API_SECRET)


# Carpetas locales ordenadas por tipo — DATA_DIR/uploads/imagenes/medicamentos|perfiles.
_LOCAL_SUBDIR = {
    "medicamentos": Path("imagenes") / "medicamentos",
    "perfiles":      Path("imagenes") / "perfiles",
}

# Todas las fotos guardadas en disco (subida directa sin Cloudinary, o respaldo
# descargado de Cloudinary) se adaptan a este cuadrado — así se ven todas del
# mismo tamaño en el catálogo sin importar la foto original que suba cada
# quien, y sobre fondo blanco parejo (ver _fit_white_square).
_STANDARD_SIZE = {"medicamentos": 800, "perfiles": 300}


def _fit_white_square(img: Image.Image, size: int) -> Image.Image:
    """Escala la imagen completa (sin recortar nada del producto) para que
    quepa dentro de un cuadrado size×size sobre fondo blanco, centrada.
    Antes se recortaba al centro para forzar 1:1 — en una foto no cuadrada
    eso podía cortar un borde del producto, muy notorio justo en las fotos
    que ya vienen sin fondo (remove.bg), donde perder un pedazo se ve peor
    que en una con fondo normal. Además deja TODAS las fotos —tengan o no
    fondo removido— sobre el mismo fondo blanco parejo."""
    img = img.convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    offset = ((size - img.width) // 2, (size - img.height) // 2)
    canvas.paste(img, offset)
    return canvas


def _standardize_image_bytes(raw: bytes, size: int) -> bytes | None:
    """Adapta los bytes de una imagen a un cuadrado de `size`×`size` sobre
    fondo blanco (ver _fit_white_square), devueltos ya codificados como JPEG.
    None si `raw` no es una imagen válida (PIL no pudo abrirla) — el llamador
    debe guardar el original tal cual en ese caso, en vez de perder el archivo."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = _fit_white_square(img, size)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=88)
        return out.getvalue()
    except Exception:
        return None


def _save_local(file_path: str, kind: str, filename: str) -> str:
    """Sin Cloudinary (no configurado, o sin conexión al subir) la imagen se
    queda en este equipo — no se ve en las demás cajas/computadoras hasta que
    Cloudinary vuelva a estar disponible."""
    dest_dir = cfg.DATA_DIR / "uploads" / _LOCAL_SUBDIR[kind]
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{filename}.*"):
        old.unlink(missing_ok=True)
    raw = Path(file_path).read_bytes()
    data = _standardize_image_bytes(raw, _STANDARD_SIZE[kind])
    ext = ".jpg" if data is not None else (Path(file_path).suffix or ".jpg")
    (dest_dir / f"{filename}{ext}").write_bytes(data if data is not None else raw)
    return f"/uploads/{_LOCAL_SUBDIR[kind].as_posix()}/{filename}{ext}"


def _delete_local(kind: str, filename: str) -> None:
    dest_dir = cfg.DATA_DIR / "uploads" / _LOCAL_SUBDIR[kind]
    for old in dest_dir.glob(f"{filename}.*"):
        old.unlink(missing_ok=True)


# ── Respaldo local de imágenes ya subidas a Cloudinary ───────────────────────
# Cuando el catálogo llega por sync de Turso a una PC nueva, imagen_url apunta
# a Cloudinary — se ve bien con internet, pero desaparece en cuanto se cae la
# conexión. sync_product_images_locally() descarga esas fotos una sola vez a
# esta misma carpeta (_LOCAL_SUBDIR["medicamentos"]), para que /uploads/producto-local/{id}
# (ver app/api/server.py) pueda servirlas sin depender de Cloudinary.

_MANIFEST_FILENAME = "_image_cache_manifest.json"


def _manifest_path() -> Path:
    return cfg.DATA_DIR / "uploads" / _MANIFEST_FILENAME


def _load_manifest() -> dict:
    p = _manifest_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_manifest(manifest: dict) -> None:
    p = _manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest), encoding="utf-8")


def cache_remote_image(url: str, kind: str, filename: str) -> bool:
    """Descarga una imagen ya alojada en Cloudinary (u otra URL http) y la
    guarda como respaldo local, con el mismo nombre/carpeta que usa la subida
    normal cuando Cloudinary no está disponible. Se recorta/escala igual que
    _save_local para que el respaldo local se vea consistente con el resto."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception:
        return False
    dest_dir = cfg.DATA_DIR / "uploads" / _LOCAL_SUBDIR[kind]
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{filename}.*"):
        old.unlink(missing_ok=True)
    data = _standardize_image_bytes(resp.content, _STANDARD_SIZE[kind])
    ext = ".jpg" if data is not None else (Path(url.split("?")[0]).suffix or ".jpg")
    (dest_dir / f"{filename}{ext}").write_bytes(data if data is not None else resp.content)
    return True


def _pending_image_pairs() -> list[tuple[int, str]]:
    """Productos con foto en Cloudinary cuya URL todavía no coincide con lo
    último descargado localmente — usado tanto para descargar como para
    reportar cuántas faltan (ver /admin/image-sync-status)."""
    from app.database.connection import get_db_session
    from app.database.models import Producto

    db = get_db_session()
    try:
        productos = db.query(Producto.id, Producto.imagen_url).filter(
            Producto.imagen_url.isnot(None), Producto.imagen_url != ""
        ).all()
    finally:
        db.close()

    manifest = _load_manifest()
    pending = []
    for pid, url in productos:
        if not url or not url.startswith("http"):
            continue  # ya es una ruta local (/uploads/...), no hay nada que bajar
        if manifest.get(f"producto_{pid}") != url:
            pending.append((pid, url))
    return pending


def count_pending_images() -> int:
    return len(_pending_image_pairs())


def sync_product_images_locally(progress_cb=None) -> int:
    """Descarga a este equipo las fotos de producto que están en Cloudinary
    pero de las que todavía no tiene copia local (o cuya URL cambió desde la
    última descarga, p. ej. porque se reemplazó la foto en otra PC). Pensado
    para llamarse en segundo plano después de cada sync con Turso — así el
    catálogo sigue mostrando fotos aunque después se pierda la conexión con
    Cloudinary. `progress_cb(done, total)` es opcional, para reportar avance
    en vivo (ver /admin/image-sync-status). Devuelve cuántas se descargaron."""
    pending = _pending_image_pairs()
    manifest = _load_manifest()
    downloaded = 0
    for i, (pid, url) in enumerate(pending):
        filename = f"producto_{pid}"
        if cache_remote_image(url, "medicamentos", filename):
            manifest[filename] = url
            downloaded += 1
            _save_manifest(manifest)  # guardar tras cada foto — si se interrumpe, no repite las ya bajadas
        if progress_cb:
            try:
                progress_cb(i + 1, len(pending))
            except Exception:
                pass
    return downloaded


# ── Cloudinary es la copia maestra de las fotos de producto ──────────────────
# Cada foto vive en Cloudinary con nombre fijo FARMACIA/PRODUCTOS/producto_{id}. Si en otra
# PC se cambia la foto, Cloudinary tiene la versión nueva aunque la fila del producto en esta
# PC tenga una fecha de modificación más reciente (p. ej. por una venta). Por eso la foto NO
# se decide por fechas de la fila: se le pregunta a Cloudinary cuál es la versión vigente.
import re as _re
import time as _time
from datetime import datetime as _dt, timezone as _tz

_PROD_PREFIX = "FARMACIA/PRODUCTOS/producto_"
_last_cloud_check = 0.0
_cloud_cache: dict = {}


def _version(url: str) -> int | None:
    m = _re.search(r"/v(\d+)/", url or "")
    return int(m.group(1)) if m else None


def cloudinary_product_images(max_age: float = 0) -> dict:
    """{producto_id: {"url", "version", "creado"}} de las fotos en Cloudinary (una consulta por
    cada 500 fotos). Con max_age > 0 reusa la última respuesta si es más reciente que eso."""
    global _last_cloud_check, _cloud_cache
    if max_age and _time.time() - _last_cloud_check < max_age:
        return _cloud_cache
    if not _cloudinary_configured():
        return {}
    _configure()
    import cloudinary.api
    out, cursor = {}, None
    while True:
        kw = dict(type="upload", prefix=_PROD_PREFIX, max_results=500)
        if cursor:
            kw["next_cursor"] = cursor
        res = cloudinary.api.resources(**kw)
        for r in res.get("resources", []):
            pid = r["public_id"][len(_PROD_PREFIX):]
            if pid.isdigit():
                creado = r.get("created_at") or ""
                try:
                    ts = _dt.fromisoformat(creado.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = 0
                out[int(pid)] = {"url": r["secure_url"], "version": int(r.get("version") or 0), "creado": ts}
        cursor = res.get("next_cursor")
        if not cursor:
            break
    _cloud_cache, _last_cloud_check = out, _time.time()
    return out


def reconcile_with_cloudinary(max_age: float = 0) -> int:
    """Cloudinary manda: si la foto de un producto en Cloudinary es distinta (otra versión) de la
    que tiene esta PC, esta PC toma la de Cloudinary sin importar fechas. La única excepción es
    una foto guardada aquí sin conexión que sea MÁS nueva que la de Cloudinary (esa se sube
    después con upload_pending_local_images). Devuelve cuántos productos cambiaron."""
    nube = cloudinary_product_images(max_age)
    if not nube:
        return 0
    from app.database.connection import get_db_session
    from app.database.models import Producto
    db = get_db_session()
    cambiados = 0
    try:
        for prod in db.query(Producto).filter(Producto.id.in_(list(nube))).all():
            c = nube[prod.id]
            url = prod.imagen_url or ""
            if url.startswith("http") and _version(url) == c["version"]:
                continue                                   # ya tiene la versión vigente
            local = local_path_for_url(url)
            if local is not None and local.stat().st_mtime > c["creado"]:
                continue                                   # foto local más nueva: se sube después
            prod.imagen_url = c["url"]
            cambiados += 1
        if cambiados:
            db.commit()
    finally:
        db.close()
    return cambiados


def local_path_for_url(url: str) -> Path | None:
    """Ruta en disco de una foto guardada localmente (imagen_url tipo /uploads/imagenes/...)."""
    if not url or url.startswith("http"):
        return None
    p = cfg.DATA_DIR / url.lstrip("/")
    return p if p.is_file() else None


def upload_pending_local_images(progress_cb=None) -> int:
    """Sube a Cloudinary las fotos de producto que solo existen en esta PC (se guardaron
    sin conexión o sin Cloudinary) y actualiza el producto con la URL de Cloudinary — así
    la foto queda en la nube para las demás cajas y Cloudinary vuelve a ser la copia maestra.
    Devuelve cuántas se subieron. Sin Cloudinary configurado o sin internet no hace nada."""
    if not _cloudinary_configured():
        return 0
    import shutil
    import tempfile
    from app.database.connection import get_db_session
    from app.database.models import Producto

    db = get_db_session()
    try:
        locales = db.query(Producto).filter(Producto.imagen_url.like("/uploads/%")).all()
        if not locales:
            return 0
        try:
            nube = cloudinary_product_images(max_age=60)
        except Exception:
            return 0                                  # sin conexión con Cloudinary: se reintenta luego
        subidas = 0
        for i, prod in enumerate(locales):
            src = local_path_for_url(prod.imagen_url)
            if src is None:
                continue
            if prod.id in nube and nube[prod.id]["creado"] >= src.stat().st_mtime:
                continue                              # Cloudinary tiene una foto más nueva: no se pisa
            # copia temporal: upload_product_image reescribe la copia local con el mismo nombre
            tmp = Path(tempfile.mkdtemp()) / src.name
            shutil.copyfile(src, tmp)
            try:
                url = upload_product_image(str(tmp), prod.id)
            finally:
                shutil.rmtree(tmp.parent, ignore_errors=True)
            if url.startswith("http"):           # se subió (si no hay internet regresa la ruta local)
                prod.imagen_url = url
                db.commit()
                subidas += 1
            else:
                break                            # sin conexión: se reintenta en la siguiente pasada
            if progress_cb:
                try:
                    progress_cb(i + 1, len(locales))
                except Exception:
                    pass
        return subidas
    finally:
        db.close()


def upload_product_image(file_path: str, product_id) -> str:
    filename = f"producto_{product_id}"
    if not _cloudinary_configured():
        return _save_local(file_path, "medicamentos", filename)
    # Cada producto tiene UNA foto en Cloudinary (identificador fijo producto_{id}). Si la foto
    # que se quiere subir es exactamente la misma que ya tiene, no se vuelve a subir.
    import hashlib
    huella = hashlib.md5(Path(file_path).read_bytes()).hexdigest()
    manifest = _load_manifest()
    if manifest.get(f"{filename}#huella") == huella and str(manifest.get(filename, "")).startswith("http"):
        return manifest[filename]
    _configure()
    try:
        size = _STANDARD_SIZE["medicamentos"]
        result = cloudinary.uploader.upload(
            file_path,
            folder="FARMACIA/PRODUCTOS",
            public_id=filename,
            overwrite=True,
            resource_type="image",
            # "pad" en vez de "fill": encoge la foto completa para que quepa en
            # el cuadrado y rellena con blanco alrededor, sin recortar nada del
            # producto (mismo criterio que _fit_white_square para la copia
            # local) — así la copia maestra en Cloudinary ya viene consistente,
            # sin depender de que cloudinaryThumb() la recorte al vuelo en el front.
            transformation=[{"width": size, "height": size, "crop": "pad", "background": "white"}],
        )
        url = result["secure_url"]
        # Guardar también una copia local del respaldo — así esta misma PC no
        # tiene que re-descargar de Cloudinary la foto que ella misma subió, y
        # sync_product_images_locally() no la vuelve a bajar en otras PCs que ya
        # la tengan (el manifest queda alineado con la URL real desde ya).
        try:
            _save_local(file_path, "medicamentos", filename)
            manifest = _load_manifest()
            manifest[filename] = url
            manifest[f"{filename}#huella"] = huella
            _save_manifest(manifest)
        except Exception:
            pass
        return url
    except Exception:
        # Sin internet / Cloudinary caído — no perder la imagen, guardarla local.
        return _save_local(file_path, "medicamentos", filename)


def upload_profile_photo(file_path: str, user_id) -> str:
    filename = f"usuario_{user_id}"
    if not _cloudinary_configured():
        return _save_local(file_path, "perfiles", filename)
    _configure()
    try:
        result = cloudinary.uploader.upload(
            file_path,
            folder="FARMACIA/FOTOS_PERFIL",
            public_id=filename,
            overwrite=True,
            resource_type="image",
            transformation=[{"width": 300, "height": 300, "crop": "fill", "gravity": "face"}],
        )
        return result["secure_url"]
    except Exception:
        return _save_local(file_path, "perfiles", filename)


def delete_product_image(product_id) -> None:
    filename = f"producto_{product_id}"
    _delete_local("medicamentos", filename)
    manifest = _load_manifest()
    if (manifest.pop(filename, None), manifest.pop(f"{filename}#huella", None)) != (None, None):
        _save_manifest(manifest)
    if not _cloudinary_configured():
        return
    _configure()
    try:
        cloudinary.uploader.destroy(f"FARMACIA/PRODUCTOS/producto_{product_id}")
    except Exception:
        pass


def upload_documento(file_path: str, folder: str, public_id: str) -> str:
    """Sube un archivo (XML/PDF) como raw a Cloudinary para respaldo en la nube."""
    _configure()
    result = cloudinary.uploader.upload(
        file_path,
        folder=folder,
        public_id=public_id,
        overwrite=True,
        resource_type="raw",
    )
    return result["secure_url"]


def delete_documento(folder: str, public_id: str) -> None:
    _configure()
    try:
        cloudinary.uploader.destroy(f"{folder}/{public_id}", resource_type="raw")
    except Exception:
        pass
