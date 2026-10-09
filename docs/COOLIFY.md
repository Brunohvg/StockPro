# Deploy de produção — Coolify

Última validação operacional: **09/10/2026, America/Sao_Paulo**.
Este documento substitui as instruções antigas de Dockerfile puro/Swarm para o ambiente atual.

## Ambiente validado

| Item | Configuração |
| --- | --- |
| Repositório | `Brunohvg/StockPro` |
| Branch implantada | `feature/bibelo-coolify-deploy` |
| Projeto / ambiente | StockPro / production |
| Servidor | Mexico |
| Build strategy | Compose, Managed by Coolify |
| Base directory | `/` |
| Compose utilizado no painel | `/docker-compose.yml` |
| Compose equivalente | `docker-compose.coolify.yml` (mesmo conteúdo) |
| Serviço público | `web`, porta interna `8000` |
| Domínio | https://stock.optarys.com.br |
| DNS / HTTPS | DNS matches; redirecionamento HTTP → HTTPS habilitado |
| Banco separado | `db-stockpro`, `postgres:17-alpine`, no servidor Mexico |
| Rede do banco | `coolify` |
| Advanced → Predefined network | **Connect to predefined network** |
| Serviços da aplicação | `web`, `worker`, `beat`, `redis` |

A branch acima é o estado implantado nesta data, não uma garantia sobre a branch usada no futuro. Antes de trocar para `main` ou outra branch, integre e confira os arquivos desta configuração. Não remova as correções ao resolver conflitos.

## O que está no Git e o que fica no painel

**No Git:** ambos os Compose definem rede externa, serviços, volumes, variáveis, dependências e healthchecks; o Dockerfile e o entrypoint definem a inicialização. Mantenha `docker-compose.yml` e `docker-compose.coolify.yml` iguais quando alterar a stack.

**No Coolify:** vínculo do GitHub/branch, servidor, caminho do Compose, domínio/porta, opção de rede predefinida e valores dos segredos. Um pull do Git não recria essas opções. Ao recriar o recurso, reaplique a tabela e confira o Compose deployable gerado.

O Compose já contém:

```yaml
networks:
  coolify_shared:
    external: true
    name: coolify
```

Os quatro serviços (`web`, `worker`, `beat`, `redis`) pertencem a `default` e `coolify_shared`. A rede `coolify` deve existir no mesmo servidor do banco. O endereço interno do PostgreSQL só resolve quando há rede compartilhada. Não substitua isso por IP fixo de container nem publique o PostgreSQL para contornar DNS.

## Variáveis e domínio

- `DATABASE_URL`: segredo obrigatório com a URL **interna** do PostgreSQL existente, porta 5432. Nunca copiar o valor real para Git, documentação ou logs.
- `SERVICE_HEX_64_DJANGO`: segredo gerado pelo Coolify, utilizado como `SECRET_KEY`; preserve o valor existente.
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` e `DJANGO_SUPERUSER_PASSWORD`: bootstrap opcional do administrador. Valores reais ficam no painel.
- Chaves de IA (`XAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`): opcionais, conforme integração.
- `DJANGO_ADMIN_PATH`, `WHATSAPP_SUPPORT`, opções Gunicorn e retenção de backup: configuráveis pelas variáveis previstas no Compose.

O Compose de produção fixa `DOMAIN=stock.optarys.com.br`, `SITE_URL=https://stock.optarys.com.br` e `ALLOWED_HOSTS=stock.optarys.com.br,localhost,127.0.0.1`. O domínio **não depende** das variáveis automáticas `SERVICE_FQDN_WEB_8000` e `SERVICE_URL_WEB_8000`. Estas podem continuar sendo geradas pelo Coolify para roteamento, mas não são a origem desses valores no YAML atual.

Não use wildcard em `ALLOWED_HOSTS`. Preserve localhost/127.0.0.1 para o healthcheck Docker. Para mudar domínio, atualize Compose, configuração do painel e origens CSRF coerentemente; o settings usa `SITE_URL` como padrão das origens CSRF.

Celery usa `redis://redis:6379/0` como broker e `redis://redis:6379/1` como backend; já estão no YAML. Preserve a conectividade e a resolução de `redis` após qualquer mudança de rede.

## Inicialização e persistência

A web aguarda o banco, executa `migrate --noinput`, `collectstatic --noinput`, bootstrap idempotente do administrador e inicia Gunicorn em 8000.
O entrypoint não redefine a senha de um administrador já existente.
Worker e Beat usam `SKIP_DJANGO_BOOTSTRAP=True` e aguardam web/Redis saudáveis antes de iniciar.

| Volume lógico no Compose | Caminho | Uso |
| --- | --- | --- |
| `stockpro_media` | `/app/media` | Arquivos enviados |
| `stockpro_imports` | `/app/imports` | Importações compartilhadas web/worker |
| `stockpro_backups` | `/data/backups` | Backups |
| `stockpro_beat` | `/data/celerybeat` | Agenda persistente |
| `stockpro_redis` | `/data` | Redis AOF |

O Coolify prefixa os nomes reais dos volumes pelo recurso. Não renomeie/remova volumes nem recrie o recurso sem plano de migração dos dados. Não executar `docker compose down -v` em produção.
O Dockerfile instala `postgresql-client-17`; o settings agenda backup diário no Beat. Isso configura a rotina, **não comprova que um backup/restauração funcionou**. Backups externos e restauração precisam de validação própria; veja [BACKUP.md](BACKUP.md).

## Incidente de 09/10/2026 e correção

O deploy anterior falhou com web unhealthy. Runtime Logs mostraram:
`could not translate host name ... to address: Temporary failure in name resolution`,
seguido de `Timeout aguardando banco de dados`.
O PostgreSQL estava saudável na rede `coolify`; no painel da aplicação estava selecionado **Isolated network only**.

Foi selecionado **Connect to predefined network**, confirmada a persistência após recarregar o painel e executado novo deploy.
O código implantado foi `b4095426653a742ce803c4a3ec338fe45c166696`, que também corrigiu o aninhamento de `depends_on` no Compose e a associação do Redis à rede compartilhada. As duas cópias de Compose nesse estado são idênticas.

Evidências observadas:
- deploy `vtmbjst8jxqvpvsegoh176wx`: **Success**; aplicação **Running**;
- migrações aplicadas sem erro e 166 arquivos estáticos coletados;
- Gunicorn iniciado em `0.0.0.0:8000`;
- `GET /healthcheck/` interno: **HTTP 200**;
- Redis healthy; worker conectado ao Redis e `ready`;
- Beat iniciado com agenda em `/data/celerybeat/celerybeat-schedule`;
- página pública abriu em HTTPS com conteúdo e estilos.

Não foram validados nesta intervenção: login autenticado do StockPro, operações de estoque, importações reais, chamadas de IA ou restauração de backup. Não declarar esses fluxos aprovados apenas porque o deploy ficou verde.

## Procedimento para próximas atualizações

1. Confira a branch efetivamente configurada no painel e preserve esta infraestrutura na branch de destino.
2. Valide os dois YAML e sua igualdade antes do push:
   ```bash
   diff -u docker-compose.yml docker-compose.coolify.yml
   docker compose -f docker-compose.yml config --quiet
   ```
   A segunda checagem exige as variáveis obrigatórias, especialmente `DATABASE_URL`, em ambiente seguro. Use credenciais fictícias na validação local; não imprimir configuração expandida com segredos.
3. Se alterar Compose, confira **Reload compose** e o **deployable compose**, sem sobrescrever configuração com YAML antigo.
4. Confira rede `coolify`, opção predefinida, PostgreSQL no mesmo servidor, domínio web:8000 e volumes existentes.
5. Execute deploy e confira Runtime Logs dos quatro serviços, migrações e healthcheck 200.
6. Abra a URL HTTPS. Quando houver mudança funcional, teste também o fluxo afetado com conta/dados apropriados.
7. Registre commit implantado, validações, limitações e mudanças de painel neste documento.

## Diagnóstico rápido

| Sintoma | Primeiro diagnóstico |
| --- | --- |
| Host PostgreSQL não resolve | Redes do Compose/painel, mesmo servidor e host da URL interna |
| Banco resolve mas falha autenticação | Usuário/senha/banco da DATABASE_URL; não recriar PostgreSQL |
| Web unhealthy | Runtime Logs, bootstrap/migrações, porta 8000 e localhost permitido |
| Celery não conecta | Host redis, redes comuns e saúde do Redis |
| 502 no domínio | Saúde web e roteamento Traefik para porta 8000 |
| Arquivos somem após deploy | Identidade e mounts dos volumes persistentes |

## Healthchecks dos serviços Celery

Após a validação inicial, o painel ficou Degraded embora web e Celery estivessem executando. O Dockerfile define um healthcheck HTTP; worker/Beat herdam a mesma imagem, mas não servem HTTP na porta 8000. Para evitar esse falso negativo, os dois Compose definem checagens próprias: worker responde a ping direcionado ao seu hostname via Celery, e Beat verifica seu processo PID 1 e conexão ao Redis. Preserve essas checagens em atualizações. A checagem do Beat comprova processo/broker disponíveis, não execução bem-sucedida de cada tarefa agendada.

## Admin sem estilos — 09/10/2026

O usuário relatou admin autenticado sem CSS. A mesma aparência foi reproduzida na primeira abertura do login; uma abertura posterior exibiu o estilo normal. A URL não versionada de base.css respondeu HTTP 200 com text/css e conteúdo correto. Isso confirma falha de carregamento observada, mas não prova a origem exata de uma resposta anterior/cache no navegador do usuário.

Para tornar a publicação determinística, STORAGES.staticfiles usa CompressedManifestStaticFilesStorage: collectstatic gera manifesto, nomes com hash e compressão; templates passam a apontar para a versão coletada. Em produção WHITENOISE_USE_FINDERS=False e manifesto estrito; não confiar em fallback de fontes ou ignorar referências faltantes. O entrypoint já coleta estáticos antes do Gunicorn.

Regressão tests/test_admin_staticfiles.py coleta arquivos reais do admin, exige URLs versionadas e serve CSS/JS com DEBUG=False e WhiteNoise, verificando HTTP 200, MIME correto e cache immutable. Validação local isolada com Django 5.2.10/WhiteNoise 6.11.0 passou. Após o redeploy, conferir admin/css/base, login, responsive, dark_mode, nav_sidebar e JS theme/nav_sidebar no manifesto; abrir login e conferir aparência. Não declarar operações autenticadas aprovadas sem login real. Se o navegador mantiver uma página antiga, recarregar com Ctrl+Shift+R.

### Causa confirmada na verificação externa

Os logs da web mostraram requests de CSS/JS com 200 e corpo de 0 bytes, seguidos de erro em gunicorn.http.wsgi.sendfile/socket.sendfile: ValueError: non-blocking sockets are not supported. O processo usa Gunicorn 24.0.0, worker gthread e Python 3.11. Isso explica o admin sem CSS mesmo com collectstatic bem-sucedido e arquivos existentes.

O CMD do Dockerfile agora inclui --no-sendfile, opção documentada pelo Gunicorn, para enviar arquivos pelo caminho de escrita normal compatível com os sockets do worker. Preserve essa opção; hash/cache de estáticos sozinho não resolve o erro de transporte. Teste local com Gunicorn 24.0.0, WhiteNoise e gthread: 28 downloads concorrentes de CSS completos, sem o erro. O teste local de manifesto/CSS/JS do admin também passou.

Revisão de segurança solicitada pelo usuário: [SECURITY_REVIEW_2026-10-09.md](SECURITY_REVIEW_2026-10-09.md). Achados críticos permanecem pendentes e não são resolvidos por este ajuste de infraestrutura.

### Verificação final do admin

Deploy ljaxnpduxtymcovulezcgrbk, commit 1c3776bec3c6cff2cf8aab2a08fa7191ca34654e: Success; aplicação Running em 09/10/2026, por volta de 12:25 America/Sao_Paulo. Após esse deploy, o login do admin abriu visualmente estilizado. As 5 folhas CSS (base, dark_mode, nav_sidebar, login, responsive) e os 2 scripts (theme, nav_sidebar) foram baixados em paralelo pela URL pública: HTTP 200, corpo presente, MIME correto e cache immutable. A verificação local de WhiteNoise/manifesto e a de Gunicorn gthread com 28 requests também passaram.

Nenhuma credencial foi inserida no admin nesta verificação; navegação autenticada não foi testada. O primeiro redeploy de manifesto sozinho teve Success mas não corrigiu o transporte; a prova visual e de downloads foi feita após --no-sendfile. O commit posterior de documentação não altera código executável.
