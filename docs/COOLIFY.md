## Stack final (Coolify)

- Domínio do serviço web: `https://stock.optarys.com.br` (porta interna 8000).
- Banco: PostgreSQL 17 **já existente** em recurso separado; configure `DATABASE_URL` com URL interna.
- Serviços Compose: `web`, `worker`, `beat` e `redis`. Não cria banco adicional.
- Redis e conexões Celery: definidos no Compose, sem necessidade de .env.
- Beat executa os schedules do Django (incluindo a tarefa diária de backup).
- O Dockerfile instala `postgresql-client-17` para `pg_dump` compatível com o banco.
- `web` aplica `migrate`, `collectstatic` e criação idempotente do superusuário; `worker` e `beat` pulam o bootstrap.
- Volumes persistentes: arquivos, importações, backups, Redis e agenda do Beat.
- Variáveis para cadastrar no Coolify: `DATABASE_URL`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` e, conforme uso, `XAI_API_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY` ou `OPENAI_API_KEY`.
- Configurar domínio no serviço web, porta 8000, e conferir se Coolify preenche `SERVICE_FQDN_WEB_8000` e `SERVICE_URL_WEB_8000`.
- Certifique-se de que o endereço interno do PostgreSQL é acessível a partir da rede da stack.
- Backups em volume no mesmo servidor **não substituem** backups externos e testes de restauração.

**Ainda é preciso executar o primeiro build/deploy e smoke tests** no próprio Coolify para validar a operação completa. As credenciais reais não devem ir para o repositório.

## Domínio definido para a Bibelô

- URL pública: `https://stock.optarys.com.br`
- Serviço com domínio: `web` na porta interna `8000`
- SSL/Traefik: habilitar via Coolify
- `DOMAIN` e `SITE_URL`: recebidos das variáveis automáticas `SERVICE_FQDN_WEB_8000` e `SERVICE_URL_WEB_8000`
- Banco: PostgreSQL 17 existente, informado por `DATABASE_URL`
- Redis: serviço `redis` provisionado pelo Compose
- Celery: serviço `worker` provisionado pelo Compose; broker/backend são internos e não precisam constar no .env do painel

Verifique no editor de serviços do Coolify que o domínio foi associado à aplicação `web`, não ao `worker` ou `redis`.

# Deploy Coolify — Banco PostgreSQL existente

Esta stack usa o PostgreSQL 17 que já foi criado no Coolify. Não cria outro banco.

1. Em **Applications**, selecione o repositório `Brunohvg/StockPro`.
2. Branch: `feature/bibelo-coolify-deploy`.
3. Build Pack: **Docker Compose**.
4. Compose File: `/docker-compose.coolify.yml`.
5. Configure o domínio público no serviço `web`, porta `8000`.
6. Em Environment Variables defina `DATABASE_URL` com a **URL interna** do PostgreSQL existente, como segredo. Exemplo: `postgresql://usuario:senha@host-interno:5432/stockpro`.
7. Configure opcionalmente `DJANGO_SUPERUSER_EMAIL` e `DJANGO_SUPERUSER_PASSWORD` para criar o admin inicial.
8. Verifique se o banco e a aplicação compartilham a rede Docker necessária para resolução do host interno.
9. Faça deploy e confirme os logs de `web`, `worker` e `redis`, além de `/healthcheck/`.

O Coolify fornece `SERVICE_HEX_64_DJANGO` como segredo de Django e `SERVICE_FQDN_WEB_8000`/`SERVICE_URL_WEB_8000` para o domínio e URL da aplicação. Não é necessário configurar `DOMAIN` ou `SITE_URL` manualmente.

O banco é **externo a este Compose**; portanto a disponibilidade do PostgreSQL depende do recurso de banco separado no Coolify. O Docker entrypoint da web aguarda a conexão antes de migrar.

Redis e Celery permanecem incluídos no YAML. O Redis tem volume persistente. O worker usa o mesmo `DATABASE_URL` do serviço web e só inicia quando o healthcheck web estiver saudável.

## Alternativa: Dockerfile puro



Esta branch esta preparada para subir o StockPro diretamente pelo `Dockerfile`,
seguindo o mesmo padrao operacional usado no VidalysFlow.

## 1. Aplicacao

No Coolify:

- Source: GitHub
- Repository: `Brunohvg/StockPro`
- Branch: `feature/bibelo-coolify-deploy`
- Build Pack: Dockerfile
- Dockerfile: `/Dockerfile`
- Porta interna: `8000`
- Healthcheck: `/healthcheck/`

Nao e necessario definir Start Command. O comando de producao ja esta no Dockerfile.

## 2. PostgreSQL

Crie um PostgreSQL no mesmo projeto/rede do Coolify e copie a URL interna para:

```env
DATABASE_URL=postgresql://usuario:senha@host-interno:5432/stockpro
```

O sistema ainda aceita `DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` e
`DB_PORT` como fallback.

## 3. Variaveis minimas

```env
SECRET_KEY=uma-chave-forte
DEBUG=False
DOMAIN=estoque.seudominio.com.br
SITE_URL=https://estoque.seudominio.com.br
DATABASE_URL=postgresql://usuario:senha@host-interno:5432/stockpro
DJANGO_ADMIN_PATH=ops19x/
PORT=8000

DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@seudominio.com.br
DJANGO_SUPERUSER_PASSWORD=uma-senha-forte
```

Com `DOMAIN` e `SITE_URL`, normalmente nao e necessario configurar
`ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` manualmente.

## 4. Inicializacao automatica

A cada deploy o entrypoint:

1. espera o PostgreSQL ficar disponivel;
2. executa `python manage.py migrate --noinput`;
3. executa `python manage.py collectstatic --noinput`;
4. cria o superusuario inicial se as variaveis dele estiverem definidas e ele
   ainda nao existir;
5. inicia o Gunicorn.

O endpoint `/healthcheck/` e usado pelo Docker/Coolify.

## 5. Volumes persistentes recomendados

Configure volumes persistentes para:

- `/app/media` — arquivos enviados;
- `/data/backups` — backups;
- `/app/imports` — recomendado se importacoes forem processadas por worker.

## 6. Redis/Celery

O primeiro deploy web pode subir sem Celery. Para processamento em background,
adicione um Redis e configure:

```env
CELERY_BROKER_URL=redis://SEU_REDIS:6379/0
CELERY_RESULT_BACKEND=redis://SEU_REDIS:6379/1
```

Depois crie um segundo recurso no Coolify usando o mesmo repositorio, branch e
Dockerfile, mas sobrescreva o comando para:

```bash
celery -A stock_control worker -l info --concurrency=2
```

O worker deve receber as mesmas variaveis de banco e Django do servico web.

## 7. Gunicorn

Valores padrao:

```env
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
GUNICORN_TIMEOUT=120
```

Podem ser ajustados no Coolify sem reconstruir o codigo.
