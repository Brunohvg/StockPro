# Deploy do StockPro no Coolify

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
