"""Motor del video promocional (Marketing → Video promocional). Genera MP4 1920x1080 con Pillow + ffmpeg."""
import math, subprocess, os, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops
import imageio_ffmpeg

W, H, FPS = 1920, 1080, 30
SLIDE = 8.0
INTRO = 3.0
CONFIG = {}
WAVE = None

# Tipografía de los anuncios: Montserrat (incluida en assets/fonts); si faltara, Segoe UI de Windows.
_BASE = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
FONT_DIR = os.path.join(_BASE, 'Font Montserrat')
_fonts = {}
def font(name, size):
    k = (name, size)
    if k not in _fonts:
        path = os.path.join(FONT_DIR, name)
        if not os.path.isfile(path):
            path = 'C:\\Windows\\Fonts\\' + {'Montserrat-ExtraBold.ttf': 'seguibl.ttf', 'Montserrat-Bold.ttf': 'segoeuib.ttf',
                                            'Montserrat-SemiBold.ttf': 'seguisb.ttf'}.get(name, 'segoeui.ttf')
        _fonts[k] = ImageFont.truetype(path, size)
    return _fonts[k]
# títulos y precios en Montserrat Bold (limpia); textos secundarios en SemiBold/Medium
BLACK, BOLD, SEMI, REG = 'Montserrat-Bold.ttf', 'Montserrat-Bold.ttf', 'Montserrat-SemiBold.ttf', 'Montserrat-Medium.ttf'

NAVY, BLUE = (36, 51, 102), (51, 115, 185)
LOGO_BIG = LOGO_SMALL = None
LOGO_W, LOGO_POS = 300, (1580, 26)    # arriba a la derecha (se recalcula al cargar el logo)

LOGO_ALPHA = 1.0     # el generador la baja para desvanecer el logo cuando cambia de lugar

def logo_pos_for(style):
    """Cortinilla: centrado arriba del lado izquierdo; demás estilos: arriba a la derecha."""
    if style == 'cortinilla' and LOGO_SMALL is not None:
        return (W / 4 - LOGO_SMALL.width / 2, 40)
    return LOGO_POS

def draw_logo(fr, pos):
    if LOGO_SMALL is None or LOGO_ALPHA <= 0.01: return
    lg = LOGO_SMALL if LOGO_ALPHA >= 0.99 else with_alpha(LOGO_SMALL, LOGO_ALPHA)
    fr.alpha_composite(lg, (int(pos[0]), int(pos[1])))

def load_logo(path):
    global LOGO_BIG, LOGO_SMALL, LOGO_POS
    if not path or not os.path.isfile(path):
        LOGO_BIG = LOGO_SMALL = None; return
    lg = Image.open(path).convert('RGBA')
    bb = lg.split()[3].getbbox()
    if bb: lg = lg.crop(bb)
    LOGO_BIG = lg.resize((1300, int(lg.height * 1300 / lg.width)), Image.LANCZOS)
    if LOGO_BIG.height > 700:
        LOGO_BIG = lg.resize((int(lg.width * 700 / lg.height), 700), Image.LANCZOS)
    LOGO_SMALL = lg.resize((LOGO_W, int(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    if LOGO_SMALL.height > 110:
        LOGO_SMALL = lg.resize((int(lg.width * 110 / lg.height), 110), Image.LANCZOS)
    LOGO_POS = (W - 40 - LOGO_SMALL.width, 26)

def auto_color(path):
    """Color de marca automático: el color saturado más común del producto, oscurecido para leerse bien."""
    import colorsys
    im = cut_cached(path).convert('RGBA')
    im.thumbnail((160, 160))
    q = im.convert('RGB').quantize(12)
    pal = q.getpalette()
    alpha = im.split()[3]
    counts = {}
    for idx, a in zip(q.getdata(), alpha.getdata()):
        if a > 200: counts[idx] = counts.get(idx, 0) + 1
    best, score = NAVY, 0
    for idx, n in counts.items():
        r, g, b = pal[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.35 or v < 0.2: continue
        sc = n * (0.5 + s)
        if sc > score: best, score = (r, g, b), sc
    r, g, b = best
    while 0.299 * r + 0.587 * g + 0.114 * b > 120:
        r, g, b = int(r * 0.88), int(g * 0.88), int(b * 0.88)
    return (r, g, b)

# ---------- helpers ----------
def ease_out_cubic(x): x = min(max(x, 0), 1); return 1 - (1 - x) ** 3
def ease_in_cubic(x): x = min(max(x, 0), 1); return x ** 3
def ease_out_back(x, s=1.7):
    x = min(max(x, 0), 1); x -= 1; return x * x * ((s + 1) * x + s) + 1

def lighten(c, a): return tuple(int(v + (255 - v) * a) for v in c)
def darken(c, a): return tuple(int(v * (1 - a)) for v in c)

def text_w(fnt, s): b = fnt.getbbox(s); return b[2] - b[0]

def wrap(fnt, s, maxw):
    lines, cur = [], ''
    for w in s.split():
        t = (cur + ' ' + w).strip()
        if text_w(fnt, t) <= maxw: cur = t
        else: lines.append(cur); cur = w
    lines.append(cur); return lines

def vgrad(size, c1, c2):
    w, h = size
    g = Image.new('RGB', (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        g.putpixel((0, y), tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return g.resize((w, h))

def hgrad(size, c1, c2):
    w, h = size
    g = Image.new('RGB', (w, 1))
    for x in range(w):
        t = x / max(w - 1, 1)
        g.putpixel((x, 0), tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return g.resize((w, h))

def rr_mask(size, r, scale=3):
    w, h = size
    m = Image.new('L', (w * scale, h * scale), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), r * scale, fill=255)
    return m.resize((w, h), Image.LANCZOS)

def shadow(layer, blur=18, off=(0, 12), opacity=0.35, pad=40):
    w, h = layer.size
    out = Image.new('RGBA', (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    a = layer.split()[3].point(lambda v: int(v * opacity))
    sh = Image.new('RGBA', layer.size, (0, 0, 0, 255)); sh.putalpha(a)
    out.alpha_composite(sh, (pad + off[0], pad + off[1]))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(layer, (pad, pad))
    return out, pad

def cut_white(im):
    """Quita el fondo blanco conectado a los bordes y recorta."""
    im = im.convert('RGB')
    w, h = im.size
    r, g, b = im.split()
    mn = ImageChops.darker(ImageChops.darker(r, g), b)
    m = mn.point(lambda v: 255 if v > 238 else 0).convert('RGB')
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    seeds += [(x, 0) for x in range(0, w, 25)] + [(x, h - 1) for x in range(0, w, 25)]
    seeds += [(0, y) for y in range(0, h, 25)] + [(w - 1, y) for y in range(0, h, 25)]
    for s in seeds:
        if m.getpixel(s) == (255, 255, 255):
            ImageDraw.floodfill(m, s, (128, 0, 0))
    bg = m.split()[1].point(lambda v: 0)  # placeholder
    rch = m.split()[0]; gch = m.split()[1]
    # fondo = r==128 & g==0
    bgmask = ImageChops.multiply(rch.point(lambda v: 255 if v == 128 else 0), gch.point(lambda v: 255 if v == 0 else 0))
    alpha = ImageChops.invert(bgmask).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    out = im.convert('RGBA'); out.putalpha(alpha)
    bbox = alpha.point(lambda v: 255 if v > 20 else 0).getbbox()
    return out.crop(bbox) if bbox else out

_cut_cache = {}
def cut_cached(path):
    k = (path, os.path.getmtime(path))
    if k not in _cut_cache:
        if len(_cut_cache) > 40: _cut_cache.clear()
        _cut_cache[k] = cut_white(Image.open(path))
    return _cut_cache[k]

def with_alpha(layer, a):
    if a >= 0.999: return layer
    if a <= 0.001: return None
    l = layer.copy(); l.putalpha(layer.split()[3].point(lambda v: int(v * a))); return l

# ---------- build static layers per product ----------
def check_icon(col, d=92):
    s = 3; D = d * s
    im = Image.new('RGBA', (D, D), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.ellipse((4 * s, 4 * s, D - 4 * s, D - 4 * s), fill=lighten(col, 0.88) + (255,), outline=col + (255,), width=5 * s)
    dr.line([(D * .30, D * .52), (D * .45, D * .66), (D * .72, D * .36)], fill=col + (255,), width=10 * s, joint='curve')
    for p in [(D * .30, D * .52), (D * .45, D * .66), (D * .72, D * .36)]:
        dr.ellipse((p[0] - 5 * s, p[1] - 5 * s, p[0] + 5 * s, p[1] + 5 * s), fill=col + (255,))
    return im.resize((d, d), Image.LANCZOS)

def _fit_size(text, avail, start, minimum, max_lines):
    size = start
    while size > minimum:
        f = font(BOLD, size)
        ls = wrap(f, text, avail)
        if len(ls) <= max_lines and all(text_w(f, l) <= avail for l in ls): break
        size -= 1
    return size

def bens_row(texts, icon, w, h, color, gap=12, start=28, minimum=17, max_lines=2):
    """Fila de palomitas: todas con el mismo tamaño de letra (el que permite que ninguna se corte)."""
    avail = w - icon.width - gap
    size = min([_fit_size(t, avail, start, minimum, max_lines) for t in texts] or [start])
    return [bens_item(t, icon, w, h, color, gap, size, max_lines) for t in texts]

def bens_item(text, icon, w, h, color, gap=12, size=28, max_lines=2):
    """Palomita + texto centrado verticalmente con el círculo."""
    avail = w - icon.width - gap
    f = font(BOLD, size)
    ls = wrap(f, text, avail)[:max_lines]
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    im.alpha_composite(icon, (0, (h - icon.height) // 2))
    dr = ImageDraw.Draw(im)
    lh = int(size * 1.22)
    for i, l in enumerate(ls):
        dr.text((icon.width + gap, h / 2 + (i - (len(ls) - 1) / 2) * lh), l, font=f, fill=color, anchor='lm')
    return im

def build(p):
    L = {}
    col = tuple(p.get('color') or auto_color(p['file']))
    col2 = tuple(p.get('color2') or lighten(col, 0.4))
    COLW = 840
    # producto
    prod = cut_cached(p['file'])
    pw, ph = prod.size
    sc = min(800 / pw, 640 / ph)
    prod = prod.resize((int(pw * sc), int(ph * sc)), Image.LANCZOS)
    L['prod'] = prod
    sh = Image.new('L', (prod.width + 200, 120), 0)
    ImageDraw.Draw(sh).ellipse((100, 40, prod.width + 100, 80), fill=110)
    sh = sh.filter(ImageFilter.GaussianBlur(22))
    shl = Image.new('RGBA', sh.size, (0, 0, 0, 255)); shl.putalpha(sh)
    L['pshadow'] = shl
    d = 680
    disc = Image.new('RGBA', (d * 2, d * 2), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((0, 0, d * 2 - 1, d * 2 - 1), fill=lighten(col, 0.93) + (255,))
    L['disc'] = disc.resize((d, d), Image.LANCZOS)

    # nombre
    size = 112
    while text_w(font(BLACK, size), p['name']) > COLW and size > 60: size -= 4
    f = font(BLACK, size)
    bb = f.getbbox(p['name'])
    im = Image.new('RGBA', (bb[2] + 20, bb[3] + 20), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10 - bb[0], 10), p['name'], font=f, fill=col + (255,))
    L['name'] = im

    f = font(SEMI, 54 if text_w(font(SEMI, 54), p['sub']) < COLW else 40)
    im = Image.new('RGBA', (COLW, 80), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((COLW // 2, 40), p['sub'], font=f, fill=lighten(col, 0.15) + (255,), anchor='mm')
    L['sub'] = im

    f = font(REG, 36)
    im = Image.new('RGBA', (COLW, 100), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    for i, s in enumerate([x for x in p.get('pres', []) if x.strip()][:2]):
        dr.text((COLW // 2, 25 + i * 48), s, font=f, fill=(55, 55, 60, 255), anchor='mm')
    L['pres'] = im

    # pastilla de descripción (si no hay descripción, no se dibuja)
    L['pill'], L['pill_pad'] = None, 0
    f = font(BOLD, 38)
    lines = wrap(f, p['desc'], COLW - 120)
    ph_ = 50 * len(lines) + 46
    pill = hgrad((COLW, ph_), col, lighten(col, 0.35)).convert('RGBA')
    pill.putalpha(rr_mask((COLW, ph_), ph_ // 2))
    dr = ImageDraw.Draw(pill)
    for i, s in enumerate(lines):
        dr.text((COLW // 2, 23 + 25 + i * 50), s, font=f, fill=(255, 255, 255, 255), anchor='mm')
    if (p.get('desc') or '').strip():
        L['pill'], L['pill_pad'] = shadow(pill, blur=12, off=(0, 8), opacity=0.25, pad=30)

    # precio
    fnum = font(BLACK, 200); fdol = font(BLACK, 90); funit = font(BLACK, 56)
    nw = text_w(fnum, p['price']); dw = text_w(fdol, '$'); uw = text_w(funit, p['unit']) if p['unit'] else 0
    bw = max(dw + nw + uw + 150, 420); bh = 215
    base = Image.new('RGBA', (bw, bh + 14), (0, 0, 0, 0))
    dark = Image.new('RGBA', (bw, bh), (150, 0, 15, 255)); dark.putalpha(rr_mask((bw, bh), 46))
    base.alpha_composite(dark, (0, 14))
    face = vgrad((bw, bh), (255, 60, 50), (205, 10, 25)).convert('RGBA'); face.putalpha(rr_mask((bw, bh), 46))
    hl = Image.new('RGBA', (bw, bh), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle((14, 10, bw - 14, bh * 0.45), 36, fill=(255, 255, 255, 38))
    face.alpha_composite(hl)
    base.alpha_composite(face, (0, 0))
    dr = ImageDraw.Draw(base)
    x0 = (bw - (dw + 10 + nw + (uw + 14 if uw else 0))) // 2
    nb = fnum.getbbox(p['price'])
    ny = (bh - (nb[3] - nb[1])) // 2 - nb[1]
    dr.text((x0, ny + 18), '$', font=fdol, fill='white')
    dr.text((x0 + dw + 10 - nb[0], ny), p['price'], font=fnum, fill='white')
    if uw:
        dr.text((x0 + dw + 10 + nw + 14, ny + nb[3] - 60), p['unit'], font=funit, fill='white')
    L['price'], L['price_pad'] = shadow(base, blur=20, off=(0, 16), opacity=0.35, pad=50)
    L['price_face'] = (bw, bh)

    if p.get('extra') and str(p['extra'][0]).strip():
        d = 190
        st = Image.new('RGBA', (d * 3, d * 3), (0, 0, 0, 0)); dr = ImageDraw.Draw(st)
        dr.ellipse((0, 0, d * 3 - 1, d * 3 - 1), fill=(255, 205, 0, 255))
        dr.ellipse((18, 18, d * 3 - 19, d * 3 - 19), outline=(255, 255, 255, 255), width=12)
        st = st.resize((d, d), Image.LANCZOS); dr = ImageDraw.Draw(st)
        dr.text((d // 2, d // 2 - 18), p['extra'][0], font=font(BLACK, 64), fill=(190, 0, 20), anchor='mm')
        dr.text((d // 2, d // 2 + 42), p['extra'][1], font=font(BLACK, 34), fill=(190, 0, 20), anchor='mm')
        L['extra'], L['extra_pad'] = shadow(st, blur=12, off=(0, 8), opacity=0.3, pad=30)

    # precio anterior tachado
    old = str(p.get('old_price') or '').strip().lstrip('$')
    if old:
        tw, th = 250, 108
        tg = Image.new('RGBA', (tw, th), (255, 255, 255, 255))
        tg.putalpha(rr_mask((tw, th), 24))
        dr = ImageDraw.Draw(tg)
        dr.rounded_rectangle((3, 3, tw - 4, th - 4), 22, outline=(225, 225, 230, 255), width=3)
        dr.text((tw // 2, 26), 'ANTES', font=font(BOLD, 24), fill=(120, 120, 128), anchor='mm')
        ft = font(BLACK, 50); txt = '$' + old
        dr.text((tw // 2, 70), txt, font=ft, fill=(110, 110, 118), anchor='mm')
        ww = text_w(ft, txt)
        dr.line((tw // 2 - ww // 2 - 8, 80, tw // 2 + ww // 2 + 8, 60), fill=(220, 20, 40), width=6)
        L['old'], _ = shadow(tg, blur=10, off=(0, 6), opacity=0.25, pad=26)

    # etiqueta de promoción (OFERTA, 2x1, NUEVO...)
    tag = str(p.get('tag') or '').strip().upper()
    if tag:
        ft = font(BLACK, 54)
        tw = text_w(ft, tag) + 80; th = 96
        rb = vgrad((tw, th), (255, 216, 40), (250, 180, 0)).convert('RGBA')
        rb.putalpha(rr_mask((tw, th), 48))
        dr = ImageDraw.Draw(rb)
        dr.rounded_rectangle((4, 4, tw - 5, th - 5), 44, outline=(255, 255, 255, 255), width=5)
        dr.text((tw // 2, th // 2 - 3), tag, font=ft, fill=(190, 0, 25), anchor='mm')
        L['tag'], _ = shadow(rb, blur=12, off=(0, 8), opacity=0.3, pad=30)

    # beneficios
    L['bens'] = bens_row([x for x in p.get('bens', []) if x.strip()][:3], check_icon(col, 80), 296, 110, (35, 35, 40, 255))

    return L

# ---------- composición por frame ----------
CX = 1440  # centro columna derecha

def paste(fr, layer, x, y, a=1.0, scale=1.0, anchor='mm'):
    if layer is None: return
    if scale != 1.0:
        if scale <= 0.01: return
        layer = layer.resize((max(1, int(layer.width * scale)), max(1, int(layer.height * scale))), Image.BILINEAR)
    layer = with_alpha(layer, a)
    if layer is None: return
    if anchor == 'mm': x, y = x - layer.width // 2, y - layer.height // 2
    fr.alpha_composite(layer, (int(x), int(y)))

def appear(t, start, dur=0.6): return ease_out_cubic((t - start) / dur)

WAVE = None

def render(L, p, t):
    fr = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    out = ease_in_cubic((t - (SLIDE - 0.6)) / 0.6)  # salida
    vis = 1 - out

    # ola
    fr.alpha_composite(WAVE, (0, H - 260))
    draw_logo(fr, LOGO_POS)

    # producto
    a = ease_out_back((t - 0.1) / 0.9, 1.2)
    float_y = math.sin((t - 0.1) * 2 * math.pi / 3.2) * 9 * ease_out_cubic((t - 1) / 1)
    px = 500 - 260 * (1 - a) - 320 * out
    py = 515 + float_y
    paste(fr, L['disc'], 500 - 320 * out, 515, min(1, appear(t, 0.0, 0.8)) * vis, scale=0.88 + 0.12 * ease_out_cubic(t / 0.8))
    paste(fr, L['pshadow'], px, py + L['prod'].height / 2 + 10, min(1, a) * vis * (1 - float_y / 40), scale=1 - float_y / 200)
    paste(fr, L['prod'], px, py, min(1, max(a, 0)) * vis, scale=0.85 + 0.15 * min(a, 1.05))

    if 'tag' in L:
        a = ease_out_back((t - 1.0) / 0.6, 2.4)
        tg = L['tag'].rotate(8 + math.sin(t * 2.4) * 3, resample=Image.BICUBIC, expand=True)
        tx = max(px - L['prod'].width / 2 + 90, 40 + tg.width / 2 - 30)
        ty = max(py - L['prod'].height / 2 + 10, 215)
        paste(fr, tg, tx, ty, min(1, max(a, 0)) * vis, scale=max(a, 0.01))

    sx = 160 * out  # textos salen a la derecha
    # nombre
    a = appear(t, 0.35); paste(fr, L['name'], CX + 80 * (1 - a) + sx, 160, a * vis)
    a = appear(t, 0.5);  paste(fr, L['sub'], CX + 80 * (1 - a) + sx, 250, a * vis)
    a = appear(t, 0.65); paste(fr, L['pres'], CX + 80 * (1 - a) + sx, 322, a * vis)
    if L['pill'] is not None:
        a = appear(t, 0.85); paste(fr, L['pill'], CX + 200 * (1 - a) + sx, 432 + L['pill'].height // 2 - L['pill_pad'] - 25, a * vis)

    # precio: pop + pulso + brillo
    pill_bottom = 432 + L['pill'].height - 2 * L['pill_pad'] - 25 if L['pill'] is not None else 410
    pcy = pill_bottom + 30 + L['price_face'][1] // 2 + 10
    a = ease_out_back((t - 1.15) / 0.6, 2.2)
    pulse = 1 + 0.025 * math.sin((t - 1.8) * 2 * math.pi / 1.4) * ease_out_cubic((t - 1.8) / 0.5)
    pr = L['price']
    # brillo
    for ts in (2.4, 5.0):
        k = (t - ts) / 0.8
        if 0 < k < 1:
            pr = pr.copy(); bw, bh = L['price_face']; pad = L['price_pad']
            sh = Image.new('L', pr.size, 0)
            x = pad - 200 + (bw + 400) * k
            ImageDraw.Draw(sh).polygon([(x, pad), (x + 90, pad), (x + 10, pad + bh), (x - 80, pad + bh)], fill=120)
            sh = sh.filter(ImageFilter.GaussianBlur(10))
            mask = rr_mask((bw, bh), 46); full = Image.new('L', pr.size, 0); full.paste(mask, (pad, pad))
            sh = ImageChops.multiply(sh, full)
            wl = Image.new('RGBA', pr.size, (255, 255, 255, 255)); wl.putalpha(sh)
            pr.alpha_composite(wl)
    pcx = CX - 90 if 'extra' in L else CX
    if 'old' in L:  # precio anterior a la izquierda del precio actual
        gw = 250 + L['price_face'][0]
        gl = max(pcx - gw / 2, 930)
        ocx, pcx = gl + 110, gl + 250 + L['price_face'][0] / 2
    paste(fr, pr, pcx + sx, pcy, min(1, max(a, 0)) * vis, scale=max(a, 0.01) * pulse)
    if 'extra' in L:
        a = ease_out_back((t - 1.6) / 0.6, 2.5)
        rot = math.sin(t * 2) * 4
        ex = L['extra'].rotate(-12 + rot, resample=Image.BICUBIC)
        paste(fr, ex, min(pcx + L['price_face'][0] // 2, W - 120) + sx, pcy - L['price_face'][1] // 2 + 30, min(1, max(a, 0)) * vis, scale=max(a, 0.01))

    if 'old' in L:
        a = ease_out_back((t - 1.5) / 0.6, 2.2)
        od = L['old'].rotate(6, resample=Image.BICUBIC, expand=True)
        paste(fr, od, ocx + sx, pcy - 8, min(1, max(a, 0)) * vis, scale=max(a, 0.01))

    # beneficios
    by = min(pcy + L['price_face'][1] // 2 + 80, 890)
    nb = len(L['bens'])
    for i, b in enumerate(L['bens']):
        a = ease_out_back((t - 1.7 - i * 0.18) / 0.5, 1.6)
        paste(fr, b, CX - 150 * (nb - 1) + i * 300 + sx, by + 30 * (1 - min(a, 1)), min(1, max(a, 0)) * vis)
    return fr.convert('RGB')

def render_intro(t):
    fr = Image.new('RGBA', (W, H), (255, 255, 255, 255))
    a = appear(t, 0.2, 0.6)                    # la ola sube al empezar (igual que el Generador de Promos)
    fr.alpha_composite(WAVE, (0, int(H - 260 + 260 * (1 - a))))
    cx, cy = W / 2, H / 2 - 50
    pop = ease_out_back((t - 0.1) / 0.9, 1.3)
    fade_out = ease_in_cubic((t - 2.3) / 0.7)              # al final: zoom suave y se desvanece
    sc = (0.8 + 0.2 * min(max(pop, 0), 1.06)) * (1 + 0.12 * fade_out)
    alpha = min(1, appear(t, 0.1, 0.5)) * (1 - fade_out)
    paste(fr, LOGO_BIG, cx, cy, alpha, scale=sc)
    # línea azul que se dibuja bajo el logo
    k = ease_out_cubic((t - 0.8) / 0.7)
    w = int(360 * k)
    if w > 4 and alpha > 0.01:
        ln = Image.new('RGBA', (w, 8), BLUE + (255,)); ln.putalpha(rr_mask((w, 8), 4))
        paste(fr, ln, cx, cy + LOGO_BIG.height * sc / 2 + 50, alpha)
    return fr.convert('RGB')


def build_wave():
    wave = Image.new('RGBA', (W * 2, 260 * 2), (0, 0, 0, 0)); dr = ImageDraw.Draw(wave)
    def band(y0, amp, c, ph):
        pts = [(x, (y0 + amp * math.sin(x / (W * 2) * math.pi * 1.6 + ph)) * 2) for x in range(0, W * 2 + 20, 20)]
        dr.polygon(pts + [(W * 2, 520), (0, 520)], fill=c)
    band(165, 30, lighten(BLUE, 0.55) + (255,), 0.4)
    band(178, 32, (200, 200, 205, 255), 0.1)
    band(188, 28, BLUE + (255,), 0.25)
    band(196, 20, NAVY + (255,), 0.0)
    dr.rectangle((0, 428, W * 2, 520), fill=NAVY + (255,))
    wave = wave.resize((W, 260), Image.LANCZOS)
    dr = ImageDraw.Draw(wave)
    dr.text((W - 40, 238), CONFIG.get('footer_right', ''), font=font(SEMI, 24), fill=(255, 255, 255, 230), anchor='rm')
    dr.text((40, 238), CONFIG.get('footer_left', ''), font=font(BOLD, 26), fill=(255, 255, 255, 255), anchor='lm')
    return wave

QUALITY = {'Máxima': (15, 'slow'), 'Alta': (18, 'medium'), 'Ligera': (23, 'medium')}

def export_images(products, config, folder, progress=None, t=4.0):
    """Guarda una imagen JPG 1920x1080 por producto (para WhatsApp, Facebook, impresión)."""
    import re
    _setup(config)
    os.makedirs(folder, exist_ok=True)
    out = []
    for i, p in enumerate(products):
        if progress: progress(i, len(products), p['name'])
        name = re.sub(r'[^\w\- ]', '', p['name']).strip() or 'producto'
        path = os.path.join(folder, f'{i + 1:02d}_{name}.jpg')
        L, R = build_any(p)
        R(L, p, t).save(path, quality=93)
        out.append(path)
    if progress: progress(len(products), len(products), 'Listo')
    return out

STYLES = {'destacado': 'Destacado', 'cortinilla': 'Cortinilla', 'minimal': 'Minimal'}

def build_any(p):
    """Devuelve (capas, función de render) según el estilo. El clásico se retiró (pasa a destacado);
    'terminal' es el anuncio de pago con tarjeta."""
    from . import estilos
    st = p.get('style')
    if st not in ('destacado', 'cortinilla', 'minimal', 'terminal'): st = 'destacado'
    return getattr(estilos, 'build_' + st)(p), getattr(estilos, 'render_' + st)

LOG_DIR = os.path.dirname(os.path.abspath(__file__))

def _setup(config):
    global SLIDE, CONFIG, WAVE
    CONFIG = dict(config)
    SLIDE = float(config.get('seconds', 8))
    load_logo(config.get('logo'))
    WAVE = build_wave()

def preview(product, config, t=4.0):
    """Devuelve un cuadro (imagen PIL) del producto ya animado."""
    _setup(config)
    global LOGO_ALPHA
    LOGO_ALPHA = 1.0
    L, R = build_any(product)
    return R(L, product, t)

def _encoder(path, crf, preset, log):
    return subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}',
                             '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-preset', preset, '-crf', str(crf),
                             '-pix_fmt', 'yuv420p', '-movflags', '+faststart', path],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def generate(products, config, out_path, progress=None, cancelled=lambda: False):
    """Genera el MP4. progress(cuadro_actual, total, texto). Devuelve False si se canceló.
    Si el video se repite, la entrada con el logo sale UNA sola vez al principio."""
    _setup(config)
    intro = bool(config.get('intro', True)) and LOGO_BIG is not None
    n = int(SLIDE * FPS); ni = int(INTRO * FPS) if intro else 0
    S = SLIDE
    total = ni + n * len(products); done = 0
    log = open(os.path.join(LOG_DIR, 'ffmpeg_log.txt'), 'w')
    crf, preset = QUALITY.get(config.get('quality', 'Alta'), QUALITY['Alta'])
    repeat = max(1, int(config.get('repeat', 1) or 1))
    final_path = out_path
    if repeat > 1:                     # intro y productos por separado; luego se unen: intro + productos x N
        intro_path = out_path[:-4] + '_intro_tmp.mp4'
        body_path = out_path[:-4] + '_tmp.mp4'
    else:
        intro_path = body_path = out_path
    procs = []
    try:
        if ni:
            pi = _encoder(intro_path, crf, preset, log); procs.append(pi)
            for i in range(ni):
                if cancelled(): raise KeyboardInterrupt
                pi.stdin.write(render_intro(i / FPS).tobytes()); done += 1
                if progress and i % 10 == 0: progress(done, total, 'Intro con logo')
            if repeat > 1:
                pi.stdin.close(); pi.wait()
        pb = pi if (ni and repeat == 1) else _encoder(body_path, crf, preset, log)
        if pb not in procs: procs.append(pb)
        global LOGO_ALPHA
        pos = [logo_pos_for(p.get('style') or 'destacado') for p in products]
        for j, p in enumerate(products):
            if progress: progress(done, total, 'Preparando ' + p['name'])
            L, R = build_any(p)
            prev = pos[j - 1] if j > 0 else None          # después de la entrada el logo aparece suave
            nxt = pos[j + 1] if j + 1 < len(products) else (pos[0] if not ni else None)
            if j == 0 and not ni: prev = pos[-1]           # bucle: el último cuadro enlaza con el primero
            for i in range(n):
                if cancelled(): raise KeyboardInterrupt
                t = i / FPS
                a_in = 1.0 if prev == pos[j] else ease_out_cubic(t / 0.5)
                a_out = 1.0 if nxt == pos[j] else 1 - ease_in_cubic((t - (S - 0.5)) / 0.5)
                LOGO_ALPHA = min(a_in, a_out)
                pb.stdin.write(R(L, p, t).tobytes()); done += 1
                if progress and i % 10 == 0: progress(done, total, p['name'])
        pb.stdin.close(); pb.wait()
    except KeyboardInterrupt:
        for pr in procs:
            try: pr.stdin.close()
            except Exception: pass
            pr.kill(); pr.wait()
        log.close()
        for f in {intro_path, body_path}:
            try: os.remove(f)
            except OSError: pass
        return False
    log.close()
    if any(pr.returncode != 0 for pr in procs): raise RuntimeError('ffmpeg falló, revisa ffmpeg_log.txt')
    if repeat > 1:
        if progress: progress(total, total, f'Repitiendo {repeat} veces...')
        lista = out_path[:-4] + '_lista.txt'
        with open(lista, 'w', encoding='utf-8') as f:
            for path in ([intro_path] if ni else []) + [body_path] * repeat:
                f.write("file '" + path.replace('\\', '/').replace("'", "'\\''") + "'\n")
        r = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-f', 'concat', '-safe', '0', '-i', lista,
                            '-c', 'copy', '-movflags', '+faststart', final_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        for f in (lista, body_path) + ((intro_path,) if ni else ()):
            try: os.remove(f)
            except OSError: pass
        if r.returncode != 0: raise RuntimeError('No se pudo repetir el video')
    if progress: progress(total, total, 'Listo')
    return True
