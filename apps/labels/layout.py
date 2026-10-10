"""
Diagramação da etiqueta em pontos (dots) da impressora.

Um único desenho alimenta o ZPL (zpl.py) e a prévia em SVG (preview.py), para
que a prévia mostre exatamente o que a Zebra imprime.
"""
import math
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .barcodes import choose_code


@dataclass
class Text:
    x: int
    y: int
    width: int
    size: int
    text: str
    align: str = 'C'  # L, C, R


@dataclass
class Barcode:
    x: int
    y: int
    module: int
    height: int
    kind: str  # EAN13, EAN8, CODE128
    value: str
    modules: str


@dataclass
class Box:
    x: int
    y: int
    width: int
    height: int
    thickness: int = 2


@dataclass
class Label:
    width: int
    height: int
    elements: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class LabelItem:
    """O que vai impresso. Montado a partir da variação (services.item_from_variant)."""
    name: str
    variant: str = ''
    price: Decimal | None = None
    sku: str = ''
    barcode: str = ''
    store: str = ''


def dpmm(dpi):
    return 12 if int(dpi) >= 300 else 8


def mm(value, dpi):
    return int(round(float(value) * dpmm(dpi)))


def format_price(value):
    if value is None:
        return ''
    q = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    inteiro, centavos = f'{q:.2f}'.split('.')
    inteiro = f'{int(inteiro):,}'.replace(',', '.')
    return f'R$ {inteiro},{centavos}'


# Largura média dos caracteres da fonte 0 da Zebra (CG Triumvirate Bold
# Condensed), em fração da altura. Valores conservadores: melhor cortar uma
# letra antes do que deixar o texto passar da borda.
_NARROW = set("iIl1.,:;'|!()[]{} fjrt-")
_WIDE = set('MWmw@%')


def text_width(text, size):
    total = 0.0
    for ch in text:
        if ch in _NARROW:
            total += 0.30
        elif ch in _WIDE:
            total += 0.78
        elif ch.isupper() or ch.isdigit():
            total += 0.56
        else:
            total += 0.50
    return total * size


def fit_lines(text, size, width, max_lines):
    """Quebra em linhas que cabem na largura e corta com '...' o que sobrar."""
    text = ' '.join((text or '').replace('\\', '/').split())
    if not text:
        return []
    words = text.split(' ')
    lines, current = [], ''
    for word in words:
        candidate = f'{current} {word}'.strip()
        if text_width(candidate, size) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        while text_width(current, size) > width and len(current) > 1:
            # palavra maior que a linha: quebra no meio
            cut = len(current)
            while cut > 1 and text_width(current[:cut], size) > width:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and text_width(last + '...', size) > width:
            last = last[:-1].rstrip()
        lines[-1] = last + '...'
    return lines


def _single(text, size, width):
    lines = fit_lines(text, size, width, 1)
    return lines[0] if lines else ''


def build_label(item, cfg):
    """
    Desenha uma etiqueta (sem deslocamento de coluna).
    cfg: LabelSettings (ou objeto com os mesmos atributos).
    """
    dpi = int(cfg.dpi)
    W, H = mm(cfg.width_mm, dpi), mm(cfg.height_mm, dpi)
    label = Label(W, H)
    pad_x, pad_y = mm(1.5, dpi), mm(1.2, dpi)
    inner = W - 2 * pad_x
    gap = mm(0.6, dpi)

    base = min(max(H * 0.12, mm(2.2, dpi)), mm(5 if cfg.height_mm >= 40 else 4, dpi))
    base = min(base, inner / 9)

    code = choose_code(item.barcode, item.sku, cfg.code_source) if cfg.show_barcode else None
    if cfg.show_barcode and code is None:
        label.warnings.append('Sem código: cadastre o código de barras ou um SKU sem acentos.')

    price_text = format_price(item.price) if cfg.show_price else ''
    store_text = (cfg.store_text or item.store or '').strip() if cfg.show_store else ''
    variant_text = item.variant if cfg.show_variant else ''
    show_sku = cfg.show_sku and bool(item.sku)
    name_lines_max = 2 if cfg.height_mm >= 24 else 1

    min_bar = mm(5 if cfg.height_mm >= 25 else 4, dpi)
    max_bar = mm(16, dpi)

    def plan(scale, drop):
        f = int(round(base * scale))
        small = max(int(round(f * 0.74)), mm(1.8, dpi))
        big = int(round(f * 1.5))
        rows = []  # (kind, height)
        if store_text and 'store' not in drop:
            rows.append(('store', small))
        name_lines = fit_lines(item.name, f, inner, 1 if 'name2' in drop else name_lines_max)
        for _ in name_lines:
            rows.append(('name', f))
        if variant_text and 'variant' not in drop:
            rows.append(('variant', small))
        has_sku_row = show_sku and 'sku' not in drop
        if price_text or has_sku_row:
            rows.append(('price', big if price_text else small))
        used = sum(h for _, h in rows) + gap * max(len(rows) - 1, 0)
        bar = 0
        if code:
            used += gap + small + gap  # espaço antes, números embaixo
            bar = H - 2 * pad_y - used
        return {'f': f, 'small': small, 'big': big, 'rows': rows, 'name_lines': name_lines,
                'bar': bar, 'used': used, 'sku_row': has_sku_row}

    attempts = [(1.0, set()), (1.0, {'store'}), (1.0, {'store', 'variant'}),
                (1.0, {'store', 'variant', 'name2'}), (0.85, {'store', 'variant', 'name2'}),
                (0.85, {'store', 'variant', 'name2', 'sku'}), (0.72, {'store', 'variant', 'name2', 'sku'})]
    chosen = None
    for scale, drop in attempts:
        p = plan(scale, drop)
        if not code or p['bar'] >= min_bar:
            chosen = p
            break
    if chosen is None:
        chosen = p
        label.warnings.append('Etiqueta baixa demais: o código de barras ficou pequeno.')

    bar_h = min(chosen['bar'], max_bar) if code else 0
    total = chosen['used'] + bar_h
    y = pad_y + max(0, (H - 2 * pad_y - total) // 2)
    f, small, big = chosen['f'], chosen['small'], chosen['big']

    first_name = True
    sku_below = False
    for kind, h in chosen['rows']:
        if kind == 'store':
            label.elements.append(Text(pad_x, y, inner, small, _single(store_text.upper(), small, inner)))
        elif kind == 'name':
            line = chosen['name_lines'][0 if first_name else 1]
            first_name = False
            label.elements.append(Text(pad_x, y, inner, f, line))
        elif kind == 'variant':
            label.elements.append(Text(pad_x, y, inner, small, _single(variant_text, small, inner)))
        elif kind == 'price':
            if price_text and chosen['sku_row']:
                # Preço à esquerda com a linha inteira (nunca quebra); SKU à direita
                # só se sobrar espaço com folga. Senão o SKU vai para baixo do código.
                label.elements.append(Text(pad_x, y, inner, big, price_text, 'L'))
                sku_w = inner - int(text_width(price_text, big) * 1.2) - mm(1.5, dpi)
                if text_width(item.sku, small) <= sku_w:
                    label.elements.append(Text(W - pad_x - sku_w, y + big - small, sku_w, small, item.sku, 'R'))
                else:
                    sku_below = True
            elif price_text:
                label.elements.append(Text(pad_x, y, inner, big, price_text))
            else:
                label.elements.append(Text(pad_x, y, inner, small, _single(item.sku, small, inner)))
        y += h + gap

    if code:
        modules = code['modules']
        n = len(modules)
        avail = W - 2 * mm(1, dpi)
        cap = 6 if dpi >= 300 else 4
        module = min(cap, avail // (n + 2 * code['quiet']))
        if module < 1:
            module = min(cap, inner // n)
        if module < 1:
            label.warnings.append(f'Código "{code["value"]}" longo demais para {cfg.width_mm} mm de largura.')
        else:
            if module / dpmm(dpi) < 0.19:
                label.warnings.append('Barras muito finas para esta largura: teste a leitura do leitor antes de imprimir tudo.')
            bar_w = module * n
            x = (W - bar_w) // 2
            label.elements.append(Barcode(x, y, module, bar_h, code['kind'], code['value'], modules))
            hr = code['value']
            if sku_below and item.sku != code['value']:
                hr = f"{hr}  {item.sku}"
            label.elements.append(Text(pad_x, y + bar_h + gap // 2, inner, small, _single(hr, small, inner)))
    elif sku_below:
        label.elements.append(Text(pad_x, y, inner, small, _single(item.sku, small, inner)))
    return label


def build_test_label(cfg):
    """Etiqueta de teste: moldura 1 mm para dentro e as medidas configuradas."""
    dpi = int(cfg.dpi)
    W, H = mm(cfg.width_mm, dpi), mm(cfg.height_mm, dpi)
    label = Label(W, H)
    inset = mm(1, dpi)
    label.elements.append(Box(inset, inset, W - 2 * inset, H - 2 * inset, max(2, dpmm(dpi) // 4)))
    size = int(min(mm(4, dpi), H / 6))
    small = max(int(size * 0.7), mm(1.8, dpi))
    y = (H - size - small - mm(1, dpi)) // 2
    label.elements.append(Text(inset * 2, y, W - inset * 4, size, f'{cfg.width_mm} x {cfg.height_mm} mm'))
    label.elements.append(Text(inset * 2, y + size + mm(1, dpi), W - inset * 4, small, f'{dpi} dpi · teste StockPro'))
    return label


def page_width(cfg):
    dpi = int(cfg.dpi)
    cols = max(1, int(cfg.columns))
    return cols * mm(cfg.width_mm, dpi) + (cols - 1) * mm(cfg.column_gap_mm, dpi)


def column_offset(cfg, col):
    dpi = int(cfg.dpi)
    return col * (mm(cfg.width_mm, dpi) + mm(cfg.column_gap_mm, dpi))


def rows_for(count, columns):
    return math.ceil(count / max(1, columns))
