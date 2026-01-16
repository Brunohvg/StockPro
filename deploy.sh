#!/bin/bash

# ===========================================
# StockPro - Script de Deploy para Docker Swarm
# ===========================================

set -e

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configurações
IMAGE_NAME="brunobh51/stockpro"
IMAGE_TAG="${1:-latest}"
STACK_NAME="stockpro"
ENV_FILE=".env"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   StockPro - Deploy Script v1.0${NC}"
echo -e "${BLUE}========================================${NC}"

# Verificar se está em modo Swarm
if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
    echo -e "${RED}❌ Docker Swarm não está ativo!${NC}"
    echo -e "${YELLOW}Execute: docker swarm init${NC}"
    exit 1
fi

# Verificar arquivo .env
if [ ! -f "$ENV_FILE" ]; then
    echo -e "${RED}❌ Arquivo .env não encontrado!${NC}"
    echo -e "${YELLOW}Copie o .env.example para .env e configure:${NC}"
    echo -e "${YELLOW}cp .env.example .env${NC}"
    exit 1
fi

# Carregar variáveis de ambiente
export $(cat $ENV_FILE | grep -v '^#' | xargs)

# Menu de opções
case "${2:-deploy}" in
    build)
        echo -e "${YELLOW}🔨 Construindo imagem Docker...${NC}"
        docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
        echo -e "${GREEN}✅ Imagem construída: ${IMAGE_NAME}:${IMAGE_TAG}${NC}"
        ;;

    push)
        echo -e "${YELLOW}📤 Enviando imagem para registry...${NC}"
        docker push ${IMAGE_NAME}:${IMAGE_TAG}
        echo -e "${GREEN}✅ Imagem enviada: ${IMAGE_NAME}:${IMAGE_TAG}${NC}"
        ;;

    deploy)
        echo -e "${YELLOW}🚀 Iniciando deploy da stack...${NC}"

        # Criar networks se não existirem
        docker network create --driver overlay traefik_public 2>/dev/null || true
        docker network create --driver overlay app_network 2>/dev/null || true

        # Deploy da stack
        docker stack deploy -c docker-stack.yml ${STACK_NAME} --with-registry-auth

        echo -e "${GREEN}✅ Stack ${STACK_NAME} deployada com sucesso!${NC}"
        echo -e "${BLUE}📊 Verificando serviços...${NC}"
        sleep 5
        docker stack services ${STACK_NAME}
        ;;

    update)
        echo -e "${YELLOW}🔄 Atualizando serviço principal...${NC}"
        docker service update --image ${IMAGE_NAME}:${IMAGE_TAG} ${STACK_NAME}_stockpro
        docker service update --image ${IMAGE_NAME}:${IMAGE_TAG} ${STACK_NAME}_worker
        docker service update --image ${IMAGE_NAME}:${IMAGE_TAG} ${STACK_NAME}_beat
        echo -e "${GREEN}✅ Serviços atualizados!${NC}"
        ;;

    logs)
        SERVICE="${3:-stockpro}"
        echo -e "${BLUE}📋 Logs do serviço ${SERVICE}...${NC}"
        docker service logs -f ${STACK_NAME}_${SERVICE}
        ;;

    status)
        echo -e "${BLUE}📊 Status da stack ${STACK_NAME}:${NC}"
        docker stack services ${STACK_NAME}
        echo ""
        echo -e "${BLUE}📦 Containers em execução:${NC}"
        docker stack ps ${STACK_NAME} --no-trunc
        ;;

    migrate)
        echo -e "${YELLOW}🔄 Executando migrate...${NC}"
        docker service scale ${STACK_NAME}_migrate=1
        sleep 10
        docker service logs ${STACK_NAME}_migrate
        ;;

    remove)
        echo -e "${RED}⚠️  Removendo stack ${STACK_NAME}...${NC}"
        read -p "Tem certeza? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            docker stack rm ${STACK_NAME}
            echo -e "${GREEN}✅ Stack removida!${NC}"
        fi
        ;;

    *)
        echo -e "${YELLOW}Uso: ./deploy.sh [tag] [comando]${NC}"
        echo ""
        echo "Comandos disponíveis:"
        echo "  build   - Construir imagem Docker"
        echo "  push    - Enviar imagem para registry"
        echo "  deploy  - Fazer deploy da stack (padrão)"
        echo "  update  - Atualizar serviços com nova imagem"
        echo "  logs    - Ver logs de um serviço (ex: ./deploy.sh latest logs worker)"
        echo "  status  - Ver status da stack"
        echo "  migrate - Executar migrações"
        echo "  remove  - Remover stack"
        echo ""
        echo "Exemplos:"
        echo "  ./deploy.sh                  # Deploy com tag 'latest'"
        echo "  ./deploy.sh v1.0 build       # Build com tag 'v1.0'"
        echo "  ./deploy.sh v1.0 push        # Push da tag 'v1.0'"
        echo "  ./deploy.sh latest update    # Atualizar para 'latest'"
        ;;
esac

echo -e "${BLUE}========================================${NC}"
