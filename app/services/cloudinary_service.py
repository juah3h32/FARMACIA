from pathlib import Path
import json
import shutil
import cloudinary
import cloudinary.uploader
import requests
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


def _save_local(file_path: str, kind: str, filename: str) -> str:
    """Sin Cloudinary (no configurado, o sin conexión al subir) la imagen se
    queda en este equipo — no se ve en las demás cajas/computadoras hasta que
    Cloudinary vuelva a estar disponible."""
    dest_dir = cfg.DATA_DIR / "uploads" / _LOCAL_SUBDIR[kind]
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{filename}.*"):
        old.unlink(missing_ok=True)
    ext = Path(file_path).suffix or ".jpg"
    shutil.copyfile(file_path, dest_dir / f"{filename}{ext}")
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
    normal cuando Cloudinary no está disponible."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception:
        return False
    dest_dir = cfg.DATA_DIR / "uploads" / _LOCAL_SUBDIR[kind]
    dest_dir.mkdir(parents=True, exist_ok=True)
    for old in dest_dir.glob(f"{filename}.*"):
        old.unlink(missing_ok=True)
    ext = Path(url.split("?")[0]).suffix or ".jpg"
    (dest_dir / f"{filename}{ext}").write_bytes(resp.content)
    return True


def sync_product_images_locally() -> int:
    """Recorre los productos con foto en Cloudinary y descarga a este equipo
    las que todavía no tiene guardadas localmente (o cuya URL cambió desde la
    última descarga, p. ej. porque se reemplazó la foto en otra PC). Pensado
    para llamarse en segundo plano después de cada sync con Turso — así el
    catálogo sigue mostrando fotos aunque después se pierda la conexión con
    Cloudinary. Devuelve cuántas imágenes se descargaron."""
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
    downloaded = 0
    for pid, url in productos:
        if not url or not url.startswith("http"):
            continue  # ya es una ruta local (/uploads/...), no hay nada que bajar
        filename = f"producto_{pid}"
        if manifest.get(filename) == url:
            continue  # ya se tiene copia local de esta misma versión de la foto
        if cache_remote_image(url, "medicamentos", filename):
            manifest[filename] = url
            downloaded += 1
    if downloaded:
        _save_manifest(manifest)
    return downloaded


def upload_product_image(file_path: str, product_id) -> str:
    filename = f"producto_{product_id}"
    if not _cloudinary_configured():
        return _save_local(file_path, "medicamentos", filename)
    _configure()
    try:
        result = cloudinary.uploader.upload(
            file_path,
            folder="FARMACIA/PRODUCTOS",
            public_id=filename,
            overwrite=True,
            resource_type="image",
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
    if manifest.pop(filename, None) is not None:
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
