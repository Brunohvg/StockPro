#!/bin/bash

# ===========================================
# StockPro - Backup Script para PostgreSQL
# ===========================================
# Uso:
#   ./backup.sh              # Backup manual
#   ./backup.sh restore      # Restaurar último backup
#   ./backup.sh list         # Listar backups
#
# Agendar no cron (diário às 2h):
#   0 2 * * * /path/to/backup.sh >> /var/log/stockpro-backup.log 2>&1
# ===========================================

set -e

# Cores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Configurações - ajuste conforme seu ambiente
BACKUP_DIR="/backup/stockpro"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="stockpro_backup_${DATE}.sql.gz"

# Carregar variáveis do .env se existir
if [ -f ".env" ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Variáveis do banco (do .env ou defaults)
DB_HOST=${DB_HOST:-postgres}
DB_NAME=${DB_NAME:-stockpro_db}
DB_USER=${DB_USER:-stockpro_user}
DB_PASSWORD=${DB_PASSWORD:-}
DB_PORT=${DB_PORT:-5432}

# Criar diretório de backup
mkdir -p "$BACKUP_DIR"

# ==== FUNÇÕES ====

do_backup() {
    echo -e "${YELLOW}🔄 Iniciando backup do PostgreSQL...${NC}"
    echo "   Host: $DB_HOST"
    echo "   Banco: $DB_NAME"
    echo "   Data: $(date)"

    # Backup comprimido
    PGPASSWORD="$DB_PASSWORD" pg_dump \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --no-owner \
        --no-acl \
        -F c \
        | gzip > "$BACKUP_DIR/$BACKUP_FILE"

    if [ $? -eq 0 ]; then
        SIZE=$(du -h "$BACKUP_DIR/$BACKUP_FILE" | cut -f1)
        echo -e "${GREEN}✅ Backup concluído: $BACKUP_FILE ($SIZE)${NC}"

        # Limpar backups antigos
        cleanup_old_backups

        # Opcional: enviar para S3/storage remoto
        # upload_to_s3
    else
        echo -e "${RED}❌ Erro no backup!${NC}"
        exit 1
    fi
}

do_backup_docker() {
    # Backup via Docker (se PostgreSQL estiver em container)
    echo -e "${YELLOW}🔄 Backup via Docker...${NC}"

    docker exec -t postgres pg_dump \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --no-owner \
        --no-acl \
        | gzip > "$BACKUP_DIR/$BACKUP_FILE"

    echo -e "${GREEN}✅ Backup Docker concluído: $BACKUP_FILE${NC}"
}

do_restore() {
    # Encontrar último backup
    LATEST=$(ls -t "$BACKUP_DIR"/stockpro_backup_*.sql.gz 2>/dev/null | head -1)

    if [ -z "$LATEST" ]; then
        echo -e "${RED}❌ Nenhum backup encontrado em $BACKUP_DIR${NC}"
        exit 1
    fi

    echo -e "${YELLOW}⚠️  ATENÇÃO: Isso irá sobrescrever o banco atual!${NC}"
    echo "   Arquivo: $LATEST"
    echo ""
    read -p "Tem certeza? (digite 'SIM' para confirmar): " confirm

    if [ "$confirm" != "SIM" ]; then
        echo "Cancelado."
        exit 0
    fi

    echo -e "${YELLOW}🔄 Restaurando backup...${NC}"

    gunzip -c "$LATEST" | PGPASSWORD="$DB_PASSWORD" pg_restore \
        -h "$DB_HOST" \
        -p "$DB_PORT" \
        -U "$DB_USER" \
        -d "$DB_NAME" \
        --clean \
        --if-exists \
        --no-owner \
        --no-acl

    echo -e "${GREEN}✅ Restauração concluída!${NC}"
}

list_backups() {
    echo -e "${YELLOW}📋 Backups disponíveis:${NC}"
    echo ""
    ls -lh "$BACKUP_DIR"/stockpro_backup_*.sql.gz 2>/dev/null || echo "Nenhum backup encontrado."
    echo ""
    echo "Total: $(ls "$BACKUP_DIR"/stockpro_backup_*.sql.gz 2>/dev/null | wc -l) arquivos"
    echo "Espaço: $(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1)"
}

cleanup_old_backups() {
    echo "Removendo backups com mais de $RETENTION_DAYS dias..."
    find "$BACKUP_DIR" -name "stockpro_backup_*.sql.gz" -mtime +$RETENTION_DAYS -delete
}

upload_to_s3() {
    # Descomente e configure para usar S3
    # S3_BUCKET="s3://seu-bucket/backups/stockpro"
    # aws s3 cp "$BACKUP_DIR/$BACKUP_FILE" "$S3_BUCKET/$BACKUP_FILE"
    # echo "Enviado para S3: $S3_BUCKET/$BACKUP_FILE"
    :
}

# Backup do media (fotos de produtos)
backup_media() {
    echo -e "${YELLOW}🔄 Backup de arquivos media...${NC}"

    MEDIA_BACKUP="stockpro_media_${DATE}.tar.gz"

    # Se usar Docker volumes
    docker run --rm \
        -v stockpro_media_volume:/data \
        -v "$BACKUP_DIR":/backup \
        alpine tar czf "/backup/$MEDIA_BACKUP" -C /data .

    echo -e "${GREEN}✅ Media backup: $MEDIA_BACKUP${NC}"
}

show_help() {
    echo "StockPro Backup Script"
    echo ""
    echo "Uso: ./backup.sh [comando]"
    echo ""
    echo "Comandos:"
    echo "  (sem args)    Fazer backup do banco"
    echo "  docker        Backup via Docker exec"
    echo "  restore       Restaurar último backup"
    echo "  list          Listar backups"
    echo "  media         Backup de arquivos media"
    echo "  full          Backup completo (banco + media)"
    echo "  help          Mostrar esta ajuda"
}

# ==== MAIN ====

case "${1:-backup}" in
    backup)     do_backup ;;
    docker)     do_backup_docker ;;
    restore)    do_restore ;;
    list)       list_backups ;;
    media)      backup_media ;;
    full)       do_backup && backup_media ;;
    help|--help|-h) show_help ;;
    *)          show_help ;;
esac
