from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.api.routes.auth_routes import get_current_api_user

router = APIRouter()

CHAR_LIMIT = 420


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

    from openai import OpenAI

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

{info_producto}

Descripción:"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.choices[0].message.content or ""
    text = text.strip()
    if len(text) > CHAR_LIMIT:
        text = text[:CHAR_LIMIT].rsplit(" ", 1)[0] + "…"

    return {"descripcion": text}
