"""Geração de ZPL II para impressoras Zebra (ZD220, ZD230, GC420, GK420 etc.)."""
from .layout import Barcode, Box, Text, column_offset, dpmm, mm, page_width

MAX_LABELS = 2000


def escape(text):
    """Escapa os caracteres de comando para uso com ^FH_ (hexadecimal)."""
    return (str(text).replace('_', '_5F').replace('^', '_5E').replace('~', '_7E')
            .replace('\r', ' ').replace('\n', ' '))


def _element(el, dx):
    x = el.x + dx
    if isinstance(el, Text):
        return (f'^FO{x},{el.y}^A0N,{el.size},{el.size}'
                f'^FB{el.width},1,0,{el.align},0^FH_^FD{escape(el.text)}^FS')
    if isinstance(el, Barcode):
        head = f'^FO{x},{el.y}^BY{el.module},2,{el.height}'
        if el.kind in ('EAN13', 'EAN8'):
            # EAN desenhado barra a barra (^GB): as barras de guarda descem mais
            # (padrão do varejo) e o resultado é o mesmo em qualquer firmware.
            return _bars(el, dx)
        from .barcodes import code128_zpl_data
        return f'{head}^BCN,{el.height},N,N,N,N^FH_^FD{escape(code128_zpl_data(el.value))}^FS'
    if isinstance(el, Box):
        return f'^FO{x},{el.y}^GB{el.width},{el.height},{el.thickness}^FS'
    raise TypeError(el)


def _bars(el, dx):
    return ''.join(f'^FO{bx + dx},{el.y}^GB{w},{h},{w}^FS' for bx, w, h in el.bars())


def _header(cfg):
    dpi = int(cfg.dpi)
    parts = ['^XA', '^CI28', f'^PW{page_width(cfg)}', f'^LL{mm(cfg.height_mm, dpi)}', '^LH0,0', '^PON']
    dx = mm(cfg.offset_x_mm, dpi)
    dy = max(-120, min(120, mm(cfg.offset_y_mm, dpi)))
    if dx:
        parts.append(f'^LS{-dx}')
    if dy:
        parts.append(f'^LT{dy}')
    if cfg.darkness:
        parts.append(f'^MD{int(cfg.darkness)}')
    if cfg.print_speed:
        parts.append(f'^PR{int(cfg.print_speed)}')
    return ''.join(parts)


def render_row(labels, cfg, copies=1):
    """Um formato ^XA..^XZ com uma linha do rolo (1 etiqueta por coluna)."""
    body = [_header(cfg)]
    for col, label in enumerate(labels):
        dx = column_offset(cfg, col)
        body += [_element(el, dx) for el in label.elements]
    body.append(f'^PQ{max(1, int(copies))},0,1,Y^XZ')
    return '\n'.join(body)


def render_job(sequence, cfg):
    """
    sequence: lista de (chave, Label) na ordem de impressão, já repetida pela quantidade.
    Agrupa linhas iguais seguidas num só formato com ^PQ, para a impressora não
    receber o mesmo desenho centenas de vezes.
    """
    cols = max(1, int(cfg.columns))
    rows = [sequence[i:i + cols] for i in range(0, len(sequence), cols)]
    out, last_key, count, last_labels = [], None, 0, None
    for row in rows:
        key = tuple(k for k, _ in row)
        if key == last_key:
            count += 1
            continue
        if last_key is not None:
            out.append(render_row(last_labels, cfg, count))
        last_key, count, last_labels = key, 1, [lb for _, lb in row]
    if last_key is not None:
        out.append(render_row(last_labels, cfg, count))
    return '\n'.join(out) + '\n'


def calibrate_command():
    """Faz a impressora medir de novo o tamanho da etiqueta (sensor de gap)."""
    return '~JC'


def dots_per_mm(cfg):
    return dpmm(cfg.dpi)
