"""Patch 6.3: CSS/JS servidos pelo próprio sistema, com versão fixa (sem CDN)."""
import re
from pathlib import Path

from django.conf import settings

TEMPLATES = Path(settings.BASE_DIR) / 'templates'
STATIC = Path(settings.BASE_DIR) / 'static'


def _templates():
    return [p for p in TEMPLATES.rglob('*.html')]


def test_nenhum_script_ou_css_de_cdn():
    """Só as fontes do Google continuam externas."""
    externos = []
    for path in _templates():
        for m in re.finditer(r'<(?:script|link)[^>]+(?:src|href)="(https?://[^"]+)"', path.read_text()):
            if not m.group(1).startswith(('https://fonts.googleapis.com', 'https://fonts.gstatic.com')):
                externos.append(f"{path.relative_to(TEMPLATES)}: {m.group(1)}")
    assert externos == []


def test_tailwind_nao_vem_mais_do_cdn():
    for path in _templates():
        text = path.read_text()
        assert 'cdn.tailwindcss.com' not in text and 'tailwind.config =' not in text, path


def _baixados_no_build():
    """Arquivos que scripts/fetch_vendor.mjs baixa (com checksum) durante o build do Docker."""
    script = Path(settings.BASE_DIR) / 'scripts' / 'fetch_vendor.mjs'
    if not script.is_file():
        return set()
    return {m.removeprefix('static/') for m in re.findall(r"writeFile\('([^']+)'", script.read_text())}


def test_arquivos_referenciados_existem():
    faltando = []
    no_build = _baixados_no_build()
    for path in _templates():
        for ref in re.findall(r"{% static '([^']+)' %}", path.read_text()):
            if not (STATIC / ref).is_file() and ref not in no_build:
                faltando.append(f"{path.relative_to(TEMPLATES)}: {ref}")
    assert faltando == []


def test_css_gerado_existe_e_tem_as_classes_do_layout():
    css = (STATIC / 'css' / 'app.css').read_text()
    for cls in ('.bg-slate-950', '.rounded-2xl', '.text-indigo-600', '.md\\:flex'):
        assert cls in css, cls


def test_vendor_sem_source_map_quebrado():
    """O collectstatic com manifest falha se o JS apontar para um .map inexistente."""
    for js in (STATIC / 'vendor').glob('*.js'):
        assert 'sourceMappingURL' not in js.read_text(errors='ignore'), js.name


def test_icones_usados_existem_no_lucide():
    """Nome de ícone errado some sem erro; conferimos contra o lucide empacotado."""
    lucide = next((STATIC / 'vendor').glob('lucide-*.min.js')).read_text()
    exported = set(re.findall(r'\.([A-Z][A-Za-z0-9]*)=', lucide))
    nomes = set()
    for path in _templates():
        text = path.read_text()
        nomes.update(re.findall(r'data-lucide="([a-z0-9-]+)"', text))
        nomes.update(re.findall(r"setAttribute\('data-lucide', *'([a-z0-9-]+)'\)", text))
    pascal = {n: ''.join(p[:1].upper() + p[1:] for p in n.split('-')) for n in nomes}
    faltando = sorted(n for n, p in pascal.items() if p not in exported)
    assert faltando == []
