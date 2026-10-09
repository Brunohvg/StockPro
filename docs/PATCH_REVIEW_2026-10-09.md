# Revisão e aplicação do patch de segurança — 09/10/2026

Base: `33fdfe1387670091614ef4d04787074c6d822c7f`, branch `feature/bibelo-coolify-deploy`. Patch enviado pelo proprietário: `stockpro-correcoes.patch`; aplicação sem conflitos.

## Resultado

Aplicadas validação obrigatória de senha em identificadores duplicados, checagens case-insensitive nos fluxos de cadastro/convite/funcionário, restrição de billing a superusuário, permissões administrativas das ações cobertas, contexto de empresa no mobile, acesso da API por empresa/status/trial, validações do ledger e isolamento de categoria/marca, proteção de gráficos por json_script e cookies/HTTPS/HSTS em produção.

Ajustes adicionais na revisão:
- Mobile rejeita tipos inválidos sem transformar ADJ em OUT; usa Decimal e bloqueia escrita com trial vencido.
- X-Tenant-ID malformado retorna 400; empresas múltiplas exigem header explícito.
- StockService rejeita produto de outra empresa antes de resolver/criar variante.
- Sem SMTP, produção usa dummy backend (nenhum envio); console só em DEBUG. Não expor tokens de recuperação nos logs. SMTP real ainda precisa ser configurado.
- Ambos os Compose encaminham EMAIL_* e opções HTTPS/HSTS à web. Nenhum segredo foi incluído.
- Teste do admin usa TestCase para compatibilidade com fechamento de resposta/sinais de conexão no pytest-django.
- Banco SQLite de backup e imports reais removidos da árvore atual do Git e ignorados. Volumes e dados de produção não foram removidos.

Preservados --no-sendfile, WhiteNoise com manifesto, migrations/preço Empresarial R$ 697, PostgreSQL externo, rede, volumes e healthchecks.

## Validação local

Python 3.12, Django 5.2.10 e requirements fixados, SQLite temporário de testes (produção permanece PostgreSQL 17).
- 29 regressões de segurança + teste de estáticos: 30 passed, 7 subtests passed.
- Suíte completa: 90 passed, 17 failed, 7 subtests passed.
- Comparação com base sem patch: 61 passed, mesmas 17 falhas funcionais e 7 subfalhas no teste de estáticos corrigido nesta revisão. Falhas antigas em API orders/staging, BI, import/export, inventory e normalization; não atribuir suíte verde ao projeto.
- makemigrations --check --dry-run: No changes detected. Não há migração nova.
- check --deploy: apenas security.W005 (HSTS subdomínios) e W021 (preload), deixados desabilitados deliberadamente sem validação de todos os subdomínios.
- git diff --check: limpo; Compose equivalentes.

## Limites e trabalho pendente

Este patch não torna o sistema pronto para abertura comercial irrestrita. Exclusão por administradores ainda pode apagar entradas/ajustes; permissões restantes da API e telas devem ser auditadas. Trial e IA ainda não têm controle completo em todos os fluxos. Não implementa NF-e, throttling de login/IA, unicidade de e-mail no banco nem atualização dos 17 testes antigos, backup externo ou build local do Tailwind.

O repositório é público. Os arquivos retirados ainda existem no histórico e em possíveis clones; isso não revoga a exposição. É necessário coordenar a limpeza de histórico e trocar as senhas das contas expostas. Não foi feito force-push nem rotação de credenciais. Não declarar e-mail funcionando sem SMTP real.

Deploy e logs: registrar evidência após implantação em docs/COOLIFY.md. Testes locais não comprovam fluxos autenticados na produção.
