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
_STANDARD_SIZE = {"medicamentos": 1200, "perfiles": 300}


def _recortar_margen(img: Image.Image, margen: float = 0.06) -> Image.Image:
    """Quita el margen blanco alrededor del producto (deja un respiro de `margen`).
    Antes una foto con mucho blanco alrededor dejaba el producto chiquito en el cuadro
    y en el video de la tele se veía borroso al agrandarlo."""
    rgb = img.convert("RGB")
    gris = rgb.convert("L").point(lambda v: 255 if v < 238 else 0)
    bb = gris.getbbox()
    if not bb:
        return rgb
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    if w * h > rgb.width * rgb.height * 0.85:          # ya casi no tiene margen
        return rgb
    m = int(max(w, h) * margen)
    return rgb.crop((max(0, bb[0] - m), max(0, bb[1] - m), min(rgb.width, bb[2] + m), min(rgb.height, bb[3] + m)))


def _fit_white_square(img: Image.Image, size: int) -> Image.Image:
    """Escala la imagen completa (sin recortar nada del producto) para que
    quepa dentro de un cuadrado size×size sobre fondo blanco, centrada.
    Antes se recortaba al centro para forzar 1:1 — en una foto no cuadrada
    eso podía cortar un borde del producto, muy notorio justo en las fotos
    que ya vienen sin fondo (remove.bg), donde perder un pedazo se ve peor
    que en una con fondo normal. Además deja TODAS las fotos —tengan o no
    fondo removido— sobre el mismo fondo blanco parejo."""
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        # foto con fondo transparente (PNG): el fondo va blanco, no negro
        rgba = img.convert("RGBA")
        fondo = Image.new("RGB", rgba.size, (255, 255, 255))
        fondo.paste(rgba, (0, 0), rgba)
        img = fondo
    img = img.convert("RGB")
    if size >= 800:                                    # fotos de producto: sin margen blanco de sobra
        img = _recortar_margen(img)
        k = size / max(img.width, img.height)          # el producto llena el cuadro (también si viene chica)
        img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    else:
        img.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    offset = ((size - img.width) // 2, (size - img.height) // 2)
    canvas.paste(img, offset)
    if size >= 800:
        # fondo blanco parejo: lo casi blanco (gris claro de la foto) se vuelve blanco puro,
        # así todas las fotos del inventario se ven iguales
        r, g, b = canvas.split()
        from PIL import ImageChops
        claro = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v >= 242 else 0)
        canvas.paste((255, 255, 255), (0, 0), claro)
    return canvas


def _standardize_image_bytes(raw: bytes, size: int) -> bytes | None:
    """Adapta los bytes de una imagen a un cuadrado de `size`×`size` sobre
    fondo blanco (ver _fit_white_square), devueltos ya codificados como JPEG.
    None si `raw` no es una imagen válida (PIL no pudo abrirla) — el llamador
    debe guardar el original tal cual en ese caso, en vez de perder el archivo."""
    try:
        from PIL import ImageOps
        # las fotos de celular traen la rotación en EXIF; sin esto se guardaban de lado
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
        img = _fit_white_square(img, size)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception:
        return None


def fondo_blanco(img: Image.Image) -> bool:
    """True si el borde de la foto es blanco (el producto ya está sobre fondo blanco).
    Una foto sobre mesa, mano o fondo de color da False: necesita quitar fondo."""
    im = img.convert("RGB")
    im.thumbnail((300, 300))
    w, h = im.size
    px = im.load()
    puntos = [(x, y) for x in range(0, w, 3) for y in (0, 1, h - 2, h - 1)] + \
             [(x, y) for y in range(0, h, 3) for x in (0, 1, w - 2, w - 1)]
    blancos = sum(1 for x, y in puntos if min(px[x, y]) >= 232)
    return blancos >= len(puntos) * 0.9


def _preparar_foto_producto(raw: bytes) -> bytes | None:
    """La foto tal como se guarda: si trae fondo (no blanco) y remove.bg está configurado se le
    quita el fondo automáticamente; luego se deja en el cuadrado estándar de 1200 sin margen."""
    try:
        from PIL import ImageOps
        abierta = Image.open(io.BytesIO(raw))
        size = _STANDARD_SIZE["medicamentos"]
        if abierta.format == "JPEG" and abierta.size == (size, size) and fondo_blanco(abierta):
            return raw                    # ya viene preparada (remove.bg, IA, copia local): no se recomprime
        img = ImageOps.exif_transpose(abierta)
        if cfg.REMOVEBG_API_KEY and not fondo_blanco(img):
            from app.services.removebg_service import quitar_fondo_bytes
            try:
                return quitar_fondo_bytes(raw)
            except Exception as e:
                print(f"[Fotos] No se pudo quitar el fondo automáticamente: {e}")
    except Exception:
        return None
    return _standardize_image_bytes(raw, size)


# Resolución real de la foto: cuántos píxeles de detalle tiene el producto. Una foto chica que se
# agrandó a 1200 sigue viéndose borrosa; se detecta reduciéndola y volviéndola a agrandar: si casi
# no cambia, la foto no tenía más detalle que ese tamaño.
# Se guarda en disco: medir tarda ~40 ms por foto y el catálogo del video revisa todas.
_res_cache: dict | None = None


def _res_cache_path() -> Path:
    return cfg.DATA_DIR / "uploads" / "_resolucion.json"


def resolucion_efectiva(path) -> int:
    global _res_cache
    from PIL import ImageChops, ImageStat
    path = Path(path)
    try:
        clave = f"{path}|{path.stat().st_mtime:.0f}|{path.stat().st_size}"
    except OSError:
        return 0
    if _res_cache is None:
        try:
            _res_cache = json.loads(_res_cache_path().read_text(encoding="utf-8"))
        except Exception:
            _res_cache = {}
    if clave in _res_cache:
        return _res_cache[clave]
    res = 0
    try:
        im = Image.open(path).convert("L")
        bb = im.point(lambda v: 255 if v < 238 else 0).getbbox()
        if bb:
            c = im.crop(bb)
            res = max(c.size)
            for t in (250, 300, 350, 400, 450, 500, 600, 700, 900):
                if t >= res:
                    break
                k = t / res
                d = c.resize((max(1, round(c.width * k)), max(1, round(c.height * k))), Image.LANCZOS).resize(c.size, Image.LANCZOS)
                if ImageStat.Stat(ImageChops.difference(c, d)).mean[0] < 1.0:
                    res = t
                    break
    except Exception:
        return 0
    prefijo = f"{path}|"
    for k in [k for k in _res_cache if k.startswith(prefijo)]:
        del _res_cache[k]                         # versión anterior de la misma foto
    _res_cache[clave] = res
    try:
        _res_cache_path().parent.mkdir(parents=True, exist_ok=True)
        _res_cache_path().write_text(json.dumps(_res_cache), encoding="utf-8")
    except Exception:
        pass
    return res


def _save_local(file_path: str, kind: str, filename: str, data: bytes | None = None) -> str:
    """Sin Cloudinary (no configurado, o sin conexión al subir) la imagen se
    queda en este equipo — no se ve en las demás cajas/computadoras hasta que
    Cloudinary vuelva a estar disponible. `data`: la foto ya preparada (así no
    se vuelve a procesar ni a mandar a remove.bg)."""
    dest_dir = cfg.DATA_DIR / "uploads" / _LOCAL_SUBDIR[kind]
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{filename}.*"):
        old.unlink(missing_ok=True)
    raw = Path(file_path).read_bytes()
    if data is None:
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
# Cada foto vive en Cloudinary con el nombre del medicamento y su id al final, p. ej.
# FARMACIA/PRODUCTOS/portem-paracetamol-500mg__313 (antes: producto_313, que se sigue leyendo). Si en otra
# PC se cambia la foto, Cloudinary tiene la versión nueva aunque la fila del producto en esta
# PC tenga una fecha de modificación más reciente (p. ej. por una venta). Por eso la foto NO
# se decide por fechas de la fila: se le pregunta a Cloudinary cuál es la versión vigente.
import re as _re
import time as _time
from datetime import datetime as _dt, timezone as _tz

_PROD_FOLDER = "FARMACIA/PRODUCTOS"
_PROD_PREFIX = _PROD_FOLDER + "/"
_ID_RE = _re.compile(r"(?:^producto_|__)(\d+)$")
_last_cloud_check = 0.0
_cloud_cache: dict = {}


def _slug(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return _re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:70].strip("-")


def nombre_foto(producto_id, nombre: str = "", concentracion: str = "") -> str:
    """Nombre de la foto en Cloudinary: el del medicamento (con su concentración si el nombre no la
    trae) y el id al final, para que nunca choquen dos productos con el mismo nombre."""
    base = nombre or ""
    if concentracion and _slug(concentracion) not in _slug(base):
        base = f"{base} {concentracion}"
    s = _slug(base)
    return f"{s}__{producto_id}" if s else f"producto_{producto_id}"


def _nombre_foto_bd(producto_id) -> str:
    try:
        from app.database.connection import get_db_session
        from app.database.models import Producto
        db = get_db_session()
        try:
            p = db.query(Producto.nombre, Producto.concentracion).filter(Producto.id == int(producto_id)).first()
        finally:
            db.close()
        if p:
            return nombre_foto(producto_id, p[0], p[1])
    except Exception:
        pass
    return f"producto_{producto_id}"


def _id_de_public_id(public_id: str) -> int | None:
    m = _ID_RE.search(public_id[len(_PROD_PREFIX):] if public_id.startswith(_PROD_PREFIX) else "")
    return int(m.group(1)) if m else None


def _fotos_del_producto(producto_id) -> list[str]:
    """Todos los public_id que tiene este producto en Cloudinary (normalmente uno)."""
    import cloudinary.api
    out, cursor = [], None
    while True:
        kw = dict(type="upload", prefix=_PROD_PREFIX, max_results=500)
        if cursor:
            kw["next_cursor"] = cursor
        res = cloudinary.api.resources(**kw)
        out += [r["public_id"] for r in res.get("resources", []) if _id_de_public_id(r["public_id"]) == int(producto_id)]
        cursor = res.get("next_cursor")
        if not cursor:
            return out


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
            pid = _id_de_public_id(r["public_id"])
            if pid is not None:
                creado = r.get("created_at") or ""
                try:
                    ts = _dt.fromisoformat(creado.replace("Z", "+00:00")).timestamp()
                except Exception:
                    ts = 0
                version = int(r.get("version") or 0)
                if pid in out and out[pid]["version"] >= version:
                    continue                       # dos fotos del mismo producto: manda la más nueva
                out[pid] = {"url": r["secure_url"], "version": version, "creado": ts,
                            "public_id": r["public_id"]}
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
            if url == c["url"]:
                continue                                   # ya tiene la versión vigente (mismo nombre y versión)
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
    base = (cfg.DATA_DIR / "uploads").resolve()
    p = (cfg.DATA_DIR / url.lstrip("/\\")).resolve()
    try:
        p.relative_to(base)                    # nunca fuera de uploads (p. ej. ../secret.key)
    except ValueError:
        return None
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
        return _save_local(file_path, "medicamentos", filename, _preparar_foto_producto(Path(file_path).read_bytes()))
    # Cada producto tiene UNA foto en Cloudinary (identificador fijo producto_{id}). Si la foto
    # que se quiere subir es exactamente la misma que ya tiene, no se vuelve a subir.
    import hashlib
    huella = hashlib.md5(Path(file_path).read_bytes()).hexdigest()
    manifest = _load_manifest()
    if manifest.get(f"{filename}#huella") == huella and str(manifest.get(filename, "")).startswith("http"):
        return manifest[filename]
    _configure()
    import tempfile
    lista = None
    nombre = _nombre_foto_bd(product_id)
    try:
        size = _STANDARD_SIZE["medicamentos"]
        # se sube ya sin margen blanco y en tamaño grande (y sin fondo si traía): así el producto
        # se ve nítido en el video
        lista = _preparar_foto_producto(Path(file_path).read_bytes())
        subir = file_path
        if lista:
            t = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            t.write(lista); t.close()
            subir = t.name
        result = cloudinary.uploader.upload(
            subir,
            folder=_PROD_FOLDER,
            public_id=nombre,
            overwrite=True,
            resource_type="image",
            # "pad" en vez de "fill": encoge la foto completa para que quepa en
            # el cuadrado y rellena con blanco alrededor, sin recortar nada del
            # producto (mismo criterio que _fit_white_square para la copia
            # local) — así la copia maestra en Cloudinary ya viene consistente,
            # sin depender de que cloudinaryThumb() la recorte al vuelo en el front.
            # La foto ya va preparada (1200, fondo blanco): se guarda tal cual, sin volver a
            # comprimirla. Solo si no se pudo preparar, Cloudinary la acomoda.
            **({} if lista else {"transformation": [{"width": size, "height": size, "crop": "pad", "background": "white"}]}),
        )
        url = result["secure_url"]
        if lista and subir != file_path:
            try: Path(subir).unlink()
            except OSError: pass
        _borrar_otras_fotos(product_id, f"{_PROD_PREFIX}{nombre}")   # la de nombre viejo (producto_N u otro nombre)
        # Guardar también una copia local del respaldo — así esta misma PC no
        # tiene que re-descargar de Cloudinary la foto que ella misma subió, y
        # sync_product_images_locally() no la vuelve a bajar en otras PCs que ya
        # la tengan (el manifest queda alineado con la URL real desde ya).
        try:
            _save_local(file_path, "medicamentos", filename, lista)
            manifest = _load_manifest()
            manifest[filename] = url
            manifest[f"{filename}#huella"] = huella
            _save_manifest(manifest)
        except Exception:
            pass
        return url
    except Exception:
        # Sin internet / Cloudinary caído — no perder la imagen, guardarla local.
        if lista and subir != file_path:
            try: Path(subir).unlink()
            except OSError: pass
        return _save_local(file_path, "medicamentos", filename, lista)


def _borrar_otras_fotos(producto_id, vigente: str) -> None:
    """Un producto = una foto: borra de Cloudinary las del mismo producto con otro nombre."""
    try:
        for pub in _fotos_del_producto(producto_id):
            if pub != vigente:
                cloudinary.uploader.destroy(pub, invalidate=True)
    except Exception as e:
        print(f"[Fotos] No se pudieron limpiar fotos viejas del producto {producto_id}: {e}")


def renombrar_foto(producto_id, actuales: list[str] | None = None) -> str | None:
    """Pone a la foto del producto el nombre del medicamento (p. ej. tras cambiarle el nombre en
    Inventario). Devuelve la URL nueva, o None si no hizo falta o no se pudo."""
    if not _cloudinary_configured():
        return None
    _configure()
    nuevo = f"{_PROD_PREFIX}{_nombre_foto_bd(producto_id)}"
    try:
        actuales = actuales if actuales is not None else _fotos_del_producto(producto_id)
        if not actuales or nuevo in actuales:
            return None
        res = cloudinary.uploader.rename(actuales[0], nuevo, overwrite=False, invalidate=True)
        for pub in actuales[1:]:
            cloudinary.uploader.destroy(pub, invalidate=True)
    except Exception as e:
        print(f"[Fotos] No se pudo renombrar la foto del producto {producto_id}: {e}")
        return None
    url = res["secure_url"]
    from app.database.connection import get_db_session
    from app.database.models import Producto
    db = get_db_session()
    try:
        prod = db.query(Producto).filter(Producto.id == int(producto_id)).first()
        if prod is not None and (prod.imagen_url or "").startswith("http"):
            prod.imagen_url = url
            db.commit()
    finally:
        db.close()
    manifest = _load_manifest()
    if str(manifest.get(f"producto_{producto_id}", "")).startswith("http"):
        manifest[f"producto_{producto_id}"] = url          # misma foto: no hay que volver a bajarla
        _save_manifest(manifest)
    global _last_cloud_check
    _last_cloud_check = 0.0
    return url


def renombrar_todas_las_fotos(progress_cb=None) -> int:
    """Pasa todas las fotos de producto al nombre del medicamento. Devuelve cuántas cambiaron."""
    nube = cloudinary_product_images()
    hechas = 0
    for n, pid in enumerate(sorted(nube)):
        if renombrar_foto(pid, [nube[pid]["public_id"]]):
            hechas += 1
        if progress_cb:
            try: progress_cb(n + 1, len(nube))
            except Exception: pass
    return hechas


def ajustar_fotos_existentes(progress_cb=None) -> int:
    """Pasa TODAS las fotos de producto de Cloudinary por el mismo ajuste que las nuevas
    (sin margen blanco, producto centrado y del mismo tamaño, fondo blanco parejo, 1200x1200)
    y las vuelve a subir con el mismo nombre. Devuelve cuántas se ajustaron."""
    import tempfile
    nube = cloudinary_product_images()
    if not nube:
        return 0
    from app.database.connection import get_db_session
    from app.database.models import Producto
    db = get_db_session()
    hechas = 0
    try:
        for n, (pid, c) in enumerate(sorted(nube.items())):
            try:
                raw = requests.get(c["url"], timeout=30).content
                data = _standardize_image_bytes(raw, _STANDARD_SIZE["medicamentos"])
                if not data:
                    continue
                t = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg"); t.write(data); t.close()
                try:
                    res = cloudinary.uploader.upload(t.name, folder=_PROD_FOLDER, public_id=_nombre_foto_bd(pid),
                                                     overwrite=True, resource_type="image")
                finally:
                    Path(t.name).unlink(missing_ok=True)
                url = res["secure_url"]
                prod = db.query(Producto).filter(Producto.id == pid).first()
                if prod is not None:
                    prod.imagen_url = url
                    db.commit()
                local = cfg.DATA_DIR / "uploads" / "imagenes" / "medicamentos" / f"producto_{pid}.jpg"
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(data)
                manifest = _load_manifest()
                manifest[f"producto_{pid}"] = url
                manifest.pop(f"producto_{pid}#huella", None)
                _save_manifest(manifest)
                hechas += 1
            except Exception as e:
                print(f"[Fotos] No se pudo ajustar producto_{pid}: {e}")
            if progress_cb:
                try: progress_cb(n + 1, len(nube))
                except Exception: pass
    finally:
        db.close()
    return hechas


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
        for pub in _fotos_del_producto(product_id) or [f"{_PROD_PREFIX}producto_{product_id}"]:
            cloudinary.uploader.destroy(pub, invalidate=True)
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
