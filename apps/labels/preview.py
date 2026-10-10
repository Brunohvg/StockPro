"""Prévia em SVG, desenhada com as mesmas medidas do ZPL."""
from django.utils.html import escape

from .layout import Barcode, Box, Text, column_offset, dpmm, mm, page_width, text_width

CONDENSE = 0.84

FONT = "'Roboto Condensed','Arial Narrow','Helvetica Neue',Arial,sans-serif"


def _element(el, dx):
    x = el.x + dx
    if isinstance(el, Text):
        # A fonte 0 da Zebra é condensada: a fonte do navegador é estreitada em 18%
        # e, se ainda passar da caixa, comprimida para caber (textLength).
        anchor = {'L': 'start', 'C': 'middle', 'R': 'end'}[el.align]
        tx = x if el.align == 'L' else (x + el.width / 2 if el.align == 'C' else x + el.width)
        size = round(el.size * 0.98)
        fit = ''
        if text_width(el.text, el.size) > el.width * 0.98:
            fit = f' textLength="{round(el.width / CONDENSE)}" lengthAdjust="spacingAndGlyphs"'
        return (f'<text transform="translate({tx} {el.y + round(el.size * 0.82)}) scale({CONDENSE} 1)" '
                f'font-size="{size}" text-anchor="{anchor}"{fit}>{escape(el.text)}</text>')
    if isinstance(el, Barcode):
        rects, i, mods = [], 0, el.modules
        while i < len(mods):
            if mods[i] == '1':
                j = i
                while j < len(mods) and mods[j] == '1':
                    j += 1
                rects.append(f'M{x + i * el.module} {el.y}h{(j - i) * el.module}v{el.height}h-{(j - i) * el.module}z')
                i = j
            else:
                i += 1
        return f'<path d="{"".join(rects)}" fill="#000"/>'
    if isinstance(el, Box):
        t = el.thickness
        return (f'<rect x="{x + t / 2}" y="{el.y + t / 2}" width="{el.width - t}" height="{el.height - t}" '
                f'fill="none" stroke="#000" stroke-width="{t}"/>')
    raise TypeError(el)


def render_svg(labels, cfg, scale_px_per_mm=None, liner=True, css_class='', title='', outline=True):
    """
    labels: lista com até `columns` Labels (uma linha do rolo).
    liner=True desenha o papel de fundo (liner) para parecer o rolo de verdade.
    outline=False tira o contorno das etiquetas (página para imprimir pelo navegador).
    """
    dpi = int(cfg.dpi)
    d = dpmm(dpi)
    cols = max(1, int(cfg.columns))
    W, H = mm(cfg.width_mm, dpi), mm(cfg.height_mm, dpi)
    PW = page_width(cfg)
    margin = mm(2, dpi) if liner else 0
    vw, vh = PW + 2 * margin, H + 2 * margin
    size = ''
    if scale_px_per_mm:
        size = f' width="{round(vw / d * scale_px_per_mm)}" height="{round(vh / d * scale_px_per_mm)}"'
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}"{size} '
           f'class="{escape(css_class)}" role="img" aria-label="{escape(title or "Prévia da etiqueta")}" '
           f'font-family="{FONT}" font-weight="700" fill="#000">']
    if liner:
        out.append(f'<rect width="{vw}" height="{vh}" fill="#efe9dc" rx="{d}"/>')
    radius = round(d * 0.8)
    for col in range(cols if outline else 0):
        ox = margin + column_offset(cfg, col)
        empty = col >= len(labels)
        fill = '#fbfbf8' if empty else '#ffffff'
        out.append(f'<rect x="{ox}" y="{margin}" width="{W}" height="{H}" rx="{radius}" fill="{fill}" '
                   f'stroke="#d8d2c4" stroke-width="{max(1, d // 4)}"/>')
    out.append(f'<g transform="translate({margin} {margin})">')
    for col, label in enumerate(labels[:cols]):
        dx = column_offset(cfg, col)
        out += [_element(el, dx) for el in label.elements]
    out.append('</g></svg>')
    return ''.join(out)
