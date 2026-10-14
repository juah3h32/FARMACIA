"""Estilos de animación (destacado, cortinilla, minimal) y el anuncio de pago con terminal.
 - destacado: producto al centro con rayos de luz girando, precio grande que "golpea" la pantalla.
 - anuncio:   aviso de texto (servicios, horarios, consultas) con foto opcional y formas animadas.
El estilo clásico vive en motor.py (build / render).
"""
import math
from PIL import Image, ImageDraw, ImageFilter, ImageChops
from . import motor as M
from .motor import (W, H, font, BLACK, BOLD, SEMI, REG, lighten, darken, text_w, wrap, hgrad, vgrad, rr_mask,
                   shadow, cut_cached, check_icon, paste, appear, ease_out_cubic, ease_in_cubic, ease_out_back)

NAVY, BLUE = M.NAVY, M.BLUE


def text_layer(s, fnt, color, pad=10):
    bb = fnt.getbbox(s or ' ')
    im = Image.new('RGBA', (bb[2] - bb[0] + pad * 2, bb[3] + pad * 2), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - bb[0], pad), s, font=fnt, fill=tuple(color) + (255,))
    return im


def fit_font(name, s, maxw, start, minimum):
    size = start
    while text_w(font(name, size), s) > maxw and size > minimum: size -= 4
    return font(name, size)


def pill(text, col, width, fsize=36):
    f = font(BOLD, fsize)
    lines = wrap(f, text, width - 100)
    h = int(fsize * 1.32) * len(lines) + 44
    im = hgrad((width, h), col, lighten(col, 0.35)).convert('RGBA')
    im.putalpha(rr_mask((width, h), h // 2))
    dr = ImageDraw.Draw(im)
    lh = int(fsize * 1.32)
    for i, s in enumerate(lines):
        dr.text((width // 2, 22 + lh // 2 + i * lh), s, font=f, fill='white', anchor='mm')
    return shadow(im, blur=12, off=(0, 8), opacity=0.25, pad=30)[0]


def shine(layer, face, pad, k):
    """Destello diagonal sobre una etiqueta (k de 0 a 1)."""
    bw, bh = face
    out = layer.copy()
    sh = Image.new('L', out.size, 0)
    x = pad - 200 + (bw + 400) * k
    ImageDraw.Draw(sh).polygon([(x, pad), (x + 90, pad), (x + 10, pad + bh), (x - 80, pad + bh)], fill=120)
    sh = sh.filter(ImageFilter.GaussianBlur(10))
    full = Image.new('L', out.size, 0); full.paste(rr_mask((bw, bh), 46), (pad, pad))
    sh = ImageChops.multiply(sh, full)
    wl = Image.new('RGBA', out.size, (255, 255, 255, 255)); wl.putalpha(sh)
    out.alpha_composite(wl)
    return out


def base_frame():
    fr = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    return fr


def finish(fr, pos=None):
    fr.alpha_composite(M.WAVE, (0, H - 260))
    M.draw_logo(fr, pos or M.LOGO_POS)
    return fr.convert('RGB')


def color_of(p):
    if p.get('color'): return tuple(p['color'])
    if p.get('file'):
        try: return tuple(M.auto_color(p['file']))
        except Exception: pass
    return BLUE


# =====================================================================
#  DESTACADO  (estilo póster de oferta a todo lo ancho: panel diagonal de color, producto en un círculo grande,
#              nombre gigante con listón encimado y etiqueta de precio colgando con contador)
# =====================================================================
def _num(price):
    t = (price or '').replace(',', '').strip()
    try:
        v = float(t)
    except ValueError:
        return None, 0
    dec = len(t.split('.')[1]) if '.' in t else 0
    return v, dec


D_CX, D_CY, D_R = 560, 560, 330          # círculo del producto
D_PIV = (850, 92)                        # de dónde cuelga la etiqueta del precio
D_STR, D_TR = 175, 150                   # largo del hilo y radio de la etiqueta
D_X, D_RW = 1075, 700                    # columna de texto
D_PANEL = (0, 820, 600)                  # panel diagonal: arriba llega a x=820, abajo a x=600
DARK = (31, 41, 55)


def build_destacado(p):
    L = M.build(p)                       # reutiliza el precio por pieza (extra)
    col = color_of(p); L['col'] = col
    deep = darken(col, 0.3)
    # fondo a todo lo ancho (nada de marco): degradado muy suave del color del producto
    L['bg'] = vgrad((W, H), (255, 255, 255), lighten(col, 0.9)).convert('RGBA')
    # panel diagonal de color detrás del producto, con anillos que irradian desde el círculo
    pw_ = D_PANEL[1] + 40
    pan = Image.new('RGBA', (pw_, H), (0, 0, 0, 0))
    g = Image.new('RGBA', (pw_, H)); g.paste(vgrad((pw_, H), lighten(col, 0.1), deep))
    dg = ImageDraw.Draw(g)
    for r in range(D_R + 90, 1400, 95):
        dg.ellipse((D_CX - r, D_CY - r, D_CX + r, D_CY + r), outline=(255, 255, 255, 255), width=2)
    base_ = Image.new('RGBA', (pw_, H)); base_.paste(vgrad((pw_, H), lighten(col, 0.1), deep))
    g = Image.blend(base_, g, 0.16)
    ss = 3
    m = Image.new('L', (pw_ * ss, H * ss), 0)
    ImageDraw.Draw(m).polygon([(0, 0), (D_PANEL[0] * ss, 0), (D_PANEL[1] * ss, 0), (D_PANEL[2] * ss, H * ss), (0, H * ss)], fill=255)
    m = m.resize((pw_, H), Image.LANCZOS)
    pan.paste(g, (0, 0), m)
    # filo claro en la diagonal
    edge = Image.new('RGBA', (pw_, H), (0, 0, 0, 0)); de = Image.new('L', (pw_ * ss, H * ss), 0)
    ImageDraw.Draw(de).line([(D_PANEL[1] * ss, 0), (D_PANEL[2] * ss, H * ss)], fill=255, width=10 * ss)
    edge.paste(Image.new('RGBA', (pw_, H), lighten(col, 0.55) + (255,)), (0, 0), de.resize((pw_, H), Image.LANCZOS))
    pan.alpha_composite(edge)
    L['panel'] = pan
    L['bg_panel'] = L['bg'].copy(); L['bg_panel'].alpha_composite(pan)
    # círculo con borde blanco, fondo de color y "piso"
    s = 2; R = D_R; D = 2 * (R + 18)
    c = Image.new('RGBA', (D * s, D * s), (0, 0, 0, 0)); dc = ImageDraw.Draw(c)
    dc.ellipse((0, 0, D * s - 1, D * s - 1), fill=(255, 255, 255, 255))
    inner = Image.new('RGBA', (2 * R * s, 2 * R * s), lighten(col, 0.84) + (255,))
    di = ImageDraw.Draw(inner)
    fy = int(2 * R * s * 0.70)
    di.rectangle((0, fy, 2 * R * s, 2 * R * s), fill=lighten(col, 0.62) + (255,))
    di.ellipse((-R * s * 0.6, -R * s * 0.9, R * s * 1.1, R * s * 0.7), fill=lighten(col, 0.9) + (255,))   # brillo suave
    m = Image.new('L', inner.size, 0); ImageDraw.Draw(m).ellipse((0, 0, 2 * R * s - 1, 2 * R * s - 1), fill=255)
    inner.putalpha(m)
    c.alpha_composite(inner, (18 * s, 18 * s))
    L['circ'] = shadow(c.resize((D, D), Image.LANCZOS), blur=26, off=(0, 18), opacity=0.25, pad=70)[0]
    L['floor_y'] = D_CY - R + 2 * R * 0.70
    # producto (se asoma por arriba del círculo)
    prod = cut_cached(p['file'])
    sc = min(500 / prod.width, 470 / prod.height)
    L['dprod'] = shadow(prod.resize((int(prod.width * sc), int(prod.height * sc)), Image.LANCZOS),
                        blur=16, off=(0, 14), opacity=0.28, pad=50)[0]
    L['dprod_pad'] = 50
    # nombre gigante (máx. 2 renglones)
    name = ' '.join((p.get('name') or '').upper().replace('/', '/ ').split())
    fn = font(BLACK, 124)
    while fn.size > 56 and (len(wrap(fn, name, D_RW)) > 2 or any(text_w(fn, l) > D_RW for l in wrap(fn, name, D_RW))):
        fn = font(BLACK, fn.size - 4)
    if len(wrap(fn, name, D_RW)) > 2:                    # nombres muy largos: hasta 3 renglones
        while fn.size > 44 and (len(wrap(fn, name, D_RW)) > 3 or any(text_w(fn, l) > D_RW for l in wrap(fn, name, D_RW))):
            fn = font(BLACK, fn.size - 4)
    L['dname'] = []
    lineas = wrap(fn, name, D_RW)[:3]
    if len(lineas) == 2:                                 # renglones parejos: "ACEITE / DE OLIVO"
        pal = name.split()
        op = [(' '.join(pal[:i]), ' '.join(pal[i:])) for i in range(1, len(pal))]
        op = [o for o in op if max(text_w(fn, o[0]), text_w(fn, o[1])) <= D_RW]
        if op: lineas = list(min(op, key=lambda o: max(text_w(fn, o[0]), text_w(fn, o[1]))))
    for i, l in enumerate(lineas):
        im = text_layer(l, fn, NAVY if i == 0 else col)
        if im.width > D_RW + 20:                         # una sola palabra larguísima: se encoge
            im = im.resize((D_RW + 20, int(im.height * (D_RW + 20) / im.width)), Image.LANCZOS)
        L['dname'].append(im)
    sub = (p.get('sub') or '').upper()
    if sub and sub in name: sub = ''
    L['dsub'] = text_layer(sub, fit_font(SEMI, sub, D_RW, 30, 18), col) if sub else None
    # listón ladeado encimado al nombre
    txt = tag_txt(p.get('tag')) or 'PRECIO ESPECIAL'
    fb = fit_font(BLACK, txt, D_RW - 120, 54, 30)
    bw, bh = text_w(fb, txt) + 70, int(fb.size * 1.5)
    ban = Image.new('RGBA', (bw, bh), col + (255,)); ImageDraw.Draw(ban).text((bw / 2, bh / 2), txt, font=fb, fill='white', anchor='mm')
    L['banner'] = shadow(ban, blur=10, off=(0, 8), opacity=0.25, pad=30)[0]
    # descripción
    fd = font(SEMI, 38)
    L['ddesc'] = [text_layer(l, fd, (70, 76, 90)) for l in wrap(fd, p.get('desc') or '', D_RW)][:2]
    # palomitas
    fbn = font(BOLD, 34); L['chips'] = []
    for s_ in [b for b in p.get('bens', []) if b.strip()][:3]:
        w = min(text_w(fbn, s_) + 110, D_RW + 40); h = 70
        ch = Image.new('RGBA', (w, h), lighten(col, 0.88) + (255,)); ch.putalpha(rr_mask((w, h), 35))
        dr = ImageDraw.Draw(ch)
        dr.line([(30, 35), (40, 46), (60, 23)], fill=col + (255,), width=6, joint='curve')
        dr.text((76, h // 2), s_, font=fit_font(BOLD, s_, w - 100, 34, 24), fill=darken(col, 0.15), anchor='lm')
        L['chips'].append(ch)
    # etiqueta del precio (base sin número; el número se dibuja con contador)
    price = (p.get('price') or '').strip()
    L['pnum'], L['pdec'] = _num(price); L['ptxt'] = price
    TR = D_TR
    tg = Image.new('RGBA', (2 * TR * s, 2 * TR * s), (0, 0, 0, 0)); dt = ImageDraw.Draw(tg)
    dt.ellipse((0, 0, 2 * TR * s - 1, 2 * TR * s - 1), fill=DARK + (255,))
    dt.ellipse((10 * s, 10 * s, (2 * TR - 10) * s, (2 * TR - 10) * s), outline=(255, 255, 255, 70), width=3 * s)
    dt.ellipse(((TR - 11) * s, 16 * s, (TR + 11) * s, 38 * s), fill=(255, 255, 255, 255))           # ojillo
    L['tagbase'] = tg.resize((2 * TR, 2 * TR), Image.LANCZOS)
    L['f_lbl'] = font(BOLD, 30)
    L['f_price'] = fit_font(BLACK, '$' + price, 2 * TR - 80, 124, 48)
    L['f_dol'] = font(BLACK, int(L['f_price'].size * 0.5))
    unit = (p.get('unit') or '').strip()
    L['dunit'] = unit
    old = str(p.get('old_price') or '').strip().lstrip('$')
    L['dold'] = old
    return L


def _tag_img(L, value_text):
    """Etiqueta oscura con el precio (value_text va contando de 0 al precio)."""
    TR = D_TR
    im = L['tagbase'].copy(); dr = ImageDraw.Draw(im)
    lbl = ('ANTES $' + L['dold']) if L['dold'] else 'PRECIO'
    dr.text((TR, TR - 66), lbl, font=L['f_lbl'], fill=lighten(L['col'], 0.55) if not L['dold'] else (255, 170, 170), anchor='mm')
    if L['dold']:
        w = text_w(L['f_lbl'], lbl)
        dr.line((TR - w / 2, TR - 64, TR + w / 2, TR - 64), fill=(255, 90, 90), width=4)
    fp, fd = L['f_price'], L['f_dol']
    nb = fp.getbbox(value_text, anchor='ls')            # caja real del número (respecto a la línea base)
    db = fd.getbbox('$', anchor='ls')
    gap = 6
    total = (db[2] - db[0]) + gap + (nb[2] - nb[0])
    cy = TR + (2 if L['dunit'] else 14)                   # centro vertical del precio
    by = cy - (nb[1] + nb[3]) / 2                         # línea base para que el número quede centrado
    x0 = TR - total / 2
    dr.text((x0 - db[0], by + nb[1] - db[1]), '$', font=fd, fill='white', anchor='ls')   # "$" alineado arriba
    dr.text((x0 + (db[2] - db[0]) + gap - nb[0], by), value_text, font=fp, fill='white', anchor='ls')
    if L['dunit']:
        dr.text((TR, by + 38), L['dunit'], font=L['f_lbl'], fill=(200, 205, 215), anchor='mm')
    return im


def render_destacado(L, p, t):
    S = M.SLIDE
    out = ease_in_cubic((t - (S - 0.55)) / 0.55); vis = 1 - out
    col = L['col']
    # panel diagonal: aparece suave (fundido + pequeño deslizamiento) y al final se va igual; sin barrido
    k = ease_out_cubic(t / 0.6) * vis
    if k >= 0.999:
        fr = L['bg_panel'].copy()                        # ya quieto: fondo y panel en una sola capa
    else:
        fr = L['bg'].copy()
        if k > 0.005:
            fr.alpha_composite(M.with_alpha(L['panel'], k), (int(-120 * (1 - k)), 0))
    # círculo y producto
    dx = -300 * out
    a = ease_out_back((t - 0.1) / 0.8, 1.4)
    paste(fr, L['circ'], D_CX + dx, D_CY, min(1, max(a, 0)) * vis, scale=max(0.01, 0.6 + 0.4 * a))
    a = ease_out_back((t - 0.35) / 0.8, 1.3)
    fy = math.sin((t - 1.2) * 2 * math.pi / 3.4) * 7 * ease_out_cubic((t - 1.2) / 0.6)
    pr = L['dprod']
    bottom = L['floor_y'] + 30
    paste(fr, pr, D_CX + dx, bottom - pr.height / 2 + L['dprod_pad'] + 140 * (1 - min(a, 1)) + fy, min(1, max(a, 0)) * vis)
    # etiqueta del precio: cae colgando de su hilo, se columpia y cuenta de $0 al precio
    kt = ease_out_back((t - 0.8) / 0.6, 1.6)
    if kt > 0.01:
        tt = max(t - 1.3, 0)
        ang = 16 * math.exp(-tt * 1.3) * math.sin(tt * 5.2) + 3 * math.sin(t * 1.7) * ease_out_cubic(tt / 1.5)
        rad = math.radians(ang)
        Ls = D_STR * min(kt, 1.08)
        px, py = D_PIV[0] + dx, D_PIV[1]
        cx, cy = px + math.sin(rad) * Ls, py + math.cos(rad) * Ls
        hole = (cx - math.sin(rad) * (D_TR - 27), cy - math.cos(rad) * (D_TR - 27))
        dr = ImageDraw.Draw(fr)
        dr.line((px, py, hole[0], hole[1]), fill=(90, 96, 108, int(255 * vis)), width=4)
        dr.ellipse((px - 9, py - 9, px + 9, py + 9), fill=DARK)
        kc = ease_out_cubic((t - 0.9) / 0.6)
        if L['pnum'] is not None:
            v0 = _num(L['dold'])[0] or 0
            v = v0 + (L['pnum'] - v0) * kc
            txt = f"{v:,.{L['pdec']}f}" if ',' in L['ptxt'] else f"{v:.{L['pdec']}f}"
        else:
            txt = L['ptxt']
        bump = 1 + 0.08 * math.sin(min(max((t - 1.5) / 0.35, 0), 1) * math.pi)
        tg = _tag_img(L, txt).rotate(ang, resample=Image.BICUBIC, expand=True)
        paste(fr, shadow(tg, blur=12, off=(0, 10), opacity=0.3, pad=30)[0], cx, cy, min(1, kt) * vis, scale=bump)
    if 'extra' in L:
        a = ease_out_back((t - 2.4) / 0.5, 2.4)
        paste(fr, L['extra'], D_CX + D_R - 40 + dx, D_CY + D_R - 70, min(1, max(a, 0)) * vis, scale=max(a, 0.01) * 0.8)

    # columna de texto
    sx = 160 * out
    items = []
    if L['dsub']: items.append(('sub', L['dsub']))
    items += [('name', l) for l in L['dname']]
    items.append(('banner', L['banner']))
    items += [('desc', l) for l in L['ddesc']]
    hs = {'sub': lambda i: i.height - 4, 'name': lambda i: i.height - 22, 'banner': lambda i: i.height - 6,
          'desc': lambda i: i.height - 8}
    filas, xx = 1, D_X                                   # renglones que ocupan las palomitas
    for c in L['chips']:
        if xx + c.width > D_X + D_RW + 40 and xx > D_X: filas += 1; xx = D_X
        xx += c.width + 16
    total = sum(hs[k](i) for k, i in items) + ((24 + filas * 82) if L['chips'] else 0)
    y = max(140, min(500 - total / 2, 800 - total))
    for n_, (k, it) in enumerate(items):
        if k == 'banner':
            a = ease_out_back((t - 0.95) / 0.55, 2.0)
            rot = -4 - 8 * (1 - min(a, 1))
            if a >= 1:
                b = L.get('banner_rot') or L.setdefault('banner_rot', it.rotate(-4, resample=Image.BICUBIC, expand=True))
            else:
                b = it.rotate(rot, resample=Image.BICUBIC, expand=True)
            paste(fr, b, D_X + b.width / 2 - 34 + sx, y + 36 + it.height / 2 - 30, min(1, max(a, 0)) * vis, scale=max(a, 0.01))
        else:
            a = ease_out_cubic((t - (0.35 + 0.1 * n_)) / 0.6)
            paste(fr, it, D_X - 10 + sx, y - 30 * (1 - a), a * vis, anchor='tl')
        y += hs[k](it)
    if L['chips']:
        y += 24
        x = D_X
        for i, c in enumerate(L['chips']):
            if x + c.width > D_X + D_RW + 40 and x > D_X:
                x = D_X; y += c.height + 12
            a = ease_out_back((t - 1.5 - 0.15 * i) / 0.5, 1.6)
            paste(fr, c, x + c.width / 2 + sx, y + c.height / 2 + 20 * (1 - min(a, 1)), min(1, max(a, 0)) * vis,
                  scale=max(0.01, 0.85 + 0.15 * min(a, 1)))
            x += c.width + 16
    return finish(fr)


# =====================================================================
#  CORTINILLA  (mitad y mitad: medicina a la izquierda, información a la derecha)
# =====================================================================
SPLIT = 960


def alpha_mul(im, a):
    im = im.copy(); im.putalpha(im.split()[3].point(lambda v: int(v * a))); return im


def white_check(size=54):
    ic = Image.new('RGBA', (180, 180), (0, 0, 0, 0)); di = ImageDraw.Draw(ic)
    di.ellipse((6, 6, 174, 174), outline=(255, 255, 255, 255), width=10)
    di.line([(52, 94), (80, 122), (130, 66)], fill=(255, 255, 255, 255), width=16, joint='curve')
    return ic.resize((size, size), Image.LANCZOS)


def tag_txt(tag):
    """Texto de la etiqueta en mayúsculas, pero '2x1' / '3x2' se quedan como se escriben."""
    import re
    t = ' '.join((tag or '').split())
    return re.sub(r'[a-zñáéíóú]+', lambda m: m.group(0) if m.group(0) == 'x' else m.group(0).upper(), t)


def sello(tag, col=(220, 38, 50), R=104):
    """Sello redondo con picos (OFERTA, 2x1, DESCUENTO…), rojo con aro blanco."""
    s = 3; D = 2 * R
    n = 22
    pts = []
    for i in range(2 * n):
        r = R if i % 2 == 0 else R * 0.88
        a = math.pi * i / n - math.pi / 2
        pts.append((R * s + math.cos(a) * r * s, R * s + math.sin(a) * r * s))
    m = Image.new('L', (D * s, D * s), 0); ImageDraw.Draw(m).polygon(pts, fill=255)
    im = vgrad((D * s, D * s), lighten(col, 0.12), darken(col, 0.15)).convert('RGBA'); im.putalpha(m)
    dr = ImageDraw.Draw(im)
    ri = R * 0.74 * s
    dr.ellipse((R * s - ri, R * s - ri, R * s + ri, R * s + ri), outline=(255, 255, 255, 230), width=4 * s)
    words = tag.split()
    lines = [tag] if len(words) < 2 or len(tag) <= 9 else [' '.join(words[:len(words) // 2]), ' '.join(words[len(words) // 2:])]
    size = 50
    while size > 18 and max(text_w(font(BLACK, size), l) for l in lines) > R * 1.3: size -= 2
    f = font(BLACK, size * s)
    lh = size * 1.05 * s
    for i, l in enumerate(lines):
        dr.text((R * s, R * s + (i - (len(lines) - 1) / 2) * lh), l, font=f, fill='white', anchor='mm')
    return shadow(im.resize((D, D), Image.LANCZOS), blur=12, off=(0, 8), opacity=0.3, pad=30)[0]


def poner_sello(fr, L, t, x, y, vis, start=1.0):
    """El sello entra girando con rebote y luego se mece suave."""
    if 'sello' not in L: return
    k = ease_out_back((t - start) / 0.6, 2.2)
    if k <= 0.01: return
    rot = -14 - 200 * (1 - min(k, 1)) + math.sin((t - start) * 2.2) * 4 * min(1, max(k, 0))
    tg = L['sello'].rotate(rot, resample=Image.BICUBIC, expand=True)
    paste(fr, tg, x, y, min(1, max(k, 0)) * vis, scale=max(k, 0.01))


def build_cortinilla(p):
    L = M.build(p)
    if (p.get('tag') or '').strip():
        L['sello'] = sello(tag_txt(p.get('tag')))
    col = color_of(p)
    while 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2] > 125:      # que el texto blanco se lea
        col = darken(col, 0.12)
    L['col'] = col
    prod = cut_cached(p['file'])
    sc = min(720 / prod.width, 600 / prod.height)
    L['cprod'] = shadow(prod.resize((int(prod.width * sc), int(prod.height * sc)), Image.LANCZOS),
                        blur=24, off=(0, 20), opacity=0.22, pad=60)[0]
    panel = vgrad((W - SPLIT, H), lighten(col, 0.06), darken(col, 0.16)).convert('RGBA')
    ImageDraw.Draw(panel).ellipse((560, -300, 1400, 540), fill=lighten(col, 0.12) + (255,))
    L['panel'] = panel.filter(ImageFilter.GaussianBlur(2))
    edge = Image.new('RGBA', (50, H), (0, 0, 0, 0)); de = ImageDraw.Draw(edge)
    for x in range(50): de.line((x, 0, x, H), fill=(0, 0, 0, int(50 * (x / 50) ** 2)))
    L['edge'] = edge
    RW = 780
    # precio grande en blanco
    pr, unit = p['price'], p.get('unit') or ''
    fp = fit_font(BLACK, '$' + pr + ' ' + unit, RW - 40, 200, 100)
    fd = font(BLACK, int(fp.size * 0.42)); fu = font(SEMI, int(fp.size * 0.24))
    wp, wd = text_w(fp, pr), text_w(fd, '$'); wu = text_w(fu, unit) if unit else 0
    bb = fp.getbbox(pr)
    im = Image.new('RGBA', (wd + 12 + wp + (wu + 16 if unit else 0) + 20, bb[3] + 16), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(im)
    d2.text((0, bb[1] + 4), '$', font=fd, fill='white')
    d2.text((wd + 12 - bb[0], 0), pr, font=fp, fill='white')
    if unit: d2.text((wd + 12 + wp + 16, bb[3] - fu.size * 1.2), unit, font=fu, fill=(255, 255, 255, 225))
    L['cprice'] = im
    old = str(p.get('old_price') or '').strip().lstrip('$')
    if old:
        fo = font(SEMI, 40); s = 'ANTES $' + old
        o = alpha_mul(text_layer(s, fo, (255, 255, 255)), 0.8)
        y_ = o.height // 2 + 4
        ImageDraw.Draw(o).line((10 + text_w(fo, 'ANTES '), y_, 10 + text_w(fo, s), y_), fill=(255, 255, 255, 235), width=4)
        L['cold'] = o
    sub = (p.get('sub') or '').upper()
    L['csub'] = alpha_mul(text_layer(sub, fit_font(SEMI, sub, RW, 28, 18), (255, 255, 255)), 0.85) if sub else None
    fn = font(BLACK, 74)
    while fn.size > 44 and (len(wrap(fn, p['name'], RW)) > 2 or any(text_w(fn, l) > RW for l in wrap(fn, p['name'], RW))):
        fn = font(BLACK, fn.size - 4)
    L['cname'] = [text_layer(l, fn, (255, 255, 255)) for l in wrap(fn, p['name'], RW)]
    L['cpres'] = [alpha_mul(text_layer(x, font(REG, 30), (255, 255, 255)), 0.85) for x in p.get('pres', []) if x.strip()]
    fdsc = font(REG, 32)
    L['cdesc'] = [text_layer(l, fdsc, (255, 255, 255)) for l in wrap(fdsc, p.get('desc') or '', RW)][:2]
    L['cbens'] = M.bens_row([b for b in p.get('bens', []) if b.strip()][:3], white_check(50), 255, 70,
                            (255, 255, 255, 255), start=24, minimum=16)
    return L


def render_cortinilla(L, p, t):
    S = M.SLIDE
    fr = base_frame()
    out = ease_in_cubic((t - (S - 0.6)) / 0.6); vis = 1 - out
    RX0 = SPLIT + 80

    # medicina entra desde la izquierda
    a = ease_out_cubic((t - 0.25) / 0.8)
    fy = math.sin((t - 1) * 2 * math.pi / 3.4) * 8 * ease_out_cubic((t - 1.2) / 0.6)
    paste(fr, L['cprod'], SPLIT / 2 - 200 * (1 - a) - 300 * out, 560 + fy, a * vis)
    # sello de promoción en la esquina de arriba a la derecha del producto (sin taparlo)
    pw, ph = L['cprod'].width, L['cprod'].height
    poner_sello(fr, L, t, min(SPLIT / 2 + pw / 2 - 40, SPLIT - 140) - 300 * out, max(560 - ph / 2 + 20, 230), vis, 1.1)

    # el panel de color aparece suave (fundido + pequeño deslizamiento) y al final se va igual; sin barrido
    k = ease_out_cubic(t / 0.6) * (1 - ease_in_cubic((t - (S - 0.5)) / 0.5))
    if k > 0.005:
        x0 = int(SPLIT + 120 * (1 - k))
        pan, edge = L['panel'].crop((0, 0, W - x0, H)), L['edge']
        if k < 0.999:
            pan, edge = M.with_alpha(pan, k), M.with_alpha(edge, k)
        fr.alpha_composite(edge, (max(x0 - 50, 0), 0))
        fr.alpha_composite(pan, (x0, 0))

    def put(layer, y, start, dy=36):
        a = ease_out_cubic((t - start) / 0.55)
        paste(fr, layer, RX0 + 60 * out, y + dy * (1 - a), a * vis, anchor='tl')

    blocks = []
    if 'cold' in L: blocks.append(('old', L['cold'], -2))
    blocks.append(('price', L['cprice'], 14))
    if L['csub']: blocks.append(('t', L['csub'], -4))
    blocks += [('t', l, -16) for l in L['cname']]
    blocks.append(('gap', None, 6))
    blocks += [('t', l, -10) for l in L['cpres']]
    if L['cdesc']: blocks += [('gap', None, 18), ('line', None, 22)]
    blocks += [('t', l, -8) for l in L['cdesc']]
    if L['cbens']: blocks += [('gap', None, 22), ('bens', None, 0)]
    hh = {'gap': 0, 'line': 6, 'bens': 66}
    total = sum((hh[k_] if k_ in hh else it.height) + g for k_, it, g in blocks)
    y = max(175, 535 - total / 2)
    for i, (k_, it, g) in enumerate(blocks):
        st = 0.7 + 0.08 * i
        if k_ == 'price':
            pa = ease_out_back((t - 0.75) / 0.6, 1.8)
            paste(fr, it, RX0 - 6 + 60 * out, y, min(1, max(pa, 0)) * vis, anchor='tl')
            if 'extra' in L:
                ka = ease_out_back((t - 1.4) / 0.5, 2.4)
                paste(fr, L['extra'], min(RX0 + it.width + 90, 1810), y + it.height / 2, min(1, max(ka, 0)) * vis,
                      scale=max(ka, 0.01) * 0.85)
        elif k_ == 'line':
            la = ease_out_cubic((t - st) / 0.5)
            if la > 0.01:
                paste(fr, Image.new('RGBA', (max(2, int(130 * la)), 6), (255, 255, 255, 230)), RX0, y + 6, vis, anchor='tl')
        elif k_ == 'bens':
            for j, b in enumerate(L['cbens']):
                ba = ease_out_back((t - st - 0.12 * j) / 0.5, 1.6)
                paste(fr, b, RX0 - 4 + j * 265 + 60 * out, y + 20 * (1 - min(ba, 1)), min(1, max(ba, 0)) * vis, anchor='tl')
        elif it is not None:
            put(it, y, st)
        y += (hh[k_] if k_ in hh else it.height) + g
    return finish(fr, pos=M.logo_pos_for('cortinilla'))


# =====================================================================
#  MINIMAL  (blanco, mucho aire, tipografía grande, sin recuadros)
# =====================================================================
def build_minimal(p):
    L = M.build(p)
    col = color_of(p); L['col'] = col
    prod = cut_cached(p['file'])
    sc = min(700 / prod.width, 580 / prod.height)
    L['mprod'] = shadow(prod.resize((int(prod.width * sc), int(prod.height * sc)), Image.LANCZOS),
                        blur=22, off=(0, 18), opacity=0.18, pad=60)[0]
    d = 760
    disc = Image.new('RGBA', (d * 2, d * 2), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((0, 0, d * 2 - 1, d * 2 - 1), fill=lighten(col, 0.92) + (255,))
    L['mdisc'] = disc.resize((d, d), Image.LANCZOS)
    RW = 720
    dark = (31, 41, 55)
    sub = (p.get('sub') or '').upper()
    L['msub'] = text_layer(sub, fit_font(SEMI, sub, RW, 28, 18), col) if sub else None
    fn = font(BLACK, 92)
    while fn.size > 48 and (len(wrap(fn, p['name'], RW)) > 2 or any(text_w(fn, l) > RW for l in wrap(fn, p['name'], RW))):
        fn = font(BLACK, fn.size - 4)
    L['mname'] = [text_layer(l, fn, dark) for l in wrap(fn, p['name'], RW)]
    fdsc = font(REG, 34)
    L['mdesc'] = [text_layer(l, fdsc, (90, 96, 108)) for l in wrap(fdsc, p.get('desc') or '', RW)][:2]
    pres = ' · '.join(x for x in p.get('pres', []) if x.strip())
    L['mpres'] = text_layer(pres, fit_font(REG, pres, RW, 28, 20), (120, 126, 138)) if pres else None
    pr, unit = p['price'], p.get('unit') or ''
    fp = font(BLACK, 170); fd = font(BLACK, 72); fu = font(SEMI, 40)
    wp, wd = text_w(fp, pr), text_w(fd, '$'); wu = text_w(fu, unit) if unit else 0
    bb = fp.getbbox(pr)
    im = Image.new('RGBA', (wd + 10 + wp + (wu + 18 if unit else 0) + 20, bb[3] + 20), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(im)
    d2.text((0, bb[1] + 6), '$', font=fd, fill=col)
    d2.text((wd + 10 - bb[0], 0), pr, font=fp, fill=col)
    if unit: d2.text((wd + 10 + wp + 18, bb[3] - 52), unit, font=fu, fill=(120, 126, 138))
    L['mprice'] = im
    old = str(p.get('old_price') or '').strip().lstrip('$')
    if old:
        fo = font(SEMI, 40); s = 'Antes $' + old
        o = text_layer(s, fo, (150, 155, 165)); y_ = o.height // 2 + 4
        ImageDraw.Draw(o).line((10, y_, 10 + text_w(fo, s), y_), fill=(220, 40, 50, 255), width=4)
        L['mold'] = o
    tag = (p.get('tag') or '').strip().upper()
    if tag:
        ft = font(BOLD, 26); tw, th = text_w(ft, tag) + 44, 48
        tg = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(tg).rounded_rectangle((1, 1, tw - 2, th - 2), 24, outline=col + (255,), width=3)
        ImageDraw.Draw(tg).text((tw // 2, th // 2 - 1), tag, font=ft, fill=col, anchor='mm')
        L['mtag'] = tg
    return L


def render_minimal(L, p, t):
    S = M.SLIDE
    fr = base_frame()
    out = ease_in_cubic((t - (S - 0.6)) / 0.6); vis = 1 - out
    a = ease_out_cubic(t / 0.9)
    paste(fr, L['mdisc'], 620, 520, a * vis, scale=0.9 + 0.1 * a)
    a = ease_out_cubic((t - 0.2) / 0.9)
    fy = math.sin((t - 1) * 2 * math.pi / 4) * 7 * ease_out_cubic((t - 1.2) / 0.6)
    paste(fr, L['mprod'], 620, 520 + 30 * (1 - a) + fy, a * vis, scale=0.94 + 0.06 * a)

    X = 1110
    items = []
    if 'mtag' in L: items.append((L['mtag'], 22))
    if L['msub']: items.append((L['msub'], 0))
    items += [(l, -14) for l in L['mname']]
    items[-1] = (items[-1][0], 14)            # aire entre el nombre y la línea de color
    items.append(('line', 26))
    items += [(l, -6) for l in L['mdesc']]
    if L['mpres']: items.append((L['mpres'], 18))
    if 'mold' in L: items.append((L['mold'], -10))
    items.append((L['mprice'], 0))
    total = sum((8 if isinstance(it, str) else it.height) + g for it, g in items)
    y = max(170, 540 - total / 2)
    for i, (it, g) in enumerate(items):
        st = 0.45 + 0.09 * i
        if isinstance(it, str):
            k = ease_out_cubic((t - st) / 0.6)
            if k > 0.01:
                ln = Image.new('RGBA', (int(110 * k) + 2, 8), L['col'] + (255,)); ln.putalpha(rr_mask(ln.size, 4))
                paste(fr, ln, X + 6, y + 8, vis, anchor='tl')
            y += 8 + g; continue
        if it is L['mprice']:
            k = ease_out_cubic((t - (st + 0.2)) / 0.7)
            paste(fr, it, X, y + 30 * (1 - k), k * vis, anchor='tl')
        else:
            k = ease_out_cubic((t - st) / 0.6)
            paste(fr, it, X - 30 * out, y + 30 * (1 - k), k * vis, anchor='tl')
        y += it.height + g
    if 'extra' in L:
        k = ease_out_back((t - 1.9) / 0.5, 2.2)
        paste(fr, L['extra'], min(X + L['mprice'].width + 110, 1800), y - L['mprice'].height / 2,
              min(1, max(k, 0)) * vis, scale=max(k, 0.01) * 0.85)
    return finish(fr)


# =====================================================================
#  TERMINAL  (anuncio: "Aceptamos todas las tarjetas" — terminal de pago animada)
# =====================================================================
MARCAS = {'visa': 'Visa', 'mastercard': 'Mastercard', 'amex': 'American Express', 'carnet': 'Carnet'}


def _card_base(w, h, fill, s=3, outline=(222, 228, 238)):
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, w * s - 1, h * s - 1), 18 * s, fill=fill + (255,),
                                         outline=outline + (255,) if outline else None, width=3 * s)
    return im


def marca_badge(k, w=190, h=120):
    """Distintivo de la marca de tarjeta (para el anuncio de pago con terminal)."""
    s = 3
    if k == 'amex':
        im = _card_base(w, h, (0, 111, 207), s, None); dr = ImageDraw.Draw(im)
        f = font('Montserrat-ExtraBold.ttf', 25 * s)
        dr.text((w * s / 2, h * s / 2 - 17 * s), 'AMERICAN', font=f, fill='white', anchor='mm')
        dr.text((w * s / 2, h * s / 2 + 17 * s), 'EXPRESS', font=f, fill='white', anchor='mm')
    else:
        im = _card_base(w, h, (255, 255, 255), s); dr = ImageDraw.Draw(im)
        if k == 'visa':
            dr.text((w * s / 2, h * s / 2 - 4 * s), 'VISA', font=font('Montserrat-ExtraBoldItalic.ttf', 54 * s), fill=(26, 31, 113), anchor='mm')
            dr.rounded_rectangle((w * s * .2, h * s * .8, w * s * .8, h * s * .8 + 6 * s), 3 * s, fill=(247, 182, 0))
        elif k == 'mastercard':
            r = 30 * s; cy = h * s / 2 - 10 * s; cx = w * s / 2
            c1 = (cx - 22 * s - r, cy - r, cx - 22 * s + r, cy + r)
            c2 = (cx + 22 * s - r, cy - r, cx + 22 * s + r, cy + r)
            dr.ellipse(c1, fill=(235, 0, 27))
            dr.ellipse(c2, fill=(247, 158, 27))
            m1 = Image.new('L', im.size, 0); ImageDraw.Draw(m1).ellipse(c1, fill=255)
            m2 = Image.new('L', im.size, 0); ImageDraw.Draw(m2).ellipse(c2, fill=255)
            mid = Image.new('RGBA', im.size, (255, 95, 0, 255)); mid.putalpha(ImageChops.multiply(m1, m2))
            im.alpha_composite(mid)
            dr = ImageDraw.Draw(im)
            dr.text((cx, h * s - 22 * s), 'mastercard', font=font(BOLD, 19 * s), fill=(35, 35, 40), anchor='mm')
        elif k == 'carnet':
            dr.text((w * s / 2, h * s / 2 - 6 * s), 'Carnet', font=font('Montserrat-ExtraBold.ttf', 40 * s), fill=(0, 76, 151), anchor='mm')
            dr.rounded_rectangle((w * s * .25, h * s * .74, w * s * .5, h * s * .74 + 7 * s), 3 * s, fill=(220, 30, 50))
            dr.rounded_rectangle((w * s * .5, h * s * .74, w * s * .75, h * s * .74 + 7 * s), 3 * s, fill=(0, 76, 151))
        else:
            dr.text((w * s / 2, h * s / 2), MARCAS.get(k, k), font=font(BOLD, 28 * s), fill=NAVY, anchor='mm')
    im = im.resize((w, h), Image.LANCZOS)
    return shadow(im, blur=12, off=(0, 8), opacity=0.18, pad=50)[0]


def _contactless(size, col, width, n=3):
    s = 3; D = size * s
    im = Image.new('RGBA', (D, D), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    for i in range(n):
        r = D * (0.22 + 0.24 * i)
        dr.arc((D * .1 - r, D / 2 - r, D * .1 + r, D / 2 + r), -50, 50, fill=col + (255,), width=width * s)
    return im.resize((size, size), Image.LANCZOS)


TERM_W, TERM_H = 380, 640


def _terminal_body():
    """Terminal de pago (sin pantalla; la pantalla se dibuja aparte para animarla)."""
    s = 2; w, h = TERM_W, TERM_H
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
    body = vgrad((w * s, h * s), (70, 77, 96), (28, 32, 42)).convert('RGBA')
    body.putalpha(rr_mask((w * s, h * s), 56 * s, 1))
    im.alpha_composite(body)
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((26 * s, 34 * s, (w - 26) * s, 300 * s), 26 * s, fill=(18, 21, 28))       # marco de la pantalla
    kw, kh, gx, gy, x0, y0 = 88, 46, 18, 16, 44, 330
    labels = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', '']
    for i, lb in enumerate(labels):
        cx, cy = x0 + (i % 3) * (kw + gx), y0 + (i // 3) * (kh + gy)
        dr.rounded_rectangle((cx * s, cy * s, (cx + kw) * s, (cy + kh) * s), 12 * s, fill=(86, 94, 116))
        if lb: dr.text(((cx + kw / 2) * s, (cy + kh / 2) * s), lb, font=font(BOLD, 24 * s), fill=(235, 238, 245), anchor='mm')
    yb = y0 + 4 * (kh + gy)
    for i, c in enumerate([(220, 50, 60), (240, 190, 40), (40, 170, 90)]):
        cx = x0 + i * (kw + gx)
        dr.rounded_rectangle((cx * s, yb * s, (cx + kw) * s, (yb + kh) * s), 12 * s, fill=c)
    im = im.resize((w, h), Image.LANCZOS)
    return shadow(im, blur=26, off=(0, 22), opacity=0.32, pad=110)[0]


def _screen(ok):
    s = 2; w, h = 300, 236
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
    c1, c2 = ((226, 248, 234), (196, 238, 210)) if ok else ((232, 240, 252), (205, 220, 242))
    bg = vgrad((w * s, h * s), c1, c2).convert('RGBA')
    bg.putalpha(rr_mask((w * s, h * s), 16 * s, 1)); im.alpha_composite(bg)
    dr = ImageDraw.Draw(im)
    if ok:
        col = (22, 150, 70); r = 46 * s; cx, cy = w * s / 2, 90 * s
        dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        dr.line([(cx - 22 * s, cy + 2 * s), (cx - 6 * s, cy + 18 * s), (cx + 24 * s, cy - 16 * s)], fill='white', width=11 * s, joint='curve')
        dr.text((cx, 186 * s), 'APROBADO', font=font(BLACK, 34 * s), fill=col, anchor='mm')
    else:
        ic = _contactless(90 * s, NAVY, 7)
        im.alpha_composite(ic, (int(w * s / 2 - 22 * s), int(22 * s)))
        dr.text((w * s / 2, 150 * s), 'Acerque o inserte', font=font(BOLD, 24 * s), fill=NAVY, anchor='mm')
        dr.text((w * s / 2, 182 * s), 'su tarjeta', font=font(BOLD, 24 * s), fill=NAVY, anchor='mm')
    return im.resize((w, h), Image.LANCZOS)


def _tarjeta():
    s = 3; w, h = 330, 208
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
    g = hgrad((w * s, h * s), BLUE, NAVY).convert('RGBA'); g.putalpha(rr_mask((w * s, h * s), 22 * s, 1))
    im.alpha_composite(g)
    gl = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).ellipse((w * s * .55, -h * s * .4, w * s * 1.3, h * s * .7), fill=(255, 255, 255, 30))
    gl.putalpha(ImageChops.multiply(gl.split()[3], rr_mask((w * s, h * s), 22 * s, 1)))
    im.alpha_composite(gl)
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((30 * s, 62 * s, 82 * s, 102 * s), 8 * s, fill=(232, 196, 100))            # chip
    for yy in (75, 89): dr.line((30 * s, yy * s, 82 * s, yy * s), fill=(190, 150, 60), width=2 * s)
    im.alpha_composite(_contactless(40 * s, (255, 255, 255), 4), (int(100 * s), int(62 * s)))
    dr.text((30 * s, 152 * s), '••••  ••••  ••••  2024', font=font(BOLD, 22 * s), fill='white', anchor='lm')
    im = im.resize((w, h), Image.LANCZOS)
    return shadow(im, blur=18, off=(0, 14), opacity=0.3, pad=75)[0]


def _chips(texts):
    icon = check_icon(BLUE, 56)
    out = []
    for tx in texts:
        f = font(BOLD, 30)
        w = icon.width + 14 + text_w(f, tx) + 36
        im = Image.new('RGBA', (w, 72), (0, 0, 0, 0))
        bg = Image.new('RGBA', (w, 72), lighten(BLUE, 0.9) + (255,)); bg.putalpha(rr_mask((w, 72), 36))
        im.alpha_composite(bg); im.alpha_composite(icon, (8, 8))
        ImageDraw.Draw(im).text((8 + icon.width + 12, 36), tx, font=f, fill=NAVY, anchor='lm')
        out.append(im)
    return out


def build_terminal(p):
    if p.get('diseno') == 'abanico': return build_abanico(p)
    if p.get('diseno') == 'contacto': return build_contacto(p)
    if p.get('diseno') == 'persona': return build_persona(p)
    L = {'body': _terminal_body(), 'scr_wait': _screen(False), 'scr_ok': _screen(True),
         'card': _tarjeta(), 'waves': _contactless(130, BLUE, 8)}
    d = 760
    disc = Image.new('RGBA', (d * 2, d * 2), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((0, 0, d * 2 - 1, d * 2 - 1), fill=lighten(BLUE, 0.9) + (255,))
    L['disc'] = disc.resize((d, d), Image.LANCZOS)
    RW = 820
    titulo = (p.get('titulo') or 'Aceptamos todas las tarjetas').upper()
    fn = font(BLACK, 92)
    while fn.size > 50 and (len(wrap(fn, titulo, RW)) > 3 or any(text_w(fn, l) > RW for l in wrap(fn, titulo, RW))):
        fn = font(BLACK, fn.size - 4)
    L['title'] = [text_layer(l, fn, NAVY) for l in wrap(fn, titulo, RW)]
    sub = (p.get('subtitulo') or '').strip()
    fs = font(SEMI, 38)
    while fs.size > 24 and len(wrap(fs, sub, RW)) > 2: fs = font(SEMI, fs.size - 2)
    L['sub'] = [text_layer(l, fs, (90, 96, 108)) for l in wrap(fs, sub, RW)][:2] if sub else []
    ln = Image.new('RGBA', (130, 10), BLUE + (255,)); ln.putalpha(rr_mask(ln.size, 5)); L['line'] = ln
    L['marcas'] = [marca_badge(k) for k in (p.get('marcas') or list(MARCAS)) if k in MARCAS][:4]
    L['chips'] = _chips([c.strip() for c in (p.get('chips') or []) if (c or '').strip()][:3])
    return L


def render_terminal(L, p, t):
    if L.get('diseno') == 'abanico': return render_abanico(L, p, t)
    if L.get('diseno') == 'contacto': return render_contacto(L, p, t)
    if L.get('diseno') == 'persona': return render_persona(L, p, t)
    S = M.SLIDE
    fr = base_frame()
    out = ease_in_cubic((t - (S - 0.6)) / 0.6); vis = 1 - out
    TX, TY = 470, 515
    a = ease_out_cubic(t / 0.9)
    paste(fr, L['disc'], TX + 20 - 300 * out, TY, a * vis, scale=0.88 + 0.12 * a)
    # terminal: sube con rebote y flota suave
    a = ease_out_back((t - 0.1) / 0.9, 1.3)
    fy = math.sin((t - 1.2) * 2 * math.pi / 3.4) * 8 * ease_out_cubic((t - 1.2) / 0.6)
    bx, by = TX - 300 * out, TY + 200 * (1 - min(a, 1)) + fy
    al = min(1, max(a, 0)) * vis
    paste(fr, L['body'], bx, by, al)
    scx, scy = bx, by - TERM_H / 2 + 34 + 133           # centro de la pantalla (dentro del marco)
    ok = ease_out_cubic((t - 2.3) / 0.35)
    paste(fr, L['scr_wait'], scx, scy, al * (1 - ok))
    if ok > 0:
        paste(fr, L['scr_ok'], scx, scy, al * ok, scale=0.94 + 0.06 * min(1, ease_out_back((t - 2.3) / 0.5, 2)))
    # ondas de "sin contacto" mientras la tarjeta toca la terminal
    for i in range(3):
        ph = (t - 1.5) / 1.0 - i * 0.3
        if 0 < ph < 1 and t < 3.0:
            paste(fr, L['waves'], bx + 40, by - TERM_H / 2 - 30, (1 - ph) * vis * 0.9, scale=0.6 + 0.8 * ph)
    # tarjeta: llega desde arriba a la derecha, "toca" la terminal y se queda flotando
    k = ease_out_cubic((t - 0.8) / 0.8)
    tap = math.sin(min(max((t - 1.6) / 0.6, 0), 1) * math.pi) * 30
    cx = bx + 175 + 360 * (1 - k)
    cy = by - TERM_H / 2 - 40 - 300 * (1 - k) + tap + fy * 0.6
    if k > 0.01:
        card = L['card'].rotate(14 - 10 * (1 - k), resample=Image.BICUBIC, expand=True)
        paste(fr, card, cx, cy, min(1, k) * vis)

    _texto_derecha(fr, L, t, out, vis)
    return finish(fr)


def _texto_derecha(fr, L, t, out, vis):
    # textos a la derecha
    X, sx = 1000, 160 * out
    items = [(l, -10) for l in L['title']]
    items[-1] = (items[-1][0], 18)
    items.append(('line', 26))
    items += [(l, -4) for l in L['sub']]
    th = sum((10 if isinstance(i, str) else i.height) + g for i, g in items)
    mh = max([m.height for m in L['marcas']] or [0])
    total = th + mh - 58 + (72 if L['chips'] else 0)
    y = max(160, 490 - total / 2)
    for i, (it, g) in enumerate(items):
        kk = ease_out_cubic((t - (0.35 + 0.1 * i)) / 0.6)
        if isinstance(it, str):
            if kk > 0.01:
                paste(fr, L['line'].crop((0, 0, max(2, int(130 * kk)), 10)), X + 10 + sx, y, vis, anchor='tl')
            y += 10 + g; continue
        paste(fr, it, X + 60 * (1 - kk) + sx, y, kk * vis, anchor='tl')
        y += it.height + g
    x = X - 40
    y -= 24                               # margen de la sombra de las marcas
    for i, m in enumerate(L['marcas']):
        kk = ease_out_back((t - 1.0 - i * 0.16) / 0.55, 2.0)
        bob = math.sin((t - 2 - i * 0.4) * 2 * math.pi / 2.6) * 4 * ease_out_cubic((t - 2) / 0.5)
        paste(fr, m, x + m.width / 2 + sx, y + m.height / 2 + bob, min(1, max(kk, 0)) * vis, scale=max(kk, 0.01))
        x += m.width - 82
    y += mh - 34
    x = X + 6
    for i, c in enumerate(L['chips']):
        kk = ease_out_back((t - 1.9 - i * 0.18) / 0.5, 1.6)
        paste(fr, c, x + sx, y + 30 * (1 - min(kk, 1)), min(1, max(kk, 0)) * vis, anchor='tl')
        x += c.width + 18


# ---------- diseños extra del anuncio de pago con tarjeta ----------
DISENOS_TERMINAL = {'terminal': 'Terminal', 'abanico': 'Abanico de tarjetas', 'contacto': 'Sin contacto'}

_CARD_LOOK = {
    'visa': ((26, 31, 113), (52, 86, 190)),
    'mastercard': ((30, 32, 40), (70, 74, 88)),
    'amex': ((0, 92, 170), (40, 150, 220)),
    'carnet': ((0, 120, 110), (40, 170, 140)),
}


def tarjeta_marca(k, w=420, h=264):
    """Tarjeta grande con el distintivo de la marca (para el abanico)."""
    s = 2
    c1, c2 = _CARD_LOOK.get(k, (NAVY, BLUE))
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
    g = hgrad((w * s, h * s), c1, c2).convert('RGBA'); g.putalpha(rr_mask((w * s, h * s), 28 * s, 1))
    im.alpha_composite(g)
    gl = Image.new('RGBA', im.size, (0, 0, 0, 0))
    ImageDraw.Draw(gl).ellipse((w * s * .5, -h * s * .5, w * s * 1.4, h * s * .8), fill=(255, 255, 255, 26))
    gl.putalpha(ImageChops.multiply(gl.split()[3], rr_mask((w * s, h * s), 28 * s, 1)))
    im.alpha_composite(gl)
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((36 * s, 84 * s, 100 * s, 132 * s), 10 * s, fill=(232, 196, 100))
    for yy in (100, 116): dr.line((36 * s, yy * s, 100 * s, yy * s), fill=(190, 150, 60), width=2 * s)
    im.alpha_composite(_contactless(46 * s, (255, 255, 255), 4), (int(118 * s), int(84 * s)))
    dr.text((36 * s, 196 * s), '••••  ••••  ••••  2024',
            font=font(BOLD, 24 * s), fill=(255, 255, 255, 230), anchor='lm')
    X, Y = (w - 36) * s, (h - 44) * s                       # marca abajo a la derecha
    if k == 'visa':
        dr.text((X, Y), 'VISA', font=font('Montserrat-ExtraBoldItalic.ttf', 50 * s), fill='white', anchor='rm')
    elif k == 'mastercard':
        r = 30 * s
        c1_ = (X - 92 * s, Y - r, X - 92 * s + 2 * r, Y + r); c2_ = (X - 2 * r, Y - r, X, Y + r)
        dr.ellipse(c1_, fill=(235, 0, 27)); dr.ellipse(c2_, fill=(247, 158, 27))
        m1 = Image.new('L', im.size, 0); ImageDraw.Draw(m1).ellipse(c1_, fill=255)
        m2 = Image.new('L', im.size, 0); ImageDraw.Draw(m2).ellipse(c2_, fill=255)
        mid = Image.new('RGBA', im.size, (255, 95, 0, 255)); mid.putalpha(ImageChops.multiply(m1, m2)); im.alpha_composite(mid)
    elif k == 'amex':
        f = font('Montserrat-ExtraBold.ttf', 24 * s)
        dr.text((X, Y - 16 * s), 'AMERICAN', font=f, fill='white', anchor='rm')
        dr.text((X, Y + 14 * s), 'EXPRESS', font=f, fill='white', anchor='rm')
    elif k == 'carnet':
        dr.text((X, Y), 'Carnet', font=font('Montserrat-ExtraBold.ttf', 40 * s), fill='white', anchor='rm')
    im = im.resize((w, h), Image.LANCZOS)
    return shadow(im, blur=20, off=(0, 16), opacity=0.3, pad=70)[0]


def _titulo(p, RW, start=92, lines=3, col=NAVY, center=False):
    titulo = (p.get('titulo') or 'Aceptamos todas las tarjetas').upper()
    fn = font(BLACK, start)
    while fn.size > 44 and (len(wrap(fn, titulo, RW)) > lines or any(text_w(fn, l) > RW for l in wrap(fn, titulo, RW))):
        fn = font(BLACK, fn.size - 4)
    return [text_layer(l, fn, col) for l in wrap(fn, titulo, RW)]


def _subt(p, RW, size=38, col=(90, 96, 108)):
    sub = (p.get('subtitulo') or '').strip()
    if not sub: return []
    fs = font(SEMI, size)
    while fs.size > 24 and len(wrap(fs, sub, RW)) > 2: fs = font(SEMI, fs.size - 2)
    return [text_layer(l, fs, col) for l in wrap(fs, sub, RW)][:2]


# ----- ABANICO: las tarjetas salen del montón y se abren en abanico -----
def build_abanico(p):
    marcas = [k for k in (p.get('marcas') or list(MARCAS)) if k in MARCAS][:4] or ['visa']
    L = {'diseno': 'abanico', 'cards': [tarjeta_marca(k) for k in marcas]}
    L['title'] = _titulo(p, 1500, 84, 1)
    L['sub'] = _subt(p, 1400, 36)
    L['chips'] = _chips([c.strip() for c in (p.get('chips') or []) if (c or '').strip()][:3])
    d = 900
    halo = Image.new('RGBA', (d * 2, d), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse((0, 0, d * 2 - 1, d - 1), fill=lighten(BLUE, 0.9) + (255,))
    L['halo'] = halo.resize((d, d // 2), Image.LANCZOS)
    return L


def render_abanico(L, p, t):
    S = M.SLIDE
    fr = base_frame()
    out = ease_in_cubic((t - (S - 0.6)) / 0.6); vis = 1 - out
    # título y frase arriba al centro
    y = 120
    for i, l in enumerate(L['title'] + L['sub']):
        k = ease_out_cubic((t - 0.2 - 0.1 * i) / 0.6)
        paste(fr, l, W / 2, y + l.height / 2 - 30 * (1 - k) - 40 * out, k * vis)
        y += l.height + (6 if i == len(L['title']) - 1 else -8)
    # abanico
    cy = 600
    k0 = ease_out_cubic(t / 0.8)
    paste(fr, L['halo'], W / 2, cy + 90, k0 * vis, scale=0.85 + 0.15 * k0)
    n = len(L['cards'])
    rise = ease_out_back((t - 0.2) / 0.8, 1.2)
    fan = ease_out_back((t - 0.95) / 0.9, 1.5)
    sway = math.sin((t - 2.2) * 2 * math.pi / 3.6) * 2.5 * ease_out_cubic((t - 2.2) / 0.6)
    for i, c in reversed(list(enumerate(L['cards']))):   # de derecha a izquierda: la marca de cada tarjeta queda visible
        u = (i - (n - 1) / 2)
        ang = -u * 12 * fan + sway
        x = W / 2 + u * 250 * fan
        yy = cy + abs(u) * 30 * fan + 300 * (1 - min(rise, 1)) - 14 * fan
        rc = c.rotate(ang, resample=Image.BICUBIC, expand=True)
        paste(fr, rc, x, yy + 120 * out, min(1, max(rise, 0)) * vis)
    # palomitas abajo
    chips = L['chips']
    tw = sum(c.width for c in chips) + 18 * (len(chips) - 1)
    x = W / 2 - tw / 2
    for i, c in enumerate(chips):
        k = ease_out_back((t - 1.8 - i * 0.15) / 0.5, 1.6)
        paste(fr, c, x, 858 + 30 * (1 - min(k, 1)), min(1, max(k, 0)) * vis, anchor='tl')
        x += c.width + 18
    return finish(fr)


# ----- SIN CONTACTO: ondas que laten, tarjeta que toca y "PAGO APROBADO"; panel azul claro con el texto -----
def build_contacto(p):
    L = {'diseno': 'contacto'}
    L['title'] = _titulo(p, 760, 86, 3)
    L['sub'] = _subt(p, 760, 36, (70, 80, 100))
    L['marcas'] = [marca_badge(k, 160, 100) for k in (p.get('marcas') or list(MARCAS)) if k in MARCAS][:4]
    L['chips'] = _chips([c.strip() for c in (p.get('chips') or []) if (c or '').strip()][:3])
    pw = 940
    panel = Image.new('RGBA', (pw, H), lighten(BLUE, 0.88) + (255,))
    m = Image.new('L', (pw * 2, H * 2), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, -200, pw * 2 + 200, H * 2 + 200), 140, fill=255)
    panel.putalpha(m.resize((pw, H), Image.LANCZOS))
    L['panel'] = panel
    # ícono central sin contacto
    d = 300; s = 3
    ic = Image.new('RGBA', (d * s, d * s), (0, 0, 0, 0))
    ImageDraw.Draw(ic).ellipse((0, 0, d * s - 1, d * s - 1), fill=(255, 255, 255, 255))
    ic.alpha_composite(_contactless(int(d * s * .62), BLUE, 9), (int(d * s * .26), int(d * s * .19)))
    L['icon'] = shadow(ic.resize((d, d), Image.LANCZOS), blur=24, off=(0, 16), opacity=0.22, pad=70)[0]
    ring = Image.new('RGBA', (1000, 1000), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((10, 10, 990, 990), outline=BLUE + (255,), width=12)
    L['ring'] = ring.resize((500, 500), Image.LANCZOS)
    L['card'] = _tarjeta()
    ok = Image.new('RGBA', (620 * 2, 120 * 2), (0, 0, 0, 0)); dr = ImageDraw.Draw(ok)
    dr.rounded_rectangle((0, 0, 1239, 239), 120, fill=(22, 150, 70))
    dr.ellipse((26, 26, 214, 214), fill='white')
    dr.line([(70, 124), (108, 160), (172, 86)], fill=(22, 150, 70), width=26, joint='curve')
    dr.text((250, 120), 'PAGO APROBADO', font=font(BLACK, 80), fill='white', anchor='lm')
    L['ok'] = shadow(ok.resize((620, 120), Image.LANCZOS), blur=14, off=(0, 10), opacity=0.25, pad=40)[0]
    return L


def render_contacto(L, p, t):
    S = M.SLIDE
    fr = base_frame()
    out = ease_in_cubic((t - (S - 0.6)) / 0.6); vis = 1 - out
    CX, CY = 470, 470
    # ondas que laten desde el centro
    for i in range(3):
        ph = ((t - 0.6) / 1.8 - i / 3) % 1 if t > 0.6 else 0
        if t > 0.6 + i * 0.6:
            paste(fr, L['ring'], CX, CY, (1 - ph) * 0.5 * vis, scale=0.6 + 0.9 * ph)
    k = ease_out_back((t - 0.1) / 0.8, 1.6)
    paste(fr, L['icon'], CX, CY, min(1, max(k, 0)) * vis, scale=max(k, 0.01) * (1 + 0.03 * math.sin(t * 3)))
    # tarjeta que entra, toca y se queda flotando
    k = ease_out_cubic((t - 0.8) / 0.8)
    tap = math.sin(min(max((t - 1.6) / 0.6, 0), 1) * math.pi) * 34
    fy = math.sin((t - 2.4) * 2 * math.pi / 3) * 8 * ease_out_cubic((t - 2.4) / 0.5)
    if k > 0.01:
        card = L['card'].rotate(-16 + 12 * (1 - k), resample=Image.BICUBIC, expand=True)
        paste(fr, card, CX + 150 + 400 * (1 - k) - 300 * out, CY - 160 - 200 * (1 - k) + tap + fy, min(1, k) * vis)
    # sello de pago aprobado
    k = ease_out_back((t - 2.2) / 0.55, 2.0)
    paste(fr, L['ok'], CX, CY + 300, min(1, max(k, 0)) * vis, scale=max(k, 0.01))
    # panel derecho con el texto
    kp = ease_out_cubic((t - 0.1) / 0.7)
    px = W - L['panel'].width + 300 * (1 - kp) + 300 * out
    fr.alpha_composite(with_alpha_safe(L['panel'], kp * vis), (int(px), 0))
    X = int(px) + 90
    items = [(l, -10) for l in L['title']]
    items[-1] = (items[-1][0], 16)
    items += [(l, -4) for l in L['sub']]
    th = sum(i.height + g for i, g in items)
    mh = (L['marcas'][0].height - 52) if L['marcas'] else 0
    total = th + 30 + mh + (90 if L['chips'] else 0)
    y = max(160, 470 - total / 2)
    for i, (it, g) in enumerate(items):
        kk = ease_out_cubic((t - (0.45 + 0.1 * i)) / 0.6)
        paste(fr, it, X + 40 * (1 - kk), y, kk * vis, anchor='tl')
        y += it.height + g
    y += 30 - 26
    x = X - 26
    for i, m in enumerate(L['marcas']):
        kk = ease_out_back((t - 1.1 - i * 0.15) / 0.5, 2.0)
        paste(fr, m, x + m.width / 2, y + m.height / 2, min(1, max(kk, 0)) * vis, scale=max(kk, 0.01))
        x += m.width - 66
    y += mh + 34
    x = X
    for i, c in enumerate(L['chips']):
        kk = ease_out_back((t - 1.9 - i * 0.15) / 0.5, 1.6)
        paste(fr, c, x, y + 30 * (1 - min(kk, 1)), min(1, max(kk, 0)) * vis, anchor='tl', scale=1)
        x += c.width + 14
    return finish(fr)


def with_alpha_safe(layer, a):
    r = M.with_alpha(layer, a)
    return r if r is not None else Image.new('RGBA', layer.size, (0, 0, 0, 0))


# ----- PERSONA: alguien mete su tarjeta en la terminal y dice "¡Pago aplicado!" -----
PIEL, PELO, CAMISA = (226, 176, 138), (58, 40, 30), (51, 115, 185)
TSC = 0.5                                   # tamaño de la terminal en esta escena
P_TX, P_MOSTR = 610, 800                    # x de la terminal, altura del mostrador


def build_persona(p):
    L = build_terminal(dict(p, diseno='terminal'))
    L['diseno'] = 'persona'
    s = 2
    # cuerpo y cabeza (estáticos)
    w, h = 420, 560
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    cx = w / 2
    dr.rounded_rectangle(((cx - 150) * s, 300 * s, (cx + 150) * s, 620 * s), 110 * s, fill=CAMISA)         # torso
    dr.rectangle(((cx - 30) * s, 250 * s, (cx + 30) * s, 320 * s), fill=darken(PIEL, 0.08))                # cuello
    dr.polygon([((cx - 52) * s, 300 * s), (cx * s, 372 * s), ((cx + 52) * s, 300 * s)], fill='white')      # cuello de la camisa
    dr.polygon([((cx - 34) * s, 300 * s), (cx * s, 348 * s), ((cx + 34) * s, 300 * s)], fill=darken(PIEL, 0.08))
    dr.ellipse(((cx - 92) * s, 70 * s, (cx + 92) * s, 270 * s), fill=PIEL)                                  # cabeza
    dr.ellipse(((cx - 104) * s, 150 * s, (cx - 76) * s, 200 * s), fill=PIEL)                                # orejas
    dr.ellipse(((cx + 76) * s, 150 * s, (cx + 104) * s, 200 * s), fill=PIEL)
    dr.chord(((cx - 98) * s, 52 * s, (cx + 98) * s, 220 * s), 180, 360, fill=PELO)                          # pelo
    dr.ellipse(((cx - 98) * s, 100 * s, (cx - 60) * s, 170 * s), fill=PELO)
    dr.ellipse(((cx + 20) * s, 62 * s, (cx + 96) * s, 150 * s), fill=PELO)
    for ex in (-36, 36):                                                                                     # cejas
        dr.line(((cx + ex - 16) * s, 148 * s, (cx + ex + 16) * s, 144 * s), fill=PELO, width=6 * s)
    L['p_body'] = im.resize((w, h), Image.LANCZOS)
    L['p_size'] = (w, h)
    # mostrador
    mw = 900
    m = Image.new('RGBA', (mw, 200), (0, 0, 0, 0)); dm = ImageDraw.Draw(m)
    dm.rounded_rectangle((0, 0, mw - 1, 34), 14, fill=NAVY)
    dm.rectangle((24, 30, mw - 25, 199), fill=lighten(BLUE, 0.82))
    dm.rectangle((24, 30, mw - 25, 44), fill=lighten(BLUE, 0.62))
    for xx in range(150, mw - 60, 200): dm.rectangle((xx, 70, xx + 6, 199), fill=lighten(BLUE, 0.74))
    L['p_mostr'] = m
    # tarjeta vertical (se mete por arriba de la terminal)
    c = _tarjeta()
    c = c.resize((int(c.width * 0.55), int(c.height * 0.55)), Image.LANCZOS)
    L['p_card'] = c.rotate(90, expand=True)
    # globo de diálogo
    f = font(BLACK, 46); txt = '¡Pago aplicado!'
    bw, bh = text_w(f, txt) + 80, 110
    b = Image.new('RGBA', ((bw + 20) * s, (bh + 50) * s), (0, 0, 0, 0)); db = ImageDraw.Draw(b)
    db.rounded_rectangle((4 * s, 4 * s, (bw + 4) * s, (bh + 4) * s), 50 * s, fill='white', outline=BLUE, width=6 * s)
    db.polygon([(60 * s, (bh - 2) * s), (110 * s, (bh - 2) * s), (50 * s, (bh + 44) * s)], fill='white')
    db.line([(64 * s, (bh + 3) * s), (50 * s, (bh + 44) * s), (110 * s, (bh + 3) * s)], fill=BLUE, width=6 * s, joint='curve')
    db.text(((bw / 2 + 4) * s, (bh / 2 + 4) * s), txt, font=font(BLACK, 46 * s), fill=(22, 150, 70), anchor='mm')
    L['p_bubble'] = shadow(b.resize((bw + 20, bh + 50), Image.LANCZOS), blur=12, off=(0, 8), opacity=0.2, pad=30)[0]
    return L


def _brazo(hombro, mano, card_on):
    """Brazo (manga + antebrazo + mano) dibujado con antialias en un recuadro local."""
    s = 2
    x0, y0 = min(hombro[0], mano[0]) - 120, min(hombro[1], mano[1]) - 120
    x1, y1 = max(hombro[0], mano[0]) + 120, max(hombro[1], mano[1]) + 160
    w, h = int(x1 - x0), int(y1 - y0)
    im = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    sx, sy = (hombro[0] - x0) * s, (hombro[1] - y0) * s
    hx, hy = (mano[0] - x0) * s, (mano[1] - y0) * s
    # codo: brazo de dos tramos de 175 px que se dobla hacia abajo
    l1, l2 = 190 * s, 200 * s
    dx, dy = hx - sx, hy - sy
    d = max(1, min(math.hypot(dx, dy), (l1 + l2) * 0.999))
    a = math.atan2(dy, dx) - math.acos(max(-1, min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    ex, ey = sx + l1 * math.cos(a), sy + l1 * math.sin(a)
    def seg(p, q, w1, w2, col):
        """Tramo que se adelgaza de w1 a w2 (bordes redondos)."""
        ang = math.atan2(q[1] - p[1], q[0] - p[0]); nx, ny = -math.sin(ang), math.cos(ang)
        dr.polygon([(p[0] + nx * w1 / 2, p[1] + ny * w1 / 2), (q[0] + nx * w2 / 2, q[1] + ny * w2 / 2),
                    (q[0] - nx * w2 / 2, q[1] - ny * w2 / 2), (p[0] - nx * w1 / 2, p[1] - ny * w1 / 2)], fill=col)
        dr.ellipse((p[0] - w1 / 2, p[1] - w1 / 2, p[0] + w1 / 2, p[1] + w1 / 2), fill=col)
        dr.ellipse((q[0] - w2 / 2, q[1] - w2 / 2, q[0] + w2 / 2, q[1] + w2 / 2), fill=col)
    # muñeca: un poco antes del puño, en dirección al codo
    ang = math.atan2(hy - ey, hx - ex)
    wx, wy = hx - math.cos(ang) * 40 * s, hy - math.sin(ang) * 40 * s
    seg((sx, sy), (ex, ey), 64 * s, 54 * s, CAMISA)                      # manga larga
    seg((ex, ey), (wx, wy), 54 * s, 46 * s, darken(CAMISA, 0.06))
    cx_, cy_ = wx - math.cos(ang) * 6 * s, wy - math.sin(ang) * 6 * s   # puño blanco de la camisa
    seg((cx_ - math.cos(ang) * 8 * s, cy_ - math.sin(ang) * 8 * s), (cx_ + math.cos(ang) * 8 * s, cy_ + math.sin(ang) * 8 * s),
        50 * s, 50 * s, (245, 247, 250))
    seg((wx, wy), (hx - math.cos(ang) * 14 * s, hy - math.sin(ang) * 14 * s), 34 * s, 40 * s, PIEL)   # dorso de la mano
    # puño que sujeta la parte de arriba de la tarjeta: cuatro dedos y el pulgar
    sombra = darken(PIEL, 0.14)
    dr.rounded_rectangle((hx - 40 * s, hy - 30 * s, hx + 40 * s, hy + 30 * s), 24 * s, fill=PIEL)
    for i in range(4):
        fy = hy - 24 * s + i * 14 * s
        dr.rounded_rectangle((hx - 6 * s, fy, hx + 46 * s, fy + 15 * s), 8 * s, fill=PIEL, outline=sombra, width=2 * s)
    dr.rounded_rectangle((hx - 34 * s, hy - 6 * s, hx + 6 * s, hy + 12 * s), 9 * s, fill=lighten(PIEL, 0.05),
                         outline=sombra, width=2 * s)                     # pulgar
    dr.arc((hx + 30 * s, hy - 24 * s, hx + 44 * s, hy - 12 * s), 270, 90, fill=lighten(PIEL, 0.3), width=2 * s)
    return im.resize((w, h), Image.LANCZOS), (x0, y0)


def render_persona(L, p, t):
    S = M.SLIDE
    fr = base_frame()
    out = ease_in_cubic((t - (S - 0.6)) / 0.6); vis = 1 - out
    dx = -300 * out
    a = ease_out_cubic(t / 0.9)
    paste(fr, L['disc'], 480 + dx, 560, a * vis, scale=0.88 + 0.12 * a)
    # persona entra desde la izquierda
    k = ease_out_cubic((t - 0.1) / 0.8)
    PX = 270 - 200 * (1 - k) + dx
    breath = math.sin(t * 2 * math.pi / 3.2) * 3
    pw, ph = L['p_size']
    body_top = P_MOSTR - 470 + breath
    paste(fr, L['p_body'], PX, body_top + ph / 2, k * vis)
    # cara: ojos (parpadeo) y boca (habla al decir "pago aplicado")
    if k * vis > 0.05:
        dr = ImageDraw.Draw(fr)
        hy = body_top + 175
        blink = any(abs(t - b) < 0.07 for b in (1.2, 4.6, 6.4))
        for ex in (-36, 36):
            if blink: dr.line((PX + ex - 10, hy, PX + ex + 10, hy), fill=(40, 30, 25), width=4)
            else: dr.ellipse((PX + ex - 8, hy - 9, PX + ex + 8, hy + 9), fill=(40, 30, 25))
        talk = 2.6 < t < 3.6
        op = abs(math.sin((t - 2.6) * 14)) if talk else 0
        if op > 0.2:                                   # sonrisa abierta al hablar
            dr.chord((PX - 28, hy + 18, PX + 28, hy + 52 + 14 * op), 0, 180, fill=(140, 45, 45))
            dr.chord((PX - 20, hy + 20, PX + 20, hy + 30), 0, 180, fill='white')
        else:
            dr.arc((PX - 30, hy + 14, PX + 30, hy + 56), 20, 160, fill=(150, 60, 55), width=6)
    # mostrador
    paste(fr, L['p_mostr'], 450 + dx, P_MOSTR + 100, vis)
    # terminal sobre el mostrador
    th = TERM_H * TSC
    tcx, tcy = P_TX + dx, P_MOSTR - th / 2 + 6
    # mano: va hacia la terminal, mete la tarjeta y se queda
    # la tarjeta llega sola volando, se endereza y se mete en la ranura de arriba de la terminal
    fly = ease_out_cubic((t - 0.6) / 0.9)
    push = ease_in_out((t - 1.6) / 0.55)
    card = L['p_card']
    CL = 330 * 0.55                                  # largo visible de la tarjeta
    top_t = tcy - th / 2
    y_top = top_t - CL / 2 + 4                       # justo encima de la ranura
    ccx = tcx + 330 * (1 - fly)
    ccy = y_top - 300 * (1 - fly) + (CL * 0.62) * push
    ang = -70 * (1 - fly) + 6 * math.sin(fly * math.pi)
    sl = Image.new('RGBA', (int(150 * TSC / 0.5), 14), (0, 0, 0, 0))
    ImageDraw.Draw(sl).rounded_rectangle((0, 0, sl.width - 1, 13), 7, fill=(18, 21, 28, 255))
    paste(fr, sl, tcx, top_t + 2, vis)                                 # ranura
    if fly > 0:
        c = card.rotate(ang, resample=Image.BICUBIC, expand=True) if abs(ang) > 0.3 else card
        paste(fr, c, ccx, ccy, vis * min(1, fly * 3))
    paste(fr, L['body'], tcx, tcy, vis, scale=TSC)
    scy = tcy + (-TERM_H / 2 + 34 + 133) * TSC
    ok = ease_out_cubic((t - 2.2) / 0.35)
    paste(fr, L['scr_wait'], tcx, scy, vis * (1 - ok), scale=TSC)
    if ok > 0: paste(fr, L['scr_ok'], tcx, scy, vis * ok, scale=TSC)
    # destello al aprobar
    for i in range(2):
        ph = (t - 2.2) / 0.9 - i * 0.25
        if 0 < ph < 1:
            paste(fr, L['waves'], tcx + 80, scy - 20, (1 - ph) * vis * 0.8, scale=0.5 + 0.6 * ph)
    # globo "¡Pago aplicado!"
    kb = ease_out_back((t - 2.5) / 0.5, 2.0)
    bub = L['p_bubble']
    paste(fr, bub, PX - 70 + bub.width / 2, body_top + 70 - bub.height / 2 + 10, min(1, max(kb, 0)) * vis,
          scale=max(kb, 0.01))
    _texto_derecha(fr, L, t, out, vis)
    return finish(fr)


def ease_in_out(x):
    x = min(max(x, 0), 1)
    return 3 * x * x - 2 * x * x * x


# =====================================================================
#  SERVICIOS  (anuncio de la farmacia: servicios, horario y código QR para escribir por WhatsApp)
#             misma composición que Destacado: panel diagonal a la izquierda con la tarjeta del QR
#             y la información a la derecha.
# =====================================================================
def _wa_link(p):
    """Texto del QR: la liga que se escribió, o WhatsApp con el número (10 dígitos → México)."""
    q = (p.get('qr') or '').strip()
    if q:
        return q
    dig = ''.join(ch for ch in (p.get('whatsapp') or '') if ch.isdigit())
    if not dig:
        return ''
    if len(dig) == 10:
        dig = '52' + dig
    return 'https://wa.me/' + dig


def _qr_img(texto, size, col=NAVY):
    import qrcode
    q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=0, box_size=10)
    q.add_data(texto); q.make(fit=True)
    im = q.make_image(fill_color=col, back_color=(255, 255, 255)).convert('RGB')
    return im.resize((size, size), Image.NEAREST).convert('RGBA')


def _icono_reloj(d, col):
    s = 3; D = d * s
    im = Image.new('RGBA', (D, D), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.ellipse((3 * s, 3 * s, D - 3 * s, D - 3 * s), outline=col + (255,), width=4 * s)
    c = D / 2
    dr.line([(c, c), (c, D * 0.24)], fill=col + (255,), width=4 * s)
    dr.line([(c, c), (D * 0.7, c)], fill=col + (255,), width=4 * s)
    return im.resize((d, d), Image.LANCZOS)


def build_servicios(p):
    col = BLUE; deep = NAVY
    L = {}
    L['bg'] = vgrad((W, H), (255, 255, 255), lighten(col, 0.9)).convert('RGBA')
    # panel diagonal de marca (igual que Destacado)
    pw_ = D_PANEL[1] + 40
    g = Image.new('RGBA', (pw_, H)); g.paste(vgrad((pw_, H), lighten(col, 0.05), deep))
    rings = g.copy(); dg = ImageDraw.Draw(rings)
    for r in range(D_R + 90, 1400, 95):
        dg.ellipse((D_CX - r, D_CY - r, D_CX + r, D_CY + r), outline=(255, 255, 255, 255), width=2)
    g = Image.blend(g, rings, 0.16)
    ss = 3
    m = Image.new('L', (pw_ * ss, H * ss), 0)
    ImageDraw.Draw(m).polygon([(0, 0), (D_PANEL[1] * ss, 0), (D_PANEL[2] * ss, H * ss), (0, H * ss)], fill=255)
    pan = Image.new('RGBA', (pw_, H), (0, 0, 0, 0)); pan.paste(g, (0, 0), m.resize((pw_, H), Image.LANCZOS))
    L['panel'] = pan
    L['bg_panel'] = L['bg'].copy(); L['bg_panel'].alpha_composite(pan)
    # tarjeta blanca: QR para escribir por WhatsApp (o el logo si no hay número)
    cw, chh = 560, 640
    card = Image.new('RGBA', (cw, chh), (255, 255, 255, 255)); card.putalpha(rr_mask((cw, chh), 44))
    dc = ImageDraw.Draw(card)
    link = _wa_link(p)
    if link:
        qs = 400
        card.alpha_composite(_qr_img(link, qs), ((cw - qs) // 2, 54))
        dc.text((cw / 2, 54 + qs + 52), 'Escanea y escríbenos', font=font(BOLD, 34), fill=NAVY, anchor='mm')
        num = (p.get('whatsapp') or '').strip()
        if num:
            dc.text((cw / 2, 54 + qs + 104), 'WhatsApp ' + num, font=fit_font(BLACK, 'WhatsApp ' + num, cw - 60, 40, 24),
                    fill=(22, 140, 70), anchor='mm')
    elif M.LOGO_BIG is not None:
        lg = M.LOGO_BIG.copy(); sc = min((cw - 80) / lg.width, (chh - 200) / lg.height)
        lg = lg.resize((int(lg.width * sc), int(lg.height * sc)), Image.LANCZOS)
        card.alpha_composite(lg, ((cw - lg.width) // 2, (chh - lg.height) // 2 - 20))
    L['card'] = shadow(card, blur=26, off=(0, 18), opacity=0.28, pad=70)[0]
    # columna de texto
    kick = 'SERVICIOS'
    fk = font(BLACK, 30)
    kw, kh = text_w(fk, kick) + 60, 54
    kp = Image.new('RGBA', (kw, kh), BLUE + (255,)); kp.putalpha(rr_mask((kw, kh), kh // 2))
    ImageDraw.Draw(kp).text((kw / 2, kh / 2), kick, font=fk, fill='white', anchor='mm')
    L['kick'] = kp
    titulo = ' '.join((p.get('titulo') or 'Te atendemos como en casa').split())
    ft = font(BLACK, 96)
    while ft.size > 50 and len(wrap(ft, titulo, D_RW)) > 2:
        ft = font(BLACK, ft.size - 4)
    L['title'] = [text_layer(l, ft, NAVY if i == 0 else BLUE) for i, l in enumerate(wrap(ft, titulo, D_RW)[:2])]
    fl = font(BOLD, 40)
    L['lineas'] = []
    for s_ in [x.strip() for x in (p.get('lineas') or []) if (x or '').strip()][:4]:
        f_ = fit_font(BOLD, s_, D_RW - 100, 40, 26)
        row = Image.new('RGBA', (D_RW, 76), (0, 0, 0, 0))
        row.alpha_composite(check_icon(BLUE, 62), (0, 7))
        ImageDraw.Draw(row).text((86, 38), s_, font=f_, fill=(40, 46, 60), anchor='lm')
        L['lineas'].append(row)
    hor = (p.get('horario') or '').strip()
    if hor:
        fh = fit_font(BOLD, hor, D_RW - 120, 34, 22)
        hw, hh = text_w(fh, hor) + 120, 70
        hp = Image.new('RGBA', (hw, hh), lighten(BLUE, 0.86) + (255,)); hp.putalpha(rr_mask((hw, hh), hh // 2))
        hp.alpha_composite(_icono_reloj(40, NAVY), (26, 15))
        ImageDraw.Draw(hp).text((84, hh / 2), hor, font=fh, fill=NAVY, anchor='lm')
        L['horario'] = hp
    else:
        L['horario'] = None
    return L


def render_servicios(L, p, t):
    S = M.SLIDE
    out = ease_in_cubic((t - (S - 0.55)) / 0.55); vis = 1 - out
    k = ease_out_cubic(t / 0.6) * vis
    if k >= 0.999:
        fr = L['bg_panel'].copy()
    else:
        fr = L['bg'].copy()
        if k > 0.005:
            fr.alpha_composite(M.with_alpha(L['panel'], k), (int(-120 * (1 - k)), 0))
    # tarjeta del QR: entra con rebote y luego flota suave
    a = ease_out_back((t - 0.15) / 0.8, 1.4)
    fy = math.sin((t - 1.2) * 2 * math.pi / 3.4) * 7 * ease_out_cubic((t - 1.2) / 0.6)
    paste(fr, L['card'], D_CX - 200 * out, D_CY - 20 + fy, min(1, max(a, 0)) * vis, scale=max(0.01, 0.8 + 0.2 * min(a, 1.05)))
    # texto
    sx = 160 * out
    blocks = [('kick', L['kick'], 22)] + [('t', l, -18) for l in L['title']]
    blocks[-1] = (blocks[-1][0], blocks[-1][1], 20)
    blocks += [('l', r, 6) for r in L['lineas']]
    if L['horario'] is not None:
        blocks.append(('h', L['horario'], 0))
    total = sum(b.height + g for _, b, g in blocks) + (16 if L['horario'] is not None else 0)
    y = max(140, min(490 - total / 2, 800 - total))
    for i, (kind, b, g) in enumerate(blocks):
        if kind == 'h':
            y += 16
        if kind in ('l', 'h'):
            a = ease_out_back((t - (1.0 + 0.15 * i)) / 0.5, 1.6)
            paste(fr, b, D_X + b.width / 2 + sx, y + b.height / 2 + 20 * (1 - min(a, 1)), min(1, max(a, 0)) * vis,
                  scale=max(0.01, 0.9 + 0.1 * min(a, 1)))
        else:
            a = ease_out_cubic((t - (0.3 + 0.1 * i)) / 0.6)
            paste(fr, b, D_X - (10 if kind == 't' else 0) + sx, y - 30 * (1 - a), a * vis, anchor='tl')
        y += b.height + g
    return finish(fr)
