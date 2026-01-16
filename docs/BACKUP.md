# 📦 StockPro - Guia de Backup e Restore

**Ambiente:** Oracle Cloud Free Tier + Docker Swarm + Portainer

---

## 📋 Visão Geral

| Componente | O que fazer backup |
|------------|-------------------|
| **PostgreSQL** | Banco de dados (produtos, movimentações, usuários) |
| **Media Volume** | Fotos de produtos, arquivos importados |
| **Redis** | Não precisa (cache, regenera automaticamente) |

---

## 🛠️ Pré-Requisitos

### No servidor Oracle:
```bash
# Instalar cliente PostgreSQL (para pg_dump)
sudo apt update
sudo apt install postgresql-client -y

# Criar diretório de backups
sudo mkdir -p /backup/stockpro
sudo chown $USER:$USER /backup/stockpro
```

---

## 🔄 Backup Manual

### 1. Via Script (Recomendado)

```bash
# Acessar pasta do projeto
cd /caminho/para/ControleEstoque

# Backup do banco
./backup.sh

# Backup de arquivos media
./backup.sh media

# Backup completo (banco + media)
./backup.sh full

# Ver backups existentes
./backup.sh list
```

### 2. Comando Direto (PostgreSQL externo)

```bash
# Variáveis do banco (ajuste conforme seu .env)
DB_HOST="IP_DO_POSTGRES"
DB_NAME="stockpro_db"
DB_USER="stockpro_user"
DB_PASSWORD="sua-senha"

# Backup
PGPASSWORD="$DB_PASSWORD" pg_dump \
    -h "$DB_HOST" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --no-owner \
    --no-acl \
    -F c \
    | gzip > /backup/stockpro/backup_$(date +%Y%m%d).sql.gz
```

### 3. PostgreSQL em Container Docker

Se o PostgreSQL roda em container na mesma VM:

```bash
# Nome do container PostgreSQL (verifique com: docker ps)
CONTAINER_NAME="postgres_db"

# Backup
docker exec -t $CONTAINER_NAME pg_dump \
    -U stockpro_user \
    -d stockpro_db \
    | gzip > /backup/stockpro/backup_$(date +%Y%m%d).sql.gz
```

---

## 📅 Backup Automático (Cron)

### Configurar Cron no Servidor Oracle

```bash
# Editar crontab do usuário
crontab -e

# Adicionar as linhas:

# Backup diário às 3h da manhã
0 3 * * * /home/ubuntu/ControleEstoque/backup.sh >> /var/log/stockpro-backup.log 2>&1

# Backup completo semanal (domingo às 4h)
0 4 * * 0 /home/ubuntu/ControleEstoque/backup.sh full >> /var/log/stockpro-backup.log 2>&1

# Limpar logs antigos (mensal)
0 0 1 * * find /var/log -name "stockpro-*.log" -mtime +30 -delete
```

### Verificar Cron

```bash
# Listar tarefas agendadas
crontab -l

# Ver logs do cron
sudo grep CRON /var/log/syslog
```

---

## 🔙 Restaurar Backup

### ⚠️ CUIDADO: Isso sobrescreve TODOS os dados atuais!

### Via Script

```bash
./backup.sh restore
# Digite 'SIM' para confirmar
```

### Comando Manual

```bash
# Descompactar e restaurar
gunzip -c /backup/stockpro/backup_20260116.sql.gz | \
    PGPASSWORD="sua-senha" pg_restore \
    -h "$DB_HOST" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    --clean \
    --if-exists \
    --no-owner
```

### Restaurar em Container Docker

```bash
# Copiar backup para container
docker cp /backup/stockpro/backup.sql.gz postgres_db:/tmp/

# Restaurar
docker exec -it postgres_db bash -c \
    "gunzip -c /tmp/backup.sql.gz | psql -U stockpro_user -d stockpro_db"
```

---

## 📁 Backup de Volumes Docker

### Media Volume (fotos de produtos)

```bash
# Identificar o volume
docker volume ls | grep media

# Backup do volume para arquivo tar
docker run --rm \
    -v stockpro_media_volume:/data \
    -v /backup/stockpro:/backup \
    alpine tar czf /backup/media_$(date +%Y%m%d).tar.gz -C /data .
```

### Restaurar Volume

```bash
# Restaurar media
docker run --rm \
    -v stockpro_media_volume:/data \
    -v /backup/stockpro:/backup \
    alpine sh -c "cd /data && tar xzf /backup/media_20260116.tar.gz"
```

---

## ☁️ Backup Remoto (Opcional)

### Oracle Object Storage (Gratuito no Free Tier)

```bash
# Instalar OCI CLI
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"

# Configurar (siga as instruções)
oci setup config

# Upload para bucket
oci os object put \
    --bucket-name "stockpro-backups" \
    --file /backup/stockpro/backup_20260116.sql.gz
```

### Adicionar ao backup.sh

Edite a função `upload_to_s3` no backup.sh:

```bash
upload_to_remote() {
    BACKUP_FILE="$1"
    oci os object put \
        --bucket-name "stockpro-backups" \
        --file "$BACKUP_FILE" \
        --force
    echo "Enviado para Oracle Object Storage"
}
```

---

## 📊 Monitoramento via Portainer

### Ver Logs do Backup

1. Acesse **Portainer**
2. Vá em **Stacks** → **stockpro**
3. Clique no serviço **migrate** (ou crie um serviço de backup)
4. Ver **Logs**

### Criar Tarefa de Backup no Portainer

1. Vá em **Stacks** → **stockpro**
2. Adicione um serviço temporário:

```yaml
backup:
  image: postgres:15-alpine
  command: >
    sh -c "pg_dump -h postgres -U stockpro_user -d stockpro_db | gzip > /backup/backup.sql.gz"
  environment:
    PGPASSWORD: ${DB_PASSWORD}
  volumes:
    - /backup/stockpro:/backup
  networks:
    - app_network
  deploy:
    replicas: 0
    restart_policy:
      condition: none
```

3. Para executar: escale para 1 replica, depois volte para 0

---

## 📝 Checklist de Backup

### Diário (Automático)
- [x] ✅ Backup do banco às 3h (cron)
- [x] ✅ Retenção de 30 dias

### Semanal
- [ ] Verificar se backups estão sendo criados
- [ ] Testar restore em ambiente de teste

### Mensal
- [ ] Fazer backup completo (banco + media)
- [ ] Enviar cópia para storage externo
- [ ] Limpar backups antigos

---

## 🆘 Troubleshooting

### Erro: "connection refused"
```bash
# Verificar se PostgreSQL está acessível
nc -zv $DB_HOST 5432
```

### Erro: "permission denied"
```bash
# Corrigir permissões
sudo chown $USER:$USER /backup/stockpro
chmod 755 /backup/stockpro
```

### Erro: "pg_dump: command not found"
```bash
# Instalar cliente PostgreSQL
sudo apt install postgresql-client -y
```

### Ver espaço em disco
```bash
df -h /backup
du -sh /backup/stockpro/*
```

---

## 📋 Resumo de Comandos

| Ação | Comando |
|------|---------|
| Backup banco | `./backup.sh` |
| Backup media | `./backup.sh media` |
| Backup completo | `./backup.sh full` |
| Listar backups | `./backup.sh list` |
| Restaurar | `./backup.sh restore` |
| Ver cron | `crontab -l` |
| Espaço usado | `du -sh /backup/stockpro` |

---

*Última atualização: Janeiro 2026*
