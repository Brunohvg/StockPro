"""Formatação dos números da Visão Geral, da Inteligência e dos e-mails."""
from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _dec(value):
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _br(number_text):
    return number_text.replace(',', 'X').replace('.', ',').replace('X', '.')


@register.filter
def qtd(value):
    """Quantidade sem casas desnecessárias: 240,0000 -> 240; 2,5000 -> 2,5; 1250 -> 1.250."""
    d = _dec(value)
    if d == d.to_integral_value():
        return _br(f'{int(d):,}')
    text = _br(f'{d.quantize(Decimal("0.001")):,.3f}').rstrip('0').rstrip(',')
    return text


@register.filter
def brl(value, places=2):
    """R$ no formato brasileiro. {{ v|brl:0 }} sem centavos."""
    d = _dec(value)
    places = int(places)
    return 'R$ ' + _br(f'{d:,.{places}f}')


@register.filter
def pct(value, places=0):
    if value is None:
        return ''
    return _br(f'{float(value):.{int(places)}f}') + '%'


@register.inclusion_tag('reports/_change.html')
def change_badge(value, inverse=False):
    """▲ 12% / ▼ 5% com a cor certa. inverse=True quando subir é ruim (ex.: CMV)."""
    if value is None:
        return {'show': False}
    up = value >= 0
    good = None if inverse == 'neutral' else (up != bool(inverse))
    # base pequena gera % absurdo (de 4 para 179 = 4375%): mostra quantas vezes
    text = f'{abs(value) / 100 + 1:.0f}x' if value >= 200 else pct(abs(value))
    return {'show': True, 'up': up, 'good': good, 'neutral': good is None, 'text': text}


SOURCE_LABELS = {
    'NFE': 'NF-e', 'IMPORT': 'Planilha', 'MOVEMENTS': 'Planilha', 'MANUAL': 'Manual', 'API': 'Integração',
    'APP_MOBILE': 'Celular', 'MOBILE_APP': 'Celular', 'ARCHIVE': 'Arquivamento', 'NFE_REVERT': 'Estorno de NF-e',
    'PRODUCTS': 'Cadastro',
}


@register.filter
def mov_source(movement):
    label = SOURCE_LABELS.get(movement.source or '', (movement.source or 'Manual').title())
    if movement.source == 'NFE' and movement.source_doc:
        doc = str(movement.source_doc)
        if doc.isdigit() and len(doc) == 44:  # chave de acesso: o número da nota fica nas posições 26-34
            return f'NF-e {doc[25:34].lstrip("0") or "0"}'
        return f'NF-e {doc[:12]}'
    return label
