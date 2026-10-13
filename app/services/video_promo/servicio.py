"""Video promocional para la pantalla de la farmacia.
Toma los productos del inventario (nombre, precio, foto, presentación), les agrega la descripción corta de la IA
(una sola vez por producto, en caché) y genera un MP4 1920x1080 con el motor de animación."""
import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import app.config as cfg
from . import motor
from . import ia

BASE = Path(cfg.DATA_DIR) / 'video_promo'
IMG_DIR = BASE / 'imagenes'
PROYECTO = BASE / 'proyecto.json'
IA_CACHE = BASE / 'ia_cache.json'
_ASSETS = Path(getattr(sys, '_MEIPASS', cfg.BASE_DIR)) / 'assets'
LOGO = _ASSETS / 'logos' / 'LOGO.png'
OUT_DIR_DEFAULT = Path.home() / 'Videos' / 'Promociones Farmacia'

ESTILOS = ['destacado', 'cortinilla', 'minimal']
TERMINAL_DEFAULT = dict(
    enabled=True, posicion='inicio', cada=3, diseno='terminal', disenos=['terminal'],
    titulo='Aceptamos todas las tarjetas',
    subtitulo='Paga con tu tarjeta de débito o crédito en nuestra terminal',
    marcas=['visa', 'mastercard', 'amex', 'carnet'],
    chips=['Débito', 'Crédito', 'Sin contacto'],
)
DEFAULT_CONFIG = dict(
    seconds=8, intro=True, quality='Alta', repeat=1, default_style='destacado',
    footer_left='FARMACIA EBENEZER  ·  Cerca de ti, como una roca firme',
    footer_right='Precios sujetos a cambio sin previo aviso. Consulte a su médico.',
    out_dir=str(OUT_DIR_DEFAULT),
    drive_dir='',                # carpeta de Google Drive para escritorio (ej. G:\\Mi unidad\\Videos Roku)
)
ITEM_DEFAULT = dict(producto_id=None, style='destacado', enabled=True, desc='', bens=['', '', ''], tag='',
                    old_price='', show_piece=True, unit='')

_lock = threading.Lock()          # el motor usa estado global: una sola tarea a la vez
_job = dict(state='idle', pct=0.0, msg='', file='', error='', cancel=False)

for d in (BASE, IMG_DIR):
    d.mkdir(parents=True, exist_ok=True)
motor.LOG_DIR = str(BASE)


# ───────────────────────── almacenamiento ─────────────────────────
def _read(path, default):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def _write(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    os.replace(tmp, path)


def cargar_proyecto():
    d = _read(PROYECTO, {})
    conf = dict(DEFAULT_CONFIG, **d.get('config', {}))
    conf['terminal'] = dict(TERMINAL_DEFAULT, **(conf.get('terminal') or {}))
    if 'disenos' not in (d.get('config', {}).get('terminal') or {}):      # proyectos de antes: un solo diseño
        conf['terminal']['disenos'] = [conf['terminal'].get('diseno') or 'terminal']
    if conf.get('default_style') not in ESTILOS: conf['default_style'] = 'destacado'
    items = [dict(ITEM_DEFAULT, **it) for it in d.get('items', []) if it.get('producto_id')]
    for it in items:                       # el estilo clásico se retiró
        if it.get('style') not in ESTILOS: it['style'] = 'destacado'
    return {'config': conf, 'items': items}


def guardar_proyecto(config=None, items=None):
    d = cargar_proyecto()
    if config is not None:
        d['config'] = dict(d['config'], **config)
    if items is not None:
        d['items'] = [dict(ITEM_DEFAULT, **it) for it in items if it.get('producto_id')]
    _write(PROYECTO, d)
    return d


# ───────────────────────── datos del producto ─────────────────────────
def _fmt(v):
    if v is None: return ''
    v = float(v)
    return str(int(v)) if abs(v - round(v)) < 0.005 else f'{v:.2f}'


def info_producto(prod):
    return dict(nombre=prod.nombre, nombre_generico=prod.nombre_generico, marca=prod.marca,
                presentacion=prod.presentacion, concentracion=prod.concentracion, contenido=prod.contenido,
                descripcion=(prod.descripcion or '')[:600], requiere_receta=bool(prod.requiere_receta))


def firma(prod):
    s = '|'.join(str(x or '') for x in (prod.nombre, prod.nombre_generico, prod.presentacion,
                                         prod.concentracion, prod.contenido))
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:16]


def ia_cache():
    return _read(IA_CACHE, {})


def texto_ia(prod, api_key, forzar=False):
    """Descripción corta + beneficios. Usa la caché: la IA se llama una sola vez por producto."""
    cache = ia_cache()
    k = str(prod.id)
    if not forzar and k in cache and cache[k].get('firma') == firma(prod):
        return cache[k], False
    r = ia.describir(info_producto(prod), api_key)
    r['firma'] = firma(prod)
    cache[k] = r
    _write(IA_CACHE, cache)
    return r, True


def _unidades(x):
    """'15ML' -> '15 ml', '10 TABS' -> '10 tabletas'."""
    import re
    x = re.sub(r'(\d)\s*([a-zA-Z])', r'\1 \2', ' '.join((x or '').split()))
    for k, v in (('tabs', 'tabletas'), ('tab', 'tabletas'), ('caps', 'cápsulas'), ('cap', 'cápsulas'),
                 ('comp', 'comprimidos'), ('pzas', 'piezas'), ('pza', 'pieza')):
        x = re.sub(r'\b' + k + r'\b', v, x, flags=re.I)
    return re.sub(r'\b(ML|MG|G|L|KG|UI|MCG)\b', lambda m: m.group(1).lower(), x, flags=re.I)


def texto_inventario(prod):
    """Descripción y palomitas armadas con los datos del inventario (sin IA, sin inventar nada)."""
    import re
    d = re.split(r'(?<=[.!?])\s', ' '.join((prod.descripcion or '').split()))[0].strip()
    if len(d) > 60:
        d = d[:60].rsplit(' ', 1)[0].rstrip(',;:') + '.'
    if not d:
        gen = (prod.nombre_generico or '').strip().capitalize()
        con = (prod.concentracion or '').strip()
        d = (gen + (' ' + con if con else '') + '.') if gen else ''
    d = re.sub(r'(\d)\s*(MG|ML|G|MCG|UI)\b', lambda m: m.group(1) + ' ' + m.group(2).lower(), d, flags=re.I)

    bens = []
    cont = _unidades(prod.contenido)
    if cont: bens.append('Contiene ' + cont)
    pres = ' '.join((prod.presentacion or '').split())
    if pres and pres.lower() not in ('otro', 'otros', 'n/a', 'na', 'ninguno', '-'):
        bens.append(('Presentación en ' + pres.lower()) if len(pres) <= 14 else pres)
    conc = _unidades(prod.concentracion)
    if conc and conc.lower() not in d.lower() and conc.lower() != cont.lower():
        bens.append('Concentración ' + conc)
    bens = [b for b in bens if len(b) <= 32]
    if prod.requiere_receta:
        bens = bens[:2] + ['Requiere receta médica']
    return {'desc': d, 'bens': (bens + ['', '', ''])[:3]}


def imagen_local(prod):
    """Ruta local de la foto del producto (descarga y guarda en caché las que están en la nube)."""
    url = (prod.imagen_url or '').strip()
    if not url: return None
    if url.startswith(('http://', 'https://')):
        ext = os.path.splitext(url.split('?')[0])[1].lower()
        ext = ext if ext in ('.png', '.jpg', '.jpeg', '.webp') else '.png'
        dest = IMG_DIR / (hashlib.sha1(url.encode()).hexdigest()[:20] + ext)
        if not dest.exists():
            req = urllib.request.Request(url, headers={'User-Agent': 'FarmaciaPOS'})
            with urllib.request.urlopen(req, timeout=30) as r:
                dest.write_bytes(r.read())
        return str(dest)
    for cand in (Path(url), Path(cfg.DATA_DIR) / url, Path(cfg.BASE_DIR) / url):
        if cand.is_file(): return str(cand)
    return None


def slide(prod, item, cache=None):
    """Convierte producto del inventario + ajustes del video en la ficha que usa el motor."""
    cache = cache if cache is not None else ia_cache()
    c = cache.get(str(prod.id)) or texto_inventario(prod)
    pres_ = (prod.presentacion or '').strip()
    if pres_.lower() in ('otro', 'otros', 'n/a', 'na', 'ninguno', '-'): pres_ = ''
    pres1 = ' '.join(x for x in (pres_, _unidades(prod.concentracion)) if x).strip()
    bens = item.get('bens') if any((b or '').strip() for b in item.get('bens') or []) else c.get('bens', ['', '', ''])
    old = str(item.get('old_price') or '').strip().lstrip('$')
    if not old and prod.precio_tachado and prod.precio_tachado > prod.precio_venta:
        old = _fmt(prod.precio_tachado)
    extra = None
    if item.get('show_piece', True) and prod.venta_fraccionada and (prod.precio_pieza or 0) > 0:
        extra = ['$' + _fmt(prod.precio_pieza), 'c/u']
    return dict(
        file=imagen_local(prod) or '', name=prod.nombre, sub=prod.nombre_generico or '',
        pres=[pres1, _unidades(prod.contenido) if _unidades(prod.contenido) not in pres1 else ''], desc=(item.get('desc') or c.get('desc') or '').strip(),
        bens=(list(bens) + ['', '', ''])[:3], price=_fmt(prod.precio_venta), unit=item.get('unit') or '',
        old_price=old, tag=item.get('tag') or '', extra=extra, style=item.get('style') or 'destacado',
        color=None, color2=None,
    )


def slide_terminal(term, diseno=None):
    """Anuncio de pago con terminal: se aceptan todas las tarjetas."""
    t = dict(TERMINAL_DEFAULT, **(term or {}))
    return dict(style='terminal', name='Pago con tarjeta', diseno=diseno or t['diseno'], titulo=t['titulo'], subtitulo=t['subtitulo'],
                marcas=t['marcas'], chips=t['chips'])


def con_terminal(slides, conf):
    """Inserta el anuncio de terminal en el video según la posición elegida."""
    t = conf.get('terminal') or {}
    if not t.get('enabled'):
        return list(slides)
    ads = anuncios_terminal(t)
    if not slides:
        return ads
    pos = t.get('posicion', 'inicio')
    if pos == 'final':
        return list(slides) + ads
    if pos == 'intercalado':             # se turnan: un anuncio distinto cada N productos
        n = max(1, int(t.get('cada') or 3))
        out, k = [ads[0]], 1
        for i, s in enumerate(slides):
            out.append(s)
            if (i + 1) % n == 0 and i + 1 < len(slides):
                out.append(ads[k % len(ads)]); k += 1
        return out
    return ads + list(slides)


def anuncios_terminal(term):
    """Un anuncio por cada diseño elegido (Terminal, Persona, Abanico, Sin contacto)."""
    t = dict(TERMINAL_DEFAULT, **(term or {}))
    return [slide_terminal(t, d) for d in (t.get('disenos') or [t['diseno']])]


def vista_previa_terminal(term, conf, t=4.0):
    with _lock:
        return motor.preview(slide_terminal(term), motor_config(conf), t)


def motor_config(conf):
    return dict(conf, logo=str(LOGO))


# ───────────────────────── vista previa y video ─────────────────────────
def vista_previa(prod, item, conf, t=4.0):
    p = slide(prod, item)
    if not p['file']:
        raise ValueError('Este producto no tiene foto. Agrégala en Inventario.')
    with _lock:
        return motor.preview(p, motor_config(conf), t)


def drive_sugerido():
    """Busca la carpeta "Videos Roku" de Google Drive para escritorio (G:\\Mi unidad\\Videos Roku, etc.)."""
    import string
    raices = [Path(f'{d}:\\') for d in string.ascii_uppercase if d not in 'AB']
    raices.append(Path.home() / 'Google Drive')
    for r in raices:
        for unidad in ('Mi unidad', 'My Drive', ''):
            base = r / unidad if unidad else r
            try:
                if (base / 'Videos Roku').is_dir():
                    return str(base / 'Videos Roku')
            except OSError:
                continue
    for r in raices:                           # Drive instalado pero sin la carpeta: sugerir "Mi unidad"
        for unidad in ('Mi unidad', 'My Drive'):
            try:
                if (r / unidad).is_dir():
                    return str(r / unidad / 'Videos Roku')
            except OSError:
                continue
    return ''


def copiar_a_drive(archivo, carpeta):
    """Copia el video a la carpeta sincronizada de Google Drive; la app de Drive lo sube sola."""
    import shutil
    dest = Path(carpeta)
    if not dest.drive or not Path(dest.drive + '\\').exists():
        raise RuntimeError('no se encuentra la unidad de Google Drive (¿está abierta la app de Drive?)')
    dest.mkdir(parents=True, exist_ok=True)
    final = dest / Path(archivo).name
    tmp = final.with_suffix('.parcial')
    shutil.copyfile(archivo, tmp)            # se copia completo y luego se renombra: Drive no sube videos a medias
    os.replace(tmp, final)
    return str(final)


def estado_tarea():
    return {k: v for k, v in _job.items() if k != 'cancel'}


def cancelar():
    _job['cancel'] = True


def generar(slides, conf, nombre):
    """Arranca la generación en segundo plano. slides: fichas ya armadas (con foto)."""
    if _job['state'] == 'trabajando':
        raise RuntimeError('Ya se está generando un video.')
    out_dir = Path(conf.get('out_dir') or OUT_DIR_DEFAULT)
    out_dir.mkdir(parents=True, exist_ok=True)
    nombre = (nombre or f'PROMOS_{datetime.now():%Y-%m-%d}').strip()
    if not nombre.lower().endswith('.mp4'): nombre += '.mp4'
    out = out_dir / nombre
    _job.update(state='trabajando', pct=0.0, msg='Preparando…', file=str(out), error='', cancel=False)

    def prog(d, t, msg):
        _job['pct'] = d / max(t, 1); _job['msg'] = msg

    def work():
        with _lock:
            try:
                ok = motor.generate(slides, motor_config(conf), str(out), prog, lambda: _job['cancel'])
                _job.update(state='listo' if ok else 'cancelado', pct=1.0 if ok else 0.0,
                            msg='Video listo' if ok else 'Cancelado', drive='')
                if ok and (conf.get('drive_dir') or '').strip():
                    _job['msg'] = 'Copiando a Google Drive…'
                    try:
                        _job['drive'] = copiar_a_drive(str(out), conf['drive_dir'])
                        _job['msg'] = 'Video listo · copiado a Google Drive (se sube solo)'
                    except Exception as e:
                        _job['msg'] = f'Video listo, pero no se pudo copiar a Google Drive: {e}'
            except Exception as e:
                _job.update(state='error', error=str(e), msg='Error')
    threading.Thread(target=work, daemon=True).start()
    return str(out)
