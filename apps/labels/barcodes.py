"""
Codificadores de código de barras usados na prévia e no cálculo de largura.

A impressora Zebra desenha as barras com os comandos nativos (^BE, ^B8, ^BC).
Aqui geramos exatamente a mesma sequência de módulos para:
- saber quanto espaço o código ocupa e escolher a espessura da barra (^BY);
- desenhar a prévia em SVG igual ao que sai na etiqueta.

Módulos: '1' = barra, '0' = espaço.
"""
import re

# --- EAN-13 / EAN-8 -------------------------------------------------------

_L = ['0001101', '0011001', '0010011', '0111101', '0100011',
      '0110001', '0101111', '0111011', '0110111', '0001011']
_R = [''.join('1' if b == '0' else '0' for b in code) for code in _L]
_G = [code[::-1] for code in _R]
_PARITY = ['LLLLLL', 'LLGLGG', 'LLGGLG', 'LLGGGL', 'LGLLGG',
           'LGGLLG', 'LGGGLL', 'LGLGLG', 'LGLGGL', 'LGGLGL']


def ean_check_digit(digits):
    """Dígito verificador GS1 para os dígitos sem o verificador."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def is_valid_ean13(code):
    return bool(code) and bool(re.fullmatch(r'\d{13}', code)) and ean_check_digit(code[:12]) == code[12]


def is_valid_ean8(code):
    return bool(code) and bool(re.fullmatch(r'\d{8}', code)) and ean_check_digit(code[:7]) == code[7]


def ean13_modules(code):
    """95 módulos de um EAN-13 (com o dígito verificador)."""
    first, left, right = int(code[0]), code[1:7], code[7:13]
    out = '101'
    for parity, ch in zip(_PARITY[first], left):
        out += (_L if parity == 'L' else _G)[int(ch)]
    out += '01010'
    for ch in right:
        out += _R[int(ch)]
    return out + '101'


def ean8_modules(code):
    """67 módulos de um EAN-8 (com o dígito verificador)."""
    return ('101' + ''.join(_L[int(c)] for c in code[:4]) + '01010'
            + ''.join(_R[int(c)] for c in code[4:8]) + '101')


# --- Code 128 -------------------------------------------------------------

_C128 = [
    '212222', '222122', '222221', '121223', '121322', '131222', '122213', '122312', '132212', '221213',
    '221312', '231212', '112232', '122132', '122231', '113222', '123122', '123221', '223211', '221132',
    '221231', '213212', '223112', '312131', '311222', '321122', '321221', '312212', '322112', '322211',
    '212123', '212321', '232121', '111323', '131123', '131321', '112313', '132113', '132311', '211313',
    '231113', '231311', '112133', '112331', '132131', '113123', '113321', '133121', '313121', '211331',
    '231131', '213113', '213311', '213131', '311123', '311321', '331121', '312113', '312311', '332111',
    '314111', '221411', '431111', '111224', '111422', '121124', '121421', '141122', '141221', '112214',
    '112412', '122114', '122411', '142112', '142211', '241211', '221114', '413111', '241112', '134111',
    '111242', '121142', '121241', '114212', '124112', '124211', '411212', '421112', '421211', '212141',
    '214121', '412121', '111143', '111341', '131141', '114113', '114311', '411113', '411311', '113141',
    '114131', '311141', '411131', '211412', '211214', '211232',
]
_STOP = '2331112'
_START_B, _START_C, _TO_B, _TO_C = 104, 105, 100, 99

# Caracteres aceitos no Code 128 B. '>' fica de fora porque é o prefixo dos
# códigos de controle do ^BC da Zebra.
CODE128_CHARSET = re.compile(r'^[\x20-\x3d\x3f-\x7e]+$')


def code128_encodable(text):
    return bool(text) and bool(CODE128_CHARSET.match(text))


def _digit_run(text, i):
    j = i
    while j < len(text) and text[j].isdigit():
        j += 1
    return j - i


def code128_tokens(text):
    """
    Divide o texto em trechos B (caracteres) e C (pares de dígitos), usando C
    quando economiza espaço. Retorna lista de (subconjunto, trecho).
    """
    tokens = []
    i, n = 0, len(text)
    current = None
    while i < n:
        run = _digit_run(text, i)
        if current == 'C':
            want_c = run >= 2
        else:
            want_c = run >= 4 and (current is None or run >= 6 or i + run == n)
        if want_c:
            if run % 2 and current != 'C':
                # número ímpar de dígitos: o primeiro vai em B
                tokens.append(('B', text[i]))
                i += 1
                run -= 1
            even = run - run % 2
            tokens.append(('C', text[i:i + even]))
            current = 'C'
            i += even
        else:
            tokens.append(('B', text[i]))
            current = 'B'
            i += 1
    merged = []
    for subset, chunk in tokens:
        if merged and merged[-1][0] == subset:
            merged[-1] = (subset, merged[-1][1] + chunk)
        else:
            merged.append((subset, chunk))
    return merged


def code128_values(text):
    """Valores dos símbolos (início, dados, verificador), sem o stop."""
    tokens = code128_tokens(text)
    values = []
    for idx, (subset, chunk) in enumerate(tokens):
        if idx == 0:
            values.append(_START_C if subset == 'C' else _START_B)
        else:
            values.append(_TO_C if subset == 'C' else _TO_B)
        if subset == 'C':
            values += [int(chunk[k:k + 2]) for k in range(0, len(chunk), 2)]
        else:
            values += [ord(ch) - 32 for ch in chunk]
    check = values[0]
    for pos, val in enumerate(values[1:], start=1):
        check += pos * val
    values.append(check % 103)
    return values


def code128_zpl_data(text):
    """Dado para o ^BC sem modo automático: subconjuntos explícitos (>: >; >5 >6)."""
    out = []
    for idx, (subset, chunk) in enumerate(code128_tokens(text)):
        if idx == 0:
            out.append('>;' if subset == 'C' else '>:')
        else:
            out.append('>5' if subset == 'C' else '>6')
        out.append(chunk)
    return ''.join(out)


def _widths_to_modules(widths):
    out, bar = [], True
    for w in widths:
        out.append(('1' if bar else '0') * int(w))
        bar = not bar
    return ''.join(out)


def code128_modules(text):
    values = code128_values(text)
    return ''.join(_widths_to_modules(_C128[v]) for v in values) + _widths_to_modules(_STOP)


# --- Escolha do código ----------------------------------------------------

def choose_code(barcode, sku, source='auto'):
    """
    Decide o que vai no código de barras.
    Retorna dict(kind, value, modules, quiet) ou None quando não há o que codificar.
    - auto: EAN-13/EAN-8 válido do cadastro; senão o código do cadastro em Code 128;
      sem código cadastrado, o SKU em Code 128.
    - sku: sempre o SKU em Code 128.
    """
    barcode = (barcode or '').strip()
    sku = (sku or '').strip()
    if source == 'auto' and barcode:
        if is_valid_ean13(barcode):
            return {'kind': 'EAN13', 'value': barcode, 'modules': ean13_modules(barcode), 'quiet': 9}
        if is_valid_ean8(barcode):
            return {'kind': 'EAN8', 'value': barcode, 'modules': ean8_modules(barcode), 'quiet': 7}
        if code128_encodable(barcode):
            return {'kind': 'CODE128', 'value': barcode, 'modules': code128_modules(barcode), 'quiet': 10}
    if sku and code128_encodable(sku):
        return {'kind': 'CODE128', 'value': sku, 'modules': code128_modules(sku), 'quiet': 10}
    return None
