# Orientações para agentes — StockPro

## Comece aqui

Antes de alterar infraestrutura ou deploy, leia [docs/COOLIFY.md](docs/COOLIFY.md).
Para regras funcionais, leia [docs/SYSTEM_AI_DOC.md](docs/SYSTEM_AI_DOC.md).
Use o código e o estado atual do Git/Coolify como evidência; não trate esta documentação datada como monitoramento em tempo real.

## Contrato de produção a preservar

- Deploy validado em 09/10/2026: branch `feature/bibelo-coolify-deploy`, servidor Mexico, Coolify Compose com `/docker-compose.yml`.
- `docker-compose.yml` e `docker-compose.coolify.yml` são cópias equivalentes; altere ambas juntas.
- PostgreSQL 17 é recurso separado existente. Não adicionar outro banco nem migrar para SQLite como solução de deploy.
- Rede externa `coolify_shared` tem `name: coolify`; web, worker, beat e redis usam as redes default e compartilhada.
- No Coolify, preserve **Advanced → Predefined network → Connect to predefined network**. Esta configuração é do painel e não é recriada por Git.
- Serviço público: web, porta 8000, https://stock.optarys.com.br, HTTPS. DOMAIN/SITE_URL são explícitos no YAML atual.
- Preserve healthcheck `/healthcheck/` e localhost/127.0.0.1 em ALLOWED_HOSTS.
- Preserve volumes de media/imports/backups/Redis/Beat e bootstrap apenas na web.
- Nunca registrar senhas, DATABASE_URL real, chaves de IA ou segredo Django no Git.
- Não remover volumes, recriar banco ou mudar branch de produção silenciosamente.
- Ao trocar a branch implantada, integrar as correções e documentação na branch destino; não presumir que main já as contém.

## Evidência e entrega

Para mudança de Compose, validar YAML e igualdade das cópias, depois verificar deploy e logs quando o deploy estiver no escopo autorizado.
Para mudança funcional, executar testes pertinentes ao fluxo afetado.
Registrar em docs/COOLIFY.md alterações de infraestrutura, commit implantado, evidências e limites da validação.
Deploy verde não comprova login, estoque, importações, IA ou restauração.
Não enfraquecer o isolamento multi-tenant, permissões de TenantMembership ou a trilha de movimentações para corrigir infraestrutura.

## Preços

Leia [docs/PRICING.md](docs/PRICING.md). Preço padrão Empresarial: R$ 697/mês; Profissional: R$ 97; Gratuito: R$ 0. Plan.price no banco é a fonte das telas. Use novas migrações para mudar preços e preserve valores personalizados.
