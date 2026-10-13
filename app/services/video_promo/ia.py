"""IA (Claude) del video promocional: escribe SOLO la descripción corta y los 3 beneficios de cada producto.
El nombre, precio, foto, ingrediente y presentación salen del inventario del POS.
Se envía únicamente texto (no la foto) para gastar el mínimo de tokens, y el resultado se guarda en caché."""
import json

MODEL = 'claude-opus-5-5'

SYSTEM = """Eres el redactor de la pantalla de promociones de una farmacia en México.
Con los datos del producto, escribe en español de México:
- descripcion: una frase de máximo 60 caracteres sobre para qué sirve, basada en el uso aprobado del producto. Termina con punto.
- beneficios: exactamente 3 frases muy cortas (máximo 24 caracteres cada una), ej. "Alivia el dolor", "Caja con 24 tabletas".
Si el producto requiere receta médica, uno de los beneficios debe ser "Requiere receta médica".
No inventes datos, no escribas precios ni promesas médicas exageradas."""

SCHEMA = {
    'type': 'object',
    'properties': {'descripcion': {'type': 'string'}, 'beneficios': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['descripcion', 'beneficios'],
    'additionalProperties': False,
}


class IAError(Exception):
    pass


def describir(info: dict, api_key: str) -> dict:
    """info: nombre, nombre_generico, marca, presentacion, concentracion, contenido, descripcion, requiere_receta."""
    if not api_key:
        raise IAError('Falta la clave de Claude. Agrégala en Marketing → Video promocional → Ajustes del video.')
    try:
        import anthropic
    except ImportError:
        raise IAError("Paquete 'anthropic' no instalado.")
    datos = [f'{k}: {v}' for k, v in info.items() if v not in (None, '', False)]
    client = anthropic.Anthropic(api_key=api_key.strip(), timeout=90.0)
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
            output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCHEMA}},
            system=SYSTEM,
            messages=[{'role': 'user', 'content': 'Datos del producto:\n' + '\n'.join(datos)}],
        )
    except anthropic.AuthenticationError:
        raise IAError('La clave de Claude no es válida. Revísala en Marketing → Video promocional → Ajustes del video.')
    except anthropic.PermissionDeniedError:
        raise IAError('La clave de Claude no tiene permiso. Revisa tu cuenta en console.anthropic.com.')
    except anthropic.RateLimitError:
        raise IAError('Demasiadas solicitudes seguidas. Espera un minuto e intenta de nuevo.')
    except anthropic.BadRequestError as e:
        msg = str(getattr(e, 'message', e))
        if 'credit' in msg.lower() or 'balance' in msg.lower():
            raise IAError('Tu cuenta de Claude no tiene saldo. Agrega crédito en console.anthropic.com.')
        raise IAError('Claude rechazó la solicitud: ' + msg[:200])
    except anthropic.APIConnectionError:
        raise IAError('Sin conexión a internet.')
    except anthropic.APIStatusError as e:
        raise IAError(f'Error del servicio de Claude ({e.status_code}). Intenta más tarde.')
    except Exception as e:
        raise IAError(f'No se pudo usar la IA: {type(e).__name__}: {e}')
    if resp.stop_reason == 'refusal':
        raise IAError('La IA no pudo describir este producto. Escribe la descripción a mano.')
    text = next((b.text for b in resp.content if b.type == 'text'), '')
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        raise IAError('La IA respondió algo inesperado. Intenta de nuevo.')
    bens = [b.strip() for b in d.get('beneficios', []) if b.strip()][:3]
    if info.get('requiere_receta') and not any('receta' in b.lower() for b in bens):
        bens = bens[:2] + ['Requiere receta médica']
    return {'desc': d.get('descripcion', '').strip(), 'bens': (bens + ['', '', ''])[:3]}
