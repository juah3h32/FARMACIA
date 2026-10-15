"""IA del video promocional: escribe SOLO la descripción corta y los 3 beneficios de cada producto.
El nombre, precio, foto, ingrediente y presentación salen del inventario del POS.
Usa OpenAI (la misma clave de Configuración > Integraciones que describe los productos; es más barato) y,
solo si no hay clave de OpenAI, Claude. Para no inventar, la IA busca en internet el producto EXACTO (laboratorio, ficha, farmacias de México) y
escribe solo lo que dice esa fuente. Se envía únicamente texto (no la foto) y el resultado se guarda en
caché: cada producto se busca una sola vez (~10-20 s)."""
import json
from urllib.parse import urlparse

import app.config as cfg

MODEL = 'claude-opus-5-5'
# Modelo chico de OpenAI con búsqueda web; si la cuenta no lo tiene, se intenta el siguiente.
OPENAI_MODELOS = ('gpt-5.4-mini', 'gpt-4.1-mini')

SYSTEM = """Eres el redactor de la pantalla de promociones de una farmacia en México.
Primero busca en internet el producto EXACTO: marca + nombre comercial + concentración + presentación (y el
código de barras si viene). Prefiere el sitio del laboratorio, la ficha o etiqueta (IPP/PLM) o farmacias de
México (Farmacias del Ahorro, Guadalajara, San Pablo, Benavides). Los datos del inventario pueden tener
errores (p. ej. una concentración mal capturada o una descripción escrita antes): si la fuente dice otra
cosa, manda la fuente.
Luego responde en español de México:
- producto_encontrado: el nombre del producto tal como aparece en la fuente.
- coincide: true solo si la fuente es del mismo producto (misma marca o nombre comercial y mismo
  ingrediente). Si no lo encuentras o es otro producto, false.
- fuentes: las URL que usaste.
- descripcion: máximo 60 caracteres, para qué sirve según la fuente. Termina con punto.
- beneficios: exactamente 3 frases de máximo 24 caracteres (uso, ingrediente, presentación o contenido
  real), ej. "Alivia el dolor", "Caja con 24 tabletas".
Si coincide es false, escribe solo lo que se sabe con certeza por el nombre genérico, sin detalles que no
estén confirmados. Si el producto requiere receta médica, uno de los beneficios debe ser "Requiere receta
médica". No escribas precios ni promesas médicas."""

SCHEMA = {
    'type': 'object',
    'properties': {
        'producto_encontrado': {'type': 'string'},
        'coincide': {'type': 'boolean'},
        'fuentes': {'type': 'array', 'items': {'type': 'string'}},
        'descripcion': {'type': 'string'},
        'beneficios': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['producto_encontrado', 'coincide', 'fuentes', 'descripcion', 'beneficios'],
    'additionalProperties': False,
}

BUSQUEDA = {'type': 'web_search_20260209', 'name': 'web_search', 'max_uses': 4,
            'user_location': {'type': 'approximate', 'country': 'MX'}}


class IAError(Exception):
    pass


def configurada() -> bool:
    return bool(cfg.OPENAI_API_KEY or cfg.ANTHROPIC_API_KEY)


def describir(info: dict) -> dict:
    """info: nombre, nombre_generico, marca, presentacion, concentracion, contenido, descripcion, requiere_receta."""
    datos = 'Datos del producto en el inventario:\n' + '\n'.join(
        f'{k}: {v}' for k, v in info.items() if v not in (None, '', False))
    if cfg.OPENAI_API_KEY:
        text = _con_openai(datos, cfg.OPENAI_API_KEY)
    elif cfg.ANTHROPIC_API_KEY:
        text = _con_claude(datos, cfg.ANTHROPIC_API_KEY)
    else:
        raise IAError('Falta la clave de OpenAI. Agrégala en Configuración > Integraciones '
                      '(o en Marketing → Video promocional → Ajustes del video).')
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        raise IAError('La IA respondió algo inesperado. Intenta de nuevo.')
    bens = [b.strip() for b in d.get('beneficios', []) if b.strip()][:3]
    if info.get('requiere_receta') and not any('receta' in b.lower() for b in bens):
        bens = bens[:2] + ['Requiere receta médica']
    fuentes = [f for f in d.get('fuentes', []) if f.startswith('http')]
    verificado = bool(d.get('coincide')) and bool(fuentes)
    return {'desc': d.get('descripcion', '').strip(), 'bens': (bens + ['', '', ''])[:3],
            'verificado': verificado, 'fuente': urlparse(fuentes[0]).netloc.removeprefix('www.') if fuentes else '',
            'producto_encontrado': d.get('producto_encontrado', '').strip()}


def _con_openai(datos: str, api_key: str) -> str:
    """OpenAI (Responses API) con búsqueda web; devuelve el JSON como texto."""
    try:
        import openai
    except ImportError:
        raise IAError("Paquete 'openai' no instalado.")
    client = openai.OpenAI(api_key=api_key.strip(), timeout=180.0)
    ultimo = None
    for modelo in OPENAI_MODELOS:
        try:
            resp = client.responses.create(
                model=modelo,
                instructions=SYSTEM,
                input=datos,
                tools=[{'type': 'web_search', 'search_context_size': 'low',
                        'user_location': {'type': 'approximate', 'country': 'MX'}}],
                text={'format': {'type': 'json_schema', 'name': 'descripcion_producto', 'schema': SCHEMA, 'strict': True}},
            )
            return resp.output_text
        except openai.AuthenticationError:
            raise IAError('La clave de OpenAI no es válida. Revísala en Configuración > Integraciones.')
        except openai.PermissionDeniedError:
            raise IAError('La clave de OpenAI no tiene permiso para este modelo. Revisa tu cuenta en platform.openai.com.')
        except openai.RateLimitError as e:
            if 'quota' in str(e).lower():
                raise IAError('Sin créditos en OpenAI. Agrega saldo en platform.openai.com/billing')
            raise IAError('Demasiadas solicitudes seguidas. Espera un minuto e intenta de nuevo.')
        except (openai.NotFoundError, openai.BadRequestError) as e:
            ultimo = e                                     # modelo no disponible en la cuenta: el siguiente
            continue
        except openai.APIConnectionError:
            raise IAError('Sin conexión a internet.')
        except openai.APIStatusError as e:
            raise IAError(f'Error del servicio de OpenAI ({e.status_code}). Intenta más tarde.')
        except Exception as e:
            raise IAError(f'No se pudo usar la IA: {type(e).__name__}: {e}')
    raise IAError('OpenAI rechazó la solicitud: ' + str(getattr(ultimo, 'message', ultimo))[:200])


def _con_claude(datos: str, api_key: str) -> str:
    try:
        import anthropic
    except ImportError:
        raise IAError("Paquete 'anthropic' no instalado.")
    client = anthropic.Anthropic(api_key=api_key.strip(), timeout=180.0)
    messages = [{'role': 'user', 'content': datos}]
    try:
        for _ in range(3):
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=8000,
                betas=['server-side-fallback-2026-07-01'],
                fallbacks='default',
                output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCHEMA}},
                tools=[BUSQUEDA],
                system=SYSTEM,
                messages=messages,
            )
            if resp.stop_reason != 'pause_turn':
                break
            # la búsqueda se pausó a medias: se reenvía tal cual y el servidor sigue donde iba
            messages = messages[:1] + [{'role': 'assistant', 'content': resp.content}]
    except anthropic.AuthenticationError:
        raise IAError('La clave de Claude no es válida.')
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
    return next((b.text for b in resp.content if b.type == 'text'), '')
