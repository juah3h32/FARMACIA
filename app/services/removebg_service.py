import requests
import app.config as cfg
from app.services.cloudinary_service import _standardize_image_bytes, _STANDARD_SIZE


def removebg_configured() -> bool:
    return bool(cfg.REMOVEBG_API_KEY)


def quitar_fondo_bytes(raw: bytes) -> bytes:
    """Manda la imagen a remove.bg (fondo blanco, resource type 'photo') y
    regresa el resultado ya recortado/escalado al mismo cuadrado estándar que
    usa el resto del catálogo (ver _STANDARD_SIZE en cloudinary_service.py) —
    así una foto "arreglada" se ve igual de consistente que las demás."""
    if not cfg.REMOVEBG_API_KEY:
        raise RuntimeError("remove.bg no está configurado — agrega la API key en Configuración > Integraciones")
    try:
        resp = requests.post(
            "https://api.remove.bg/v1.0/removebg",
            files={"image_file": raw},
            data={"size": "auto", "format": "png"},          # PNG con transparencia: la silueta
            headers={"X-Api-Key": cfg.REMOVEBG_API_KEY},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Sin conexión con remove.bg: {e}")
    if resp.status_code != 200:
        detail = resp.text[:200]
        try:
            errors = resp.json().get("errors", [])
            if errors:
                detail = errors[0].get("title", detail)
        except Exception:
            pass
        raise RuntimeError(detail)
    final = _silueta_sobre_original(raw, resp.content)
    standardized = _standardize_image_bytes(final, _STANDARD_SIZE["medicamentos"])
    return standardized if standardized is not None else final


def _silueta_sobre_original(raw: bytes, recorte: bytes) -> bytes:
    """remove.bg (sin créditos pagados) regresa una vista previa chica. En vez de usar esa
    imagen chica, se toma solo su silueta (transparencia), se agranda al tamaño de la foto
    original y se aplica sobre la original: el producto queda con TODA su resolución y
    sobre fondo blanco. Si algo no cuadra, se usa el recorte tal cual sobre blanco."""
    import io
    from PIL import Image, ImageOps, ImageFilter
    cut = Image.open(io.BytesIO(recorte)).convert("RGBA")

    def blanco(im, mascara):
        fondo = Image.new("RGB", im.size, (255, 255, 255))
        fondo.paste(im.convert("RGB"), (0, 0), mascara)
        return fondo

    try:
        abierta = Image.open(io.BytesIO(raw))
        # remove.bg puede regresar la foto girada o sin girar según el EXIF: se usa la que cuadre
        # (tolerancia relativa — en la vista previa chica el redondeo mueve un poco la proporción)
        prop = cut.width / cut.height
        orig = next((im.convert("RGB") for im in (ImageOps.exif_transpose(abierta), abierta)
                     if abs(im.width / im.height - prop) / prop <= 0.03 and im.width >= cut.width), None)
        if orig is None:
            print("[remove.bg] la silueta no cuadra con la foto original; se usa la vista previa")
            raise ValueError("proporciones distintas")
        mask = cut.split()[3].resize(orig.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
        res = blanco(orig, mask)
    except Exception:
        res = blanco(cut, cut.split()[3])
    out = io.BytesIO()
    res.save(out, format="JPEG", quality=95)
    return out.getvalue()


def check_account() -> dict:
    """Ping liviano a remove.bg — usado por /admin/integrations-status. Regresa
    créditos restantes, útil para avisar antes de que se acaben."""
    resp = requests.get(
        "https://api.remove.bg/v1.0/account",
        headers={"X-Api-Key": cfg.REMOVEBG_API_KEY},
        timeout=8,
    )
    if resp.status_code == 403:
        raise RuntimeError("API key de remove.bg inválida")
    resp.raise_for_status()
    attrs = resp.json().get("data", {}).get("attributes", {})
    credits = attrs.get("credits", {})
    return {"free_credits": credits.get("free"), "paid_credits": credits.get("subscription", credits.get("payg"))}
