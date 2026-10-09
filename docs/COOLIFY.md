# Recomendado: Docker Compose no Coolify

O deploy da Bibelô deve utilizar **docker-compose.coolify.yml** versionado nesta
branch, não o compose de desenvolvimento `docker-compose.yml`.

1. No Coolify, crie **New Resource → Application → GitHub**.
2. Selecione `Brunohvg/StockPro`, branch `feature/bibelo-coolify-deploy`.
3. Escolha **Docker Compose** como Build Pack.
4. Informe `/docker-compose.coolify.yml` como Compose File.
5. Salve. No serviço **web**, configure o domínio no painel do Coolify,
   com HTTPS habilitado. O serviço usa porta interna 8000.
6. Em **Environment Variables**, preencha apenas o necessário:
   `DJANGO_SUPERUSER_EMAIL` e `DJANGO_SUPERUSER_PASSWORD` para criar o
   primeiro admin. Recomenda-se manter estas variáveis em segredo.
7. Faça deploy e confira os logs do `web`, `db`, `redis` e `worker`.

O próprio Coolify gera e compartilha:
- `SERVICE_HEX_64_DJANGO`: segredo Django;
- `SERVICE_PASSWORD_64_POSTGRES`: senha do PostgreSQL 17;
- `SERVICE_FQDN_WEB_8000` e `SERVICE_URL_WEB_8000`: domínio e URL HTTPS
  escolhidos no painel do serviço web.

O Django recebe `DOMAIN` e `SITE_URL` a partir dessas variáveis.
Não é preciso duplicar domínio em um arquivo `.env`. O compose usa
`DB_HOST=db`, rede interna e PostgreSQL 17; não publica a porta 5432.

**Atenção:** o modo Compose cria um banco PostgreSQL novo. Não aponte uma
instância existente com dados de produção para esta stack sem backup e plano
de migração. A operação do StockPro/Bibelô ainda precisa de validação funcional,
mesmo que os contêineres iniciem corretamente.

---

# Alternativa: Dockerfile com banco externo

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
