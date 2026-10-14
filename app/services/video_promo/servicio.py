"""Video promocional para la pantalla de la farmacia.
Toma los productos del inventario (nombre, precio, foto, presentación), les agrega la descripción corta de la IA
(una sola vez por producto, en caché) y genera un MP4 1920x1080 con el motor de animación."""
import hashlib
import json
import os
import re
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import app.config as cfg
from PIL import Image
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
SERVICIOS_DEFAULT = dict(
    enabled=False, posicion='final',
    titulo='Te atendemos como en casa',
    lineas=['Toma de presión arterial', 'Medición de glucosa', 'Inyecciones', ''],
    horario='', whatsapp='', qr='',
)
DEFAULT_CONFIG = dict(
    seconds=8, intro=True, quality='Máxima', repeat=1, default_style='cortinilla',
    footer_left='FARMACIA EBENEZER  ·  Cerca de ti, como una roca firme',
    footer_right='Precios sujetos a cambio sin previo aviso. Consulte a su médico.',
    out_dir=str(OUT_DIR_DEFAULT),
    drive_auto=True,             # si la PC tiene Google Drive con la carpeta "Videos Roku", se copia ahí sola
    drive_dir='',                # carpeta de Google Drive elegida a mano (vacío = la que se detecte) (ej. G:\\Mi unidad\\Videos Roku)
    drive_reemplazar=True,       # el video nuevo reemplaza al anterior en Drive (el viejo pasa a "Anteriores")
    drive_ultimos={},            # {'promos': 'PROMOS_….mp4', 'tarjetas': '…'}: último video copiado de cada tipo
    precios_video={},            # {producto_id: precio} con los que se hizo el último video de promociones
    auto_noche=True,             # si cambió algún precio, se genera de nuevo solo en la noche
    auto_hora=22,
    auto_ultimo='',              # fecha de la última generación automática
    ms_cuadro=0,                 # cuánto tardó cada cuadro la última vez (para estimar el tiempo)
)
ITEM_DEFAULT = dict(producto_id=None, style='cortinilla', enabled=True, desc='', bens=['', '', ''], tag='',
                    old_price='', show_piece=True, unit='', seconds=0)

_lock = threading.Lock()          # el motor usa estado global: una sola tarea a la vez
_job_lock = threading.Lock()      # revisar y marcar "trabajando" en un solo paso (doble clic)


class _Ocupado:
    """Vista previa: si se está generando un video no se queda esperando (no traba el POS)."""
    def __enter__(self):
        if not _lock.acquire(timeout=2):
            raise ValueError('Se está generando un video; la vista previa vuelve al terminar.')

    def __exit__(self, *a):
        _lock.release()
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
    conf['servicios'] = dict(SERVICIOS_DEFAULT, **(conf.get('servicios') or {}))
    conf['terminal']['disenos'] = [x for x in conf['terminal'].get('disenos') or [] if x != 'persona'] or ['terminal']
    if conf['terminal'].get('diseno') == 'persona': conf['terminal']['diseno'] = 'terminal'
    if 'disenos' not in (d.get('config', {}).get('terminal') or {}):      # proyectos de antes: un solo diseño
        conf['terminal']['disenos'] = [conf['terminal'].get('diseno') or 'terminal']
    if conf.get('default_style') not in ESTILOS: conf['default_style'] = 'cortinilla'
    conf['quality'] = 'Máxima'                     # siempre máxima calidad
    items = [dict(ITEM_DEFAULT, **it) for it in d.get('items', []) if it.get('producto_id')]
    for it in items:                       # el estilo clásico se retiró
        if it.get('style') not in ESTILOS: it['style'] = 'cortinilla'
    if not conf.get('cortinilla_v1'):      # una sola vez: Cortinilla queda como diseño elegido
        conf['cortinilla_v1'] = True
        conf['default_style'] = 'cortinilla'
        for it in items: it['style'] = 'cortinilla'
        try:
            _write(PROYECTO, dict(d, config=conf, items=items))
        except Exception:
            pass
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
        partes, corto = re.split(r'(?<=[,;:])\s', d), ''
        for p_ in partes:                      # junta trozos completos (separados por coma) mientras quepan
            if len((corto + ' ' + p_).strip()) > 60: break
            corto = (corto + ' ' + p_).strip()
        if len(corto) < 18:                    # sin comas útiles: corta por palabras y quita las sueltas del final
            pal = d[:60].split()[:-1]
            while pal and pal[-1].lower().strip(',;:') in ('de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'y', 'o',
                                                            'que', 'es', 'con', 'para', 'en', 'por', 'a', 'al', 'se'):
                pal.pop()
            corto = ' '.join(pal)
        d = corto.rstrip(',;: ') + '.'
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


IMG_MANIFEST = IMG_DIR / '_fotos.json'          # producto_id -> URL de Cloudinary de la copia guardada


def _respaldo_pos(prod_id):
    """Copia local que guarda el POS (uploads/imagenes/medicamentos/producto_{id}.*)."""
    d = Path(cfg.DATA_DIR) / 'uploads' / 'imagenes' / 'medicamentos'
    return next((str(f) for f in sorted(d.glob(f'producto_{prod_id}.*'))), None) if d.is_dir() else None


def imagen_local(prod):
    """Foto del producto para el video. Cloudinary es la copia de calidad: se descarga y, si la foto
    cambió en Cloudinary, se reemplaza la copia guardada. Sin internet se usa la última copia que haya."""
    url = (prod.imagen_url or '').strip()
    if not url: return None
    if url.startswith(('http://', 'https://')):
        ext = os.path.splitext(url.split('?')[0])[1].lower()
        ext = ext if ext in ('.png', '.jpg', '.jpeg', '.webp') else '.png'
        man = _read(IMG_MANIFEST, {})
        actual = next(iter(sorted(IMG_DIR.glob(f'producto_{prod.id}.*'))), None)
        if actual is not None and man.get(str(prod.id)) == url:
            return str(actual)                    # ya está la versión más nueva
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'FarmaciaPOS'})
            with urllib.request.urlopen(req, timeout=30) as r:
                datos = r.read()
            for viejo in IMG_DIR.glob(f'producto_{prod.id}.*'):     # se reemplaza la copia anterior
                viejo.unlink(missing_ok=True)
            dest = IMG_DIR / f'producto_{prod.id}{ext}'
            dest.write_bytes(datos)
            man[str(prod.id)] = url
            _write(IMG_MANIFEST, man)
            return str(dest)
        except Exception:
            # sin internet: la copia que haya (aunque sea la anterior) o el respaldo del POS
            return str(actual) if actual is not None else _respaldo_pos(prod.id)
    # foto que solo está en esta PC (/uploads/...): se sube a Cloudinary en la siguiente sincronización
    for cand in (Path(cfg.DATA_DIR) / url.lstrip('/\\'), Path(url), Path(cfg.BASE_DIR) / url.lstrip('/\\')):
        if cand.is_file(): return str(cand)
    return _respaldo_pos(prod.id)


def foto_chica(prod):
    """True si el producto ocupa muy pocos píxeles en su foto (se verá borroso en la tele).
    Solo revisa la copia que ya está en esta PC (no descarga nada)."""
    act = next(iter(sorted(IMG_DIR.glob(f'producto_{prod.id}.*'))), None) or (
        Path(_respaldo_pos(prod.id)) if _respaldo_pos(prod.id) else None)
    if act is None:
        return False
    try:
        im = Image.open(act)
        im.draft('L', (im.width // 2, im.height // 2))
        g = im.convert('L')
        k = im.width / g.width if g.width else 1
        bb = g.point(lambda v: 255 if v < 238 else 0).getbbox()
        return bool(bb) and max(bb[2] - bb[0], bb[3] - bb[1]) * k < 320
    except Exception:
        return False


def limpiar_fotos_viejas():
    """Borra copias del formato anterior (nombres por hash) que ya no se usan."""
    for f in IMG_DIR.iterdir():
        if f.is_file() and not f.name.startswith(('producto_', '_')):
            f.unlink(missing_ok=True)


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
    tag = (item.get('tag') or '').strip()
    try:
        ahorro = float(old) - float(prod.precio_venta or 0) if old else 0
    except ValueError:
        ahorro = 0
    if not tag and ahorro >= 1:
        tag = 'AHORRA $' + _fmt(ahorro)                 # sello automático con lo que se ahorra
    extra = None
    if item.get('show_piece', True) and prod.venta_fraccionada and (prod.precio_pieza or 0) > 0:
        extra = ['$' + _fmt(prod.precio_pieza), 'c/u']
    return dict(
        file=imagen_local(prod) or '', name=prod.nombre, sub=prod.nombre_generico or '',
        pres=[pres1, _unidades(prod.contenido) if _unidades(prod.contenido) not in pres1 else ''], desc=(item.get('desc') or c.get('desc') or '').strip(),
        bens=(list(bens) + ['', '', ''])[:3], price=_fmt(prod.precio_venta), unit=item.get('unit') or '',
        old_price=old, tag=tag, extra=extra, style=item.get('style') or 'destacado',
        color=None, color2=None, seconds=int(item.get('seconds') or 0),
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


def slide_servicios(serv):
    s = dict(SERVICIOS_DEFAULT, **(serv or {}))
    return dict(style='servicios', name='Servicios', titulo=s['titulo'], lineas=s['lineas'], horario=s['horario'],
                whatsapp=s['whatsapp'], qr=s['qr'])


def con_anuncios(slides, conf):
    """Tarjetas + servicios en el lugar elegido."""
    out = con_terminal(slides, conf)
    s = conf.get('servicios') or {}
    if s.get('enabled'):
        out = [slide_servicios(s)] + out if s.get('posicion') == 'inicio' else out + [slide_servicios(s)]
    return out


def vista_previa_servicios(serv, conf, t=4.0):
    with _Ocupado():
        return motor.preview(slide_servicios(serv), motor_config(conf), t)


def anuncios_terminal(term):
    """Un anuncio por cada diseño elegido (Terminal, Persona, Abanico, Sin contacto)."""
    t = dict(TERMINAL_DEFAULT, **(term or {}))
    return [slide_terminal(t, d) for d in (t.get('disenos') or [t['diseno']])]


def vista_previa_terminal(term, conf, t=4.0):
    with _Ocupado():
        return motor.preview(slide_terminal(term), motor_config(conf), t)


def motor_config(conf):
    return dict(conf, logo=str(LOGO))


# ───────────────────────── vista previa y video ─────────────────────────
def vista_previa(prod, item, conf, t=4.0):
    p = slide(prod, item)
    if not p['file']:
        raise ValueError('Este producto no tiene foto. Agrégala en Inventario.')
    with _Ocupado():
        return motor.preview(p, motor_config(conf), t)


def carpeta_drive(conf):
    """Carpeta de Drive a donde se copia el video ('' = no se sube)."""
    if not conf.get('drive_auto', True):
        return ''
    manual = (conf.get('drive_dir') or '').strip()
    if manual:
        return manual
    return drive_sugerido(solo_existente=True)


def drive_sugerido(solo_existente=False):
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
    if solo_existente:
        return ''
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


def retirar_anterior(carpeta, nombre_viejo, nombre_nuevo):
    """Mueve el video anterior a "Anteriores" (dentro de la misma carpeta): la tele ya no lo pasa, pero no se borra."""
    if not nombre_viejo or nombre_viejo == nombre_nuevo:
        return ''
    viejo = Path(carpeta) / nombre_viejo
    if not viejo.is_file():
        return ''
    dest = Path(carpeta) / 'Anteriores'
    dest.mkdir(exist_ok=True)
    final = dest / nombre_viejo
    if final.exists():
        final = dest / f'{viejo.stem}_{datetime.now():%H%M%S}{viejo.suffix}'
    os.replace(viejo, final)
    return str(final)


def estado_tarea():
    d = {k: v for k, v in _job.items() if k not in ('cancel', 'inicio')}
    if _job.get('state') == 'trabajando' and _job.get('inicio'):
        pasado = time.time() - _job['inicio']
        d['transcurrido'] = int(pasado)
        if 0.05 < _job.get('pct', 0) < 0.999:
            d['restante'] = int(pasado * (1 - _job['pct']) / _job['pct'])
    return d


def estimar_segundos(slides, conf):
    """Cuánto tardará en generarse (según la última vez en esta PC)."""
    ms = float(conf.get('ms_cuadro') or 0) or 22.0
    cuadros = motor.cuadros_totales(slides, dict(conf, logo=str(LOGO)))
    return int(cuadros * ms / 1000) + 3


def cancelar():
    _job['cancel'] = True


def generar(slides, conf, nombre, tipo='promos', precios=None, automatico=False):
    """Arranca la generación en segundo plano. slides: fichas ya armadas (con foto).
    tipo: 'promos' o 'tarjetas' (en Drive, cada video nuevo reemplaza al anterior del mismo tipo).
    precios: {producto_id: precio} con que se hace (para avisar cuando cambien)."""
    out_dir = Path(conf.get('out_dir') or OUT_DIR_DEFAULT)
    out_dir.mkdir(parents=True, exist_ok=True)
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', (nombre or '').strip()).strip(' .') or f'PROMOS_{datetime.now():%Y-%m-%d}'
    if not nombre.lower().endswith('.mp4'): nombre += '.mp4'
    out = out_dir / nombre
    tmp = out.with_name(out.stem + '.generando.mp4')   # el video anterior no se toca hasta que el nuevo esté completo
    with _job_lock:
        if _job['state'] == 'trabajando':
            raise RuntimeError('Ya se está generando un video.')
        _job.update(state='trabajando', pct=0.0, msg='Preparando…', file=str(out), error='', cancel=False, drive='',
                    inicio=time.time(), automatico=automatico)

    def prog(d, t, msg):
        _job['pct'] = d / max(t, 1); _job['msg'] = msg

    def work():
        with _lock:
            try:
                t0 = time.time()
                ok = motor.generate(slides, motor_config(conf), str(tmp), prog, lambda: _job['cancel'])
                if not ok:
                    _job.update(state='cancelado', pct=0.0, msg='Cancelado')
                    return
                os.replace(tmp, out)
                cambios = {}
                cuadros = motor.cuadros_totales(slides, motor_config(conf))
                if cuadros:
                    cambios['ms_cuadro'] = round((time.time() - t0) * 1000 / cuadros, 1)
                if precios is not None:
                    cambios['precios_video'] = {str(k): v for k, v in precios.items()}
                msg = 'Video listo'
                destino = carpeta_drive(conf)
                if destino:
                    _job.update(pct=1.0, msg='Copiando a Google Drive…')
                    try:
                        _job['drive'] = copiar_a_drive(str(out), destino)
                        msg = 'Video listo · copiado a Google Drive (se sube solo)'
                        ult = dict(cargar_proyecto()['config'].get('drive_ultimos') or {})
                        if conf.get('drive_reemplazar', True) and retirar_anterior(destino, ult.get(tipo), out.name):
                            msg += ' · el video anterior pasó a "Anteriores"'
                        ult[tipo] = out.name
                        cambios['drive_ultimos'] = ult
                    except Exception as e:
                        msg = f'Video listo, pero no se pudo copiar a Google Drive: {e}'
                try:
                    guardar_proyecto(config=cambios)
                except Exception:
                    pass
                _job.update(state='listo', pct=1.0, msg=msg)      # "listo" hasta el final (ya con Drive)
            except Exception as e:
                _job.update(state='error', error=str(e), msg='Error')
            finally:
                try: tmp.unlink(missing_ok=True)
                except OSError: pass
    threading.Thread(target=work, daemon=True).start()
    return str(out)


# ───────────────────────── tipo de medicamento (para filtrar el catálogo) ─────────────────────────
# Se deduce del nombre, ingrediente activo, descripción y categoría del inventario (sin IA).
USOS = [
    ('gripe', 'Gripe y resfriado', '', ['fenilefrina', 'pseudoefedrina', 'clorfenamina', 'gripe', 'gripa', 'resfriado',
                                          'antigripal', 'congestion nasal', 'descongestion', 'desenfriol', 'tabcin', 'xl-3',
                                          'xl3', 'next', 'contac', 'catarro']),
    ('tos', 'Tos', '', ['dextrometorfano', 'ambroxol', 'bromhexina', 'guaifenesina', 'carbocisteina', 'acetilcisteina',
                          'benzonatato', 'tos', 'antitusiv', 'expectorante', 'mucolitic', 'flemas', 'broxol',
                          'histiacil', 'pulmonar', 'bronquio']),
    ('dolor', 'Dolor y fiebre', '', ['paracetamol', 'acetaminofen', 'ibuprofeno', 'naproxeno', 'diclofenaco', 'ketorolaco',
                                       'metamizol', 'aspirina', 'acetilsalicilico', 'ketoprofeno', 'meloxicam', 'celecoxib',
                                       'tramadol', 'piroxicam', 'nimesulida', 'analgesic', 'antiinflamatori', 'dolor',
                                       'fiebre', 'migrana', 'jaqueca', 'cafiaspirina', 'neomelubrina']),
    ('alergia', 'Alergias', '', ['loratadina', 'cetirizina', 'desloratadina', 'fexofenadina', 'levocetirizina', 'difenhidramina',
                                   'alergi', 'antihistamin', 'rinitis', 'comezon', 'urticaria']),
    ('estomago', 'Estómago y digestión', '', ['omeprazol', 'pantoprazol', 'esomeprazol', 'ranitidina', 'butilhioscina',
                                               'hioscina', 'loperamida', 'metoclopramida', 'subsalicilato', 'simeticona',
                                               'antiacido', 'gastri', 'colitis', 'diarrea', 'nausea', 'vomito', 'estomac',
                                               'agruras', 'acidez', 'sal de uvas', 'pepto', 'electrolit', 'suero oral',
                                               'lactobacil', 'estrenimiento', 'senosido', 'laxante', 'parasit', 'albendazol',
                                               'nitazoxanida', 'metronidazol']),
    ('infeccion', 'Infecciones (antibióticos)', '', ['amoxicilina', 'ampicilina', 'cefalexina', 'ciprofloxacino', 'azitromicina',
                                                      'claritromicina', 'cloranfenicol', 'trimetoprim', 'sulfametoxazol',
                                                      'nitrofurantoina', 'penicilina', 'dicloxacilina', 'gentamicina',
                                                      'ceftriaxona', 'levofloxacino', 'doxiciclina', 'clindamicina',
                                                      'antibiotic', 'infeccion', 'bencilpenicilina', 'ampigrin']),
    ('corazon', 'Presión, corazón y colesterol', '', ['losartan', 'enalapril', 'captopril', 'amlodipino', 'metoprolol',
                                                        'telmisartan', 'hidroclorotiazida', 'nifedipino', 'atorvastatina',
                                                        'pravastatina', 'simvastatina', 'rosuvastatina', 'clopidogrel',
                                                        'hipertension', 'presion arterial', 'colesterol', 'hipolipemiante',
                                                        'trigliceridos', 'bezafibrato', 'atorlip']),
    ('diabetes', 'Diabetes', '', ['metformina', 'glibenclamida', 'glimepirida', 'sitagliptina', 'insulina', 'diabet',
                                    'glucosa', 'dapagliflozina', 'pioglitazona']),
    ('vitaminas', 'Vitaminas y suplementos', '', ['vitamina', 'complejo b', 'acido folico', 'multivitamin', 'suplemento',
                                                   'omega', 'calcio', 'hierro', 'zinc', 'magnesio', 'colageno', 'electrolitos']),
    ('piel', 'Piel', '', ['crema', 'pomada', 'unguento', 'dermat', 'clotrimazol', 'ketoconazol', 'miconazol', 'terbinafina',
                            'hidrocortisona', 'betametasona', 'acne', 'hongos', 'piel', 'quemadura', 'rozadura', 'emoliente',
                            'aceite de oliv', 'vaselina']),
    ('ojos', 'Ojos y oídos', '', ['oftalm', 'gotas para los ojos', 'lagrima', 'colirio', 'conjuntivitis', 'otico', 'oidos',
                                     'nafazolina', 'tobramicina']),
    ('curacion', 'Curación y primeros auxilios', '', ['gasa', 'venda', 'guante', 'jeringa', 'alcohol', 'agua oxigenada',
                                                       'algodon', 'curita', 'cubrebocas', 'micropore', 'isodine', 'antisept',
                                                       'aposito', 'cinta', 'termometro', 'plastic world']),
    ('personal', 'Cuidado personal y bebé', '', ['shampoo', 'jabon', 'desodorante', 'panal', 'toalla', 'pasta dental',
                                                  'cepillo', 'bebe', 'biberon', 'condon', 'preservativo', 'protector solar']),
]
_USO_CATEGORIA = {'antibioticos': 'infeccion', 'vitaminas y suplementos': 'vitaminas', 'material de curacion': 'curacion',
                  'cuidado personal': 'personal', 'productos de bebe': 'personal', 'dermatologia': 'piel',
                  'oftalmologia': 'ojos'}


def _sin_acentos(t):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFD', (t or '').lower()) if unicodedata.category(c) != 'Mn')


def usos_producto(prod):
    """Lista de usos (claves de USOS) de un producto, deducida de sus datos del inventario."""
    import re
    def limpio(t):
        return ' ' + re.sub(r'[^a-z0-9]+', ' ', _sin_acentos(t)) + ' '
    desc = (prod.descripcion or '')[:170]                 # solo el inicio: "para qué sirve"
    nombre = limpio(' '.join(str(x or '') for x in (prod.nombre, prod.nombre_generico, prod.marca, prod.presentacion)))
    texto = nombre + limpio(desc)
    out = []
    for k, _, _, palabras in USOS:
        donde = nombre if k in ('curacion', 'personal') else texto
        # la palabra debe empezar donde empieza una palabra; las cortas (tos, gasa, zinc…) deben ser completas
        if any(re.search(r'(?<![a-z0-9])' + re.escape(p.strip()) + (r'(?![a-z])' if len(p.strip()) <= 4 else ''), donde)
               for p in palabras):
            out.append(k)
    cat = _sin_acentos(getattr(getattr(prod, 'categoria', None), 'nombre', '') or '')
    if cat in _USO_CATEGORIA and _USO_CATEGORIA[cat] not in out:
        out.append(_USO_CATEGORIA[cat])
    return out or ['otros']


try:
    limpiar_fotos_viejas()
except Exception:
    pass


# ───────────────────────── armar el video desde el inventario ─────────────────────────
def productos_por_id(ids):
    from app.database.connection import get_db_session
    from app.database.models import Producto
    db = get_db_session()
    try:
        prods = db.query(Producto).filter(Producto.id.in_(list(ids))).all() if ids else []
        for p in prods: db.expunge(p)
        return {p.id: p for p in prods}
    finally:
        db.close()


def hay_existencia(p):
    return (p.stock or 0) > 0 or (getattr(p, 'piezas_sueltas', 0) or 0) > 0


def armar_slides(proy):
    """(fichas, precios, sin_foto) de los productos marcados, con tarjetas y servicios en su lugar."""
    items = [it for it in proy['items'] if it.get('enabled', True)]
    prods = productos_por_id({it['producto_id'] for it in items})
    cache = ia_cache()
    slides, precios, sin_foto = [], {}, []
    for it in items:
        p = prods.get(it['producto_id'])
        if not p or not hay_existencia(p):
            continue                                   # sin existencia no se anuncia
        try:
            sl = slide(p, it, cache)
        except Exception:
            sl = None
        if not sl or not sl['file']:
            sin_foto.append(p.nombre); continue
        slides.append(sl)
        precios[p.id] = float(p.precio_venta or 0)
    return con_anuncios(slides, proy['config']), precios, sin_foto


def cambios_de_precio(proy, prods=None):
    """Productos del video cuyo precio cambió desde el último video: [{id, nombre, antes, ahora}]."""
    ant = proy['config'].get('precios_video') or {}
    if not ant:
        return []
    ids = [it['producto_id'] for it in proy['items'] if it.get('enabled', True)]
    prods = prods or productos_por_id(set(ids))
    out = []
    for i in ids:
        p = prods.get(i)
        if p is None or str(i) not in ant:
            continue
        if abs(float(p.precio_venta or 0) - float(ant[str(i)])) >= 0.005:
            out.append(dict(id=i, nombre=p.nombre, antes=float(ant[str(i)]), ahora=float(p.precio_venta or 0)))
    return out


# ───────────────────────── generación automática en la noche ─────────────────────────
def _revisar_noche():
    proy = cargar_proyecto()
    c = proy['config']
    hoy = f'{datetime.now():%Y-%m-%d}'
    if not c.get('auto_noche', True) or datetime.now().hour != int(c.get('auto_hora') or 22) or c.get('auto_ultimo') == hoy:
        return
    if _job['state'] == 'trabajando' or not carpeta_drive(c):      # solo en la PC que sube a la tele
        return
    if not cambios_de_precio(proy):
        return
    guardar_proyecto(config={'auto_ultimo': hoy})
    slides, precios, _ = armar_slides(proy)
    if slides:
        print(f'[Video] Cambiaron precios: se genera el video de promociones automáticamente ({hoy})')
        generar(slides, c, f'PROMOS_{hoy}', 'promos', precios, automatico=True)


_programador = None


def iniciar_programador():
    """Revisa cada minuto si toca generar el video en la noche (si cambió algún precio)."""
    global _programador
    if _programador is not None:
        return

    def loop():
        time.sleep(90)
        while True:
            try:
                _revisar_noche()
            except Exception as e:
                print(f'[Video] Revisión nocturna: {e}')
            time.sleep(60)
    _programador = threading.Thread(target=loop, daemon=True, name='VideoNoche')
    _programador.start()


# ───────────────────────── vista previa en movimiento (tiempo real) ─────────────────────────
_vivo = {}


def vivo_registrar(p, conf):
    """Guarda la ficha y devuelve una clave de un solo uso para ver la animación en movimiento."""
    import secrets
    ahora = time.time()
    for k in [k for k, v in _vivo.items() if v[2] < ahora]:
        _vivo.pop(k, None)
    tok = secrets.token_urlsafe(18)
    _vivo[tok] = (p, motor_config(conf), ahora + 120)
    return tok


def vivo_cuadros(tok, fps=12, vueltas=3):
    """Cuadros JPEG (960x540) de la animación, al ritmo real, en formato MJPEG."""
    import io
    d = _vivo.pop(tok, None)
    if not d or d[2] < time.time():
        return
    p, conf, _ = d
    with _Ocupado():
        motor._setup(conf)
        motor.LOGO_ALPHA = 1.0
        S = motor.segundos_de(p)
        L, R = motor.build_any(p)
    n = int(S * fps)
    for v in range(vueltas):
        t0 = time.time()
        for i in range(n):
            t = i / fps
            if not _lock.acquire(timeout=2):
                return                                  # se empezó a generar un video
            try:
                motor.SLIDE = S; motor.LOGO_ALPHA = 1.0
                fr = R(L, p, t)
            finally:
                _lock.release()
            buf = io.BytesIO()
            fr.resize((960, 540), Image.BILINEAR).save(buf, 'JPEG', quality=82)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' + str(buf.tell()).encode()
                   + b'\r\n\r\n' + buf.getvalue() + b'\r\n')
            espera = t0 + (i + 1) / fps - time.time()
            if espera > 0:
                time.sleep(espera)
