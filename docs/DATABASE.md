# 🐘 StockPro - Guia de Deploy do PostgreSQL

**Ambiente:** Oracle Cloud Free Tier + Docker Swarm + Portainer

---

## 📋 Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│                      DOCKER SWARM                           │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │           STACK: stockpro (Principal)               │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐         │   │
│  │  │ stockpro  │ │  worker   │ │   beat    │         │   │
│  │  │ (Django)  │ │ (Celery)  │ │(Schedule) │         │   │
│  │  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘         │   │
│  │        └─────────────┼─────────────┘               │   │
│  │                      │                              │   │
│  │                ┌─────▼─────┐                        │   │
│  │                │   redis   │                        │   │
│  │                └───────────┘                        │   │
│  └──────────────────────┼──────────────────────────────┘   │
│                         │                                   │
│                    app_network (overlay)                    │
│                         │                                   │
│  ┌──────────────────────┼──────────────────────────────┐   │
│  │           STACK: stockpro_db (Banco)                │   │
│  │                ┌─────▼─────┐                        │   │
│  │                │ postgres  │                        │   │
│  │                │   :5432   │                        │   │
│  │                └─────┬─────┘                        │   │
│  │                      │                              │   │
│  │                ┌─────▼─────┐                        │   │
│  │                │ pgbackup  │ (backup automático)    │   │
│  │                └───────────┘                        │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 Deploy Passo a Passo

### 1. Criar Network (se ainda não existir)

```bash
docker network create --driver overlay app_network
```

### 2. Configurar Variáveis

Crie um arquivo `.env` para o banco:

```bash
# .env (mesmo do projeto principal)
DB_NAME=stockpro_db
DB_USER=stockpro_user
DB_PASSWORD=sua-senha-segura-aqui
```

### 3. Deploy da Stack do Banco

```bash
# Via terminal
docker stack deploy -c docker-stack-db.yml stockpro_db

# Verificar se subiu
docker service ls | grep stockpro_db
```

### 4. Deploy da Stack Principal

```bash
# Configurar DB_HOST para apontar ao serviço postgres
# No .env:
DB_HOST=postgres

# Deploy
docker stack deploy -c docker-stack.yml stockpro
```

---

## 📦 Via Portainer

### Deploy do Banco

1. Acesse **Portainer** → **Stacks**
2. Clique em **+ Add stack**
3. Nome: `stockpro_db`
4. Cole o conteúdo de `docker-stack-db.yml`
5. Em **Environment variables**, adicione:
   - `DB_NAME=stockpro_db`
   - `DB_USER=stockpro_user`
   - `DB_PASSWORD=sua-senha`
6. Clique em **Deploy the stack**

### Deploy do App Principal

1. **Stacks** → **+ Add stack**
2. Nome: `stockpro`
3. Cole o conteúdo de `docker-stack.yml`
4. Adicione todas as variáveis do `.env`
5. **IMPORTANTE:** `DB_HOST=postgres`
6. **Deploy the stack**

---

## 🔧 Configuração do .env

```env
# ===========================================
# Banco de Dados
# ===========================================
DB_HOST=postgres          # Nome do serviço no Swarm
DB_NAME=stockpro_db
DB_USER=stockpro_user
DB_PASSWORD=senha-muito-segura-123
DB_PORT=5432

# ===========================================
# Resto das configurações...
# ===========================================
SECRET_KEY=sua-chave-secreta
# ...
```

---

## 📊 Serviços da Stack de Banco

| Serviço | Descrição | Recursos |
|---------|-----------|----------|
| `postgres` | Banco PostgreSQL 15 | 512MB RAM, 0.5 CPU |
| `pgbackup` | Backup automático diário | 256MB RAM, 0.25 CPU |

---

## 🔄 Backup Automático

O serviço `pgbackup` faz backup automático:

- **Frequência:** A cada 24 horas
- **Local:** Volume `postgres_backup`
- **Retenção:** 7 dias (backups antigos são deletados)
- **Formato:** PostgreSQL custom dump (`.dump`)

### Ver backups

```bash
# Via Docker
docker exec $(docker ps -q -f name=stockpro_db_pgbackup) ls -la /backup

# Via volume (no servidor)
docker run --rm -v stockpro_db_postgres_backup:/backup alpine ls -la /backup
```

### Restaurar backup

```bash
# Acessar container postgres
docker exec -it $(docker ps -q -f name=stockpro_db_postgres) bash

# Restaurar
pg_restore -U stockpro_user -d stockpro_db --clean /backup/stockpro_20260116.dump
```

---

## 🩺 Healthcheck

O PostgreSQL tem healthcheck configurado:

```yaml
healthcheck:
  test: pg_isready -U stockpro_user -d stockpro_db
  interval: 10s
  retries: 5
```

### Verificar saúde

```bash
# Status do serviço
docker service ps stockpro_db_postgres

# Logs
docker service logs stockpro_db_postgres --tail 50
```

---

## 📈 Monitoramento

### Ver uso de recursos

```bash
# Stats dos containers
docker stats $(docker ps -q -f name=stockpro_db)
```

### Ver tamanho do banco

```bash
docker exec $(docker ps -q -f name=stockpro_db_postgres) \
    psql -U stockpro_user -d stockpro_db -c \
    "SELECT pg_size_pretty(pg_database_size('stockpro_db'));"
```

---

## 🔐 Segurança

### Alterar senha do banco

```bash
# Acessar postgres
docker exec -it $(docker ps -q -f name=stockpro_db_postgres) psql -U stockpro_user -d stockpro_db

# Alterar senha
ALTER USER stockpro_user WITH PASSWORD 'nova-senha-segura';

# Sair
\q

# Atualizar .env e redeploy das stacks
```

---

## 🆘 Troubleshooting

### Banco não inicia

```bash
# Ver logs
docker service logs stockpro_db_postgres

# Comum: problema de permissão no volume
docker volume rm stockpro_db_postgres_data
# E redeploy
```

### Conexão recusada

```bash
# Verificar se está na mesma network
docker network inspect app_network | grep -A5 stockpro

# Testar conexão
docker run --rm --network app_network postgres:15-alpine \
    pg_isready -h postgres -U stockpro_user
```

### Sem espaço em disco

```bash
# Ver espaço
df -h

# Limpar imagens não usadas
docker system prune -a

# Limpar volumes órfãos
docker volume prune
```

---

## 📋 Ordem de Deploy

1. **Primeiro:** Criar network
   ```bash
   docker network create --driver overlay app_network
   docker network create --driver overlay traefik_public
   ```

2. **Segundo:** Deploy do banco
   ```bash
   docker stack deploy -c docker-stack-db.yml stockpro_db
   # Aguardar ficar healthy (~30s)
   ```

3. **Terceiro:** Deploy da aplicação
   ```bash
   docker stack deploy -c docker-stack.yml stockpro
   ```

---

## 📁 Arquivos de Deploy

| Arquivo | Descrição |
|---------|-----------|
| `docker-stack-db.yml` | Stack do PostgreSQL |
| `docker-stack.yml` | Stack principal (Django, Celery, Redis) |
| `.env` | Variáveis de ambiente |
| `deploy.sh` | Script de automação |
| `backup.sh` | Script de backup |

---

*Última atualização: Janeiro 2026*
