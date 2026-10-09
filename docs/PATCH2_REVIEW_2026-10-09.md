# Patch 2 e cadastro por CNPJ — 09/10/2026

Base: f3dbe22398d252fbbf17769bb9994eb8a7d0f434, branch feature/bibelo-coolify-deploy. Patch enviado pelo proprietário: stockpro-correcoes-2-api-mobile.patch; aplicado e revisado. Preservadas as correções do patch 1, WhiteNoise/--no-sendfile, preço R$697, banco/rede/volumes.

## Mudanças

API: criação de variantes com produto pai da mesma empresa, somente VARIABLE na criação, proibição de trocar pai, validação de SKU case-insensitive incluindo SKUs de produtos. Curadoria API/web exige OWNER/ADMIN e contexto de tenant ativo; aprovação/rejeição travam item, aprovação também trava tenant para serializar criação/limite. Quantidade/custo negativos ou não finitos são recusados; erro de entrada reverte criação e deixa item PENDING. Matching de SKU na aprovação é case-insensitive. Submissões em staging validam nome, SKU, barcode e custo antes de gravar. Curadoria web limita-se a source API (não processa importações CSV/NF-e por esta tela).

Resolução de empresa: X-Tenant-ID explícito tem prioridade e valida vínculo ativo. Autenticação de sessão sem header usa active_tenant_id; JWT não herda contexto de um cookie acidental. Rotas DRF passam pela própria permissão HasActiveTenant, evitando redirects de middleware para empresa errada. Endpoint legado de busca de fornecedores mantém middleware de tenant.

Mobile: resultados por textContent/listeners, histórico com campo type, quantidade com 4 casas (mesma precisão do ledger), logout POST com CSRF, scanner html5-qrcode 2.3.8 fixado. Scanner do gestor exige match exato para seleção automática. Tipos inválidos não viram OUT. Cancelamento espera inicialização/para câmera antes de liberar nova abertura. Câmera física não foi testada neste ambiente.

Throttling: DRF token/refresh20/min, usuário1200/h, anônimo300/h, CNPJ20/min; web encaminha API_THROTTLE_*, CACHE_URL e API_NUM_PROXIES nos dois Compose. Cache Redis DB2 separado de broker DB0/result DB1; tests usam cache local isolado antes de clear para jamais apagar cache Redis de produção. API_NUM_PROXIES=1 assume Traefik como último proxy confiável; ajustar se arquitetura de proxies mudar. Limites DRF não substituem proteção de borda/brute-force distribuído e login web ainda precisa de proteção própria.

## Consulta de CNPJ

A chamada antiga era direta do navegador para BrasilAPI, apenas no blur, sem timeout nem mensagem de erro visível. Não usa chave de API. Consulta sem autenticação a um CNPJ público de referência retornou HTTP200/JSON no ambiente de validação. Não foi reproduzida a falha específica do CNPJ do usuário nem determinado bloqueio de rede/navegador; não atribuir automaticamente a falta de chave.

Agora GET /partners/api/suppliers/cnpj/?cnpj=... é autenticado e limitado a OWNER/ADMIN e tenant ativo. Valida dígitos verificadores antes de chamar serviços fixos HTTPS, timeout curto e cache público24h, apenas campos necessários ao cadastro (sem quadro societário). BrasilAPI primária; ReceitaWS pública como fallback em indisponibilidade/dados incompletos, chamadas espaçadas por trava compartilhada21s para respeitar3/min. Fonte: https://developers.receitaws.com.br/ . Consulta404 preserva preenchimento manual. Não há assinatura comercial ou chave nova.

Formulário consulta automaticamente após completar14dígitos, também ao sair do campo, e tem botão Consultar CNPJ para repetir. Exibe erro/timeout/limite, descarta respostas atrasadas após trocar CNPJ e permite preenchimento manual. Não cria fornecedor automaticamente; usuário confere e salva. Inscrição estadual pode precisar de preenchimento manual. CEP continua consulta existente, não faz parte deste ajuste.

## Validação e limites

Python3.12, Django5.2.10, requirements fixados, SQLite temporário local:
- Testes focados de API/mobile/segurança/CNPJ/curadoria/estáticos:58passed,7subtests passed.
- Suíte completa:117passed,16failed,7subtests passed. Mesmas16falhas antigas do patch2 original; test_api_staging que falhava antes agora passa. Nenhuma suíte integral verde foi alegada.
- Novos testes: header/sessão/JWT, SKU do pai, quantidade negativa, custo inválido, matching case-insensitive, rollback, cache/fallback/erros/permissõesCNPJ.
- Scripts das três telas renderizados pelo Django e verificados com node --check:PASS.
- makemigrations --check --dry-run:No changes detected; sem migração/dependência nova.
- check --deploy:W005/W021 deliberadamente pendentes como antes.
- Compose YAML válido e cópias idênticas; git diff --check limpo.

Dados reais no histórico público, rotação de senhas, SMTP, ledger de exclusão, testes antigos, NF-e e backup externo permanecem fora desta mudança. Registrar resultado real do deploy em docs/COOLIFY.md após verificar. Fluxos autenticados/ câmera em produção não são comprovados por deploy verde.
