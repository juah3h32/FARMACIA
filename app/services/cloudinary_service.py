from pathlib import Path
import shutil
import cloudinary
import cloudinary.uploader
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
        return result["secure_url"]
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
    _delete_local("medicamentos", f"producto_{product_id}")
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
