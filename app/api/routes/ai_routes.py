from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, List, Any
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()

CHAR_LIMIT = 500


class DescripcionRequest(BaseModel):
    nombre: str
    nombre_generico: Optional[str] = None
    marca: Optional[str] = None
    presentacion: Optional[str] = None
    concentracion: Optional[str] = None
    contenido: Optional[str] = None


@router.post("/descripcion")
def generar_descripcion(body: DescripcionRequest, payload: dict = Depends(get_current_api_user)):
    import app.config as cfg
    if not cfg.OPENAI_API_KEY:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY no configurada. Agrégala como variable de entorno.",
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="Paquete 'openai' no instalado en el servidor.",
        )

    client = OpenAI(api_key=cfg.OPENAI_API_KEY)

    partes = [f"Medicamento: {body.nombre}"]
    if body.nombre_generico:
        partes.append(f"Nombre genérico: {body.nombre_generico}")
    if body.marca:
        partes.append(f"Marca: {body.marca}")
    if body.presentacion:
        partes.append(f"Presentación: {body.presentacion}")
    if body.concentracion:
        partes.append(f"Concentración: {body.concentracion}")
    if body.contenido:
        partes.append(f"Contenido: {body.contenido}")

    info_producto = "\n".join(partes)

    prompt = f"""Genera una descripción farmacéutica breve y precisa para este medicamento.
La descripción debe incluir: indicaciones principales, mecanismo de acción o grupo terapéutico, y advertencias clave.
Usa lenguaje técnico-profesional en español. Máximo {CHAR_LIMIT} caracteres. Sin títulos, sin listas, texto corrido.
IMPORTANTE: termina siempre en oración completa, nunca dejes la descripción cortada a la mitad.

{info_producto}

Descripción:"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        msg = str(e)
        if "429" in msg or "quota" in msg.lower() or "billing" in msg.lower():
            raise HTTPException(
                status_code=402,
                detail="Sin créditos en OpenAI. Agrega saldo en platform.openai.com/billing",
            )
        raise HTTPException(status_code=502, detail=f"Error OpenAI: {msg[:200]}")

    text = (response.choices[0].message.content or "").strip()
    if len(text) > CHAR_LIMIT:
        # Cortar en el último punto de una oración completa dentro del límite
        chunk = text[:CHAR_LIMIT]
        last_end = max(chunk.rfind(". "), chunk.rfind("! "), chunk.rfind("? "))
        if last_end > CHAR_LIMIT // 3:
            text = chunk[:last_end + 1].strip()
        else:
            text = chunk.rsplit(" ", 1)[0].rstrip(",;:") + "."

    return {"descripcion": text}


class HistorialMsg(BaseModel):
    rol: str
    contenido: str


class ChatIn(BaseModel):
    mensaje: str
    historial: List[HistorialMsg] = []


@router.post("/chat")
def chat_asistente(body: ChatIn, payload: dict = Depends(get_current_api_user)):
    import app.config as cfg
    if not cfg.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY no configurada.")
    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(status_code=500, detail="Paquete 'openai' no instalado.")

    import re
    from app.database.connection import get_db_session
    from app.database.models import Producto

    db = get_db_session()
    try:
        productos = (
            db.query(Producto)
            .filter(Producto.activo == True)
            .order_by(Producto.nombre)
            .limit(300)
            .all()
        )

        catalog_lines = []
        for p in productos:
            st = f"{int(p.stock or 0)} en stock" if (p.stock or 0) > 0 else "SIN STOCK"
            parts = [f"[{p.id}]", p.nombre]
            if p.nombre_generico and p.nombre_generico.lower() != p.nombre.lower():
                parts.append(f"({p.nombre_generico})")
            if p.concentracion:
                parts.append(p.concentracion)
            if p.presentacion:
                parts.append(p.presentacion)
            parts.append(f"${p.precio_venta:.2f}")
            parts.append(st)
            catalog_lines.append(" | ".join(parts))
        catalog = "\n".join(catalog_lines)

        system_prompt = (
            "Eres Farmacito, asistente farmacéutico clínico experto de Farmacia Eben-Ezer. "
            "Tu conocimiento equivale al de un Químico Farmacéutico Biólogo (QFB) con experiencia clínica. "
            "Tienes acceso al conocimiento de fuentes como Vademécum PLM, Drugs.com, Medscape, "
            "FDA Drug Database, formularios de la OMS y guías terapéuticas de la SSA México.\n\n"

            "CUANDO RESPONDAS A UNA CONSULTA DE MEDICAMENTO O SÍNTOMA, INCLUYE SIEMPRE:\n"
            "1. Qué medicamento(s) recomendar (solo los disponibles en inventario)\n"
            "2. Dosis exacta (adulto y pediátrica si aplica)\n"
            "3. Frecuencia: cada cuántas horas o veces al día\n"
            "4. Duración del tratamiento\n"
            "5. Advertencia o contraindicación clave (máx 1 línea)\n"
            "6. Si aplica: interacción importante con otros medicamentos comunes\n\n"

            "FORMATO DE POSOLOGÍA (úsalo siempre que sugieras un producto):\n"
            "📋 [Nombre]: Dosis adulto: Xmg · Frecuencia: cada Xh · Duración: X días\n"
            "   Pediátrico: X mg/kg cada Xh (si aplica)\n"
            "   ⚠️ Advertencia: [contraindicación o precaución clave]\n\n"

            "REGLAS:\n"
            "- Responde en español, profesional pero comprensible para el cajero\n"
            "- Solo sugiere productos que existan en tu INVENTARIO\n"
            "- Marca cada producto sugerido con su ID: [123]\n"
            "- Si el producto pedido no tiene stock, sugiere SIEMPRE alternativas del mismo principio activo o grupo terapéutico\n"
            "- Para síntomas, recomienda el tratamiento de primera línea con lo disponible\n"
            "- Indica si se requiere receta médica\n"
            "- Para dudas diagnósticas o tratamientos crónicos, recomienda consultar médico\n"
            "- Si no hay ningún producto adecuado, dilo claramente\n\n"

            f"INVENTARIO ACTUAL:\n{catalog}"
        )

        messages: list = [{"role": "system", "content": system_prompt}]
        for h in body.historial[-8:]:
            messages.append({"role": h.rol, "content": h.contenido})
        messages.append({"role": "user", "content": body.mensaje})

        client = OpenAI(api_key=cfg.OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o",
            max_tokens=700,
            temperature=0.15,
            messages=messages,
        )
        texto = (response.choices[0].message.content or "").strip()

        ids = [int(m) for m in re.findall(r'\[(\d+)\]', texto)]
        texto_limpio = re.sub(r'\s*\[\d+\]', '', texto).strip()

        sugeridos = []
        if ids:
            prods = db.query(Producto).filter(Producto.id.in_(ids[:6])).all()
            id_order = {pid: i for i, pid in enumerate(ids)}
            prods.sort(key=lambda p: id_order.get(p.id, 99))
            for p in prods:
                sugeridos.append({
                    "id": p.id,
                    "nombre": p.nombre,
                    "nombre_generico": p.nombre_generico or "",
                    "precio_venta": p.precio_venta,
                    "stock": int(p.stock or 0),
                    "presentacion": p.presentacion or "",
                    "concentracion": p.concentracion or "",
                })

        return {"respuesta": texto_limpio, "sugeridos": sugeridos}

    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "429" in msg or "quota" in msg.lower() or "billing" in msg.lower():
            raise HTTPException(status_code=402, detail="Sin créditos en OpenAI. Agrega saldo en platform.openai.com/billing")
        raise HTTPException(status_code=502, detail=f"Error OpenAI: {msg[:200]}")
    finally:
        db.close()


# ── Mejorar calidad de imagen (IA generativa, gpt-image-1) ──────────────────
# ADVERTENCIA que el admin ya vio y aceptó al elegir esta opción: a diferencia
# de "Quitar fondo" (segmentación, no re-dibuja nada), esto SÍ es un modelo
# generativo — puede alterar sutilmente el texto/código de barras de la
# etiqueta. Por eso el resultado SIEMPRE se regresa como vista previa (no se
# sube a Cloudinary ni se guarda solo) — el front lo muestra para que el
# admin decida si lo acepta o se queda con el original, igual que
# "Quitar fondo" pero con este paso de revisión más explícito por el riesgo.
_MEJORAR_IMAGEN_PROMPT = """Restore this blurry product photograph into a hyper-realistic 4K photograph with the visual character of an ultra-high-end medium-format or flagship full-frame camera system and a world-class prime lens.

Desired visual qualities: extremely high resolving power, precision optics, true-to-life material and surface texture, refined dynamic range, subtle tonal rolloff, realistic micro-contrast, premium lens sharpness, natural depth rendition, clean subject-background separation, lifelike high-end photographic detail.

This is a medicine/pharmacy product package (box, bottle, blister, or tube). Preserve the product EXACTLY as in the source: shape, proportions, colors, packaging design and layout. All printed text, numbers, dosage information, and barcodes must remain PIXEL-FAITHFUL to the source — do not alter, redraw, reflow, invent, or reinterpret any text, numbers, or barcode. If any text is illegible in the source, keep it exactly as blurry/illegible rather than inventing plausible-looking text.

Recover fine detail in: packaging print sharpness, label edges, material reflections and texture, box/bottle/blister contours.

Avoid: hallucinated details, altering any text/numbers/barcodes, fake symmetry, over-retouching, oversharpening halos, artificial HDR, cinematic stylization, fantasy detail, added objects, or changing the product in any way.

Make the final image look as if captured with an extremely expensive professional camera and premium glass under ideal focus, while remaining fully natural and 100% faithful to the source — especially all label text and barcodes."""


@router.post("/mejorar-imagen")
async def mejorar_imagen(
    file: UploadFile = File(None),
    imagen_url: str = Form(None),
    payload: dict = Depends(get_current_api_user),
):
    """Botón opcional "Mejorar calidad" del editor de producto. Usa IA
    generativa (gpt-image-1) — el resultado SIEMPRE se regresa como vista
    previa (base64), nunca se guarda solo, porque a diferencia de remove.bg
    esto sí puede alterar detalle fino como el texto de la etiqueta."""
    import app.config as cfg
    if payload.get("rol") != "admin":
        raise HTTPException(status_code=403, detail="Solo administradores")
    if not cfg.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY no configurada. Agrégala en Configuración > Integraciones.")

    import asyncio
    if file is not None:
        raw = await file.read()
    elif imagen_url:
        import requests
        try:
            r = await asyncio.to_thread(requests.get, imagen_url, timeout=15)
            r.raise_for_status()
            raw = r.content
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"No se pudo descargar la imagen actual: {e}")
    else:
        raise HTTPException(status_code=400, detail="Falta la imagen (archivo o imagen_url)")

    try:
        from openai import OpenAI
    except ImportError:
        raise HTTPException(status_code=500, detail="Paquete 'openai' no instalado en el servidor.")

    import io
    client = OpenAI(api_key=cfg.OPENAI_API_KEY)
    try:
        img_file = io.BytesIO(raw)
        img_file.name = "producto.png"
        # to_thread: client.images.edit es una llamada HTTP bloqueante que
        # puede tardar 10-30s — sin esto bloqueaba el único hilo del event
        # loop y toda la app se sentía congelada mientras generaba la imagen,
        # no solo este botón.
        response = await asyncio.to_thread(
            client.images.edit,
            model="gpt-image-1",
            image=img_file,
            prompt=_MEJORAR_IMAGEN_PROMPT,
            size="1024x1024",
        )
    except Exception as e:
        msg = str(e)
        if "429" in msg or "quota" in msg.lower() or "billing" in msg.lower():
            raise HTTPException(status_code=402, detail="Sin créditos en OpenAI. Agrega saldo en platform.openai.com/billing")
        if "verify" in msg.lower() or "organization" in msg.lower():
            raise HTTPException(status_code=403, detail="Tu cuenta de OpenAI necesita verificación de organización para usar gpt-image-1 (platform.openai.com/settings/organization/general)")
        raise HTTPException(status_code=502, detail=f"Error OpenAI: {msg[:200]}")

    b64 = response.data[0].b64_json
    if not b64:
        raise HTTPException(status_code=502, detail="OpenAI no regresó una imagen")

    import base64
    processed_raw = base64.b64decode(b64)
    from app.services.cloudinary_service import _standardize_image_bytes, _STANDARD_SIZE
    standardized = _standardize_image_bytes(processed_raw, _STANDARD_SIZE["medicamentos"])
    final_bytes = standardized if standardized is not None else processed_raw
    final_b64 = base64.b64encode(final_bytes).decode()
    return {"imagen_base64": f"data:image/jpeg;base64,{final_b64}"}
