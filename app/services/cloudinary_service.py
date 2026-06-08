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


def upload_product_image(file_path: str, product_id: int) -> str:
    _configure()
    result = cloudinary.uploader.upload(
        file_path,
        folder="FARMACIA/PRODUCTOS",
        public_id=f"producto_{product_id}",
        overwrite=True,
        resource_type="image",
    )
    return result["secure_url"]


def upload_profile_photo(file_path: str, user_id: int) -> str:
    _configure()
    result = cloudinary.uploader.upload(
        file_path,
        folder="FARMACIA/FOTOS_PERFIL",
        public_id=f"usuario_{user_id}",
        overwrite=True,
        resource_type="image",
        transformation=[{"width": 300, "height": 300, "crop": "fill", "gravity": "face"}],
    )
    return result["secure_url"]


def delete_product_image(product_id: int) -> None:
    _configure()
    try:
        cloudinary.uploader.destroy(f"FARMACIA/PRODUCTOS/producto_{product_id}")
    except Exception:
        pass
