# CSS e JavaScript de terceiros

Nada de CDN em produção: tudo é servido pelo próprio sistema (WhiteNoise, com hash no nome).
A única exceção são as fontes do Google.

| O quê | Arquivo | Versão |
|---|---|---|
| Tailwind CSS | `static/css/app.css` (gerado) | 3.4.19 (`package.json`) |
| htmx | `static/vendor/htmx-1.9.10.min.js` | 1.9.10 |
| Ícones Lucide | `static/vendor/lucide-1.48.0.min.js` | 1.48.0 |
| Chart.js | `static/vendor/chart-4.5.1.umd.min.js` | 4.5.1 |
| Leitor de código de barras | `static/vendor/html5-qrcode-2.3.8.min.js` | 2.3.8 |
| Leitor na tela "Nova movimentação" | `static/js/scanner.js` | código nosso |

## Tailwind

O CSS é gerado a partir das classes encontradas em `templates/`, `apps/**/*.py` e `static/js/`.

```bash
npm ci            # uma vez
npm run build:css # depois de mexer em classes de templates
```

- O **Dockerfile regera o CSS em todo deploy** (etapa `assets`), então produção nunca fica sem uma classe nova.
- O `static/css/app.css` commitado serve para o `runserver` local. O CI (job `tailwind-css`) falha se ele estiver desatualizado.
- Escreva classes por extenso (`'text-rose-500'`). Classe montada por partes (`'text-' + cor + '-500'`) não é encontrada e fica sem estilo.
- O tema (fonte `Plus Jakarta Sans`, cores `brand-*`) fica em `tailwind.config.js`, igual ao que estava inline no `base.html`.

## Atualizar uma biblioteca

1. Baixe a versão nova do npm (`npm pack lucide@X.Y.Z`) e copie o `.min.js` para `static/vendor/` com a versão no nome.
2. Apague linhas `//# sourceMappingURL=...` (o collectstatic falha se o `.map` não existir).
3. Troque a referência nos templates e rode `pytest tests/test_patch6_assets.py`, que confere arquivos e nomes de ícones.
