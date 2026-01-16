#!/bin/bash

# ===========================================
# StockPro V11 - Script de Deploy para Docker Hub
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
STACK_NAME="stockpro"
ENV_FILE=".env"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   StockPro V11 - Deploy Script${NC}"
echo -e "${BLUE}========================================${NC}"

# Verificar se Docker está rodando
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker não está rodando ou você não tem permissão.${NC}"
    exit 1
fi

# Menu de opções
show_menu() {
    echo ""
    echo -e "${YELLOW}Escolha uma opção:${NC}"
    echo "  1) build   - Build + Push para Docker Hub"
    echo "  2) deploy  - Deploy da stack no Swarm"
    echo "  3) update  - Atualizar serviços"
    echo "  4) logs    - Ver logs"
    echo "  5) status  - Ver status"
    echo "  6) migrate - Executar migrações"
    echo "  7) remove  - Remover stack"
    echo "  0) sair"
    echo ""
}

# ==== BUILD + PUSH ====
do_build() {
    echo ""
    echo -e "${YELLOW}🔨 BUILD + PUSH PARA DOCKER HUB${NC}"
    echo ""

    echo -n "Digite a TAG da versão (ex: v11, v11.1, latest): "
    read VERSION

    if [ -z "$VERSION" ]; then
        echo -e "${RED}Erro: A versão não pode ser vazia!${NC}"
        return 1
    fi

    FULL_IMAGE_NAME="$IMAGE_NAME:$VERSION"
    LATEST_IMAGE_NAME="$IMAGE_NAME:latest"

    echo ""
    echo -e "${GREEN}[1/3] Construindo imagem Docker...${NC}"
    if docker build -t $FULL_IMAGE_NAME -t $LATEST_IMAGE_NAME .; then
        echo -e "${GREEN}✅ Build com sucesso!${NC}"
    else
        echo -e "${RED}❌ Falha no Build. Verifique os erros acima.${NC}"
        return 1
    fi

    echo ""
    echo -e "${GREEN}[2/3] Enviando para o Docker Hub...${NC}"

    echo "Enviando tag: $VERSION..."
    docker push $FULL_IMAGE_NAME

    echo "Enviando tag: latest..."
    docker push $LATEST_IMAGE_NAME

    echo ""
    echo -e "${GREEN}[3/3] SUCESSO!${NC}"
    echo -e "Imagem enviada com as tags:"
    echo -e "  → $FULL_IMAGE_NAME"
    echo -e "  → $LATEST_IMAGE_NAME"
    echo ""
    echo -e "${YELLOW}Agora execute: ./deploy.sh e escolha 'deploy' ou 'update'${NC}"
}

# ==== DEPLOY STACK ====
do_deploy() {
    echo ""
    echo -e "${YELLOW}🚀 DEPLOY DA STACK NO SWARM${NC}"

    # Verificar se está em modo Swarm
    if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
        echo -e "${RED}❌ Docker Swarm não está ativo!${NC}"
        echo -e "${YELLOW}Execute: docker swarm init${NC}"
        return 1
    fi

    # Verificar arquivo .env
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}❌ Arquivo .env não encontrado!${NC}"
        echo -e "${YELLOW}Copie: cp .env.example .env${NC}"
        return 1
    fi

    # Carregar variáveis de ambiente
    export $(cat $ENV_FILE | grep -v '^#' | xargs)

    # Criar networks se não existirem
    echo "Criando networks..."
    docker network create --driver overlay traefik_public 2>/dev/null || true
    docker network create --driver overlay app_network 2>/dev/null || true

    # Deploy da stack
    echo "Deployando stack..."
    docker stack deploy -c docker-stack.yml ${STACK_NAME} --with-registry-auth

    echo ""
    echo -e "${GREEN}✅ Stack ${STACK_NAME} deployada!${NC}"
    echo ""
    echo -e "${BLUE}📊 Verificando serviços...${NC}"
    sleep 5
    docker stack services ${STACK_NAME}
}

# ==== UPDATE SERVICES ====
do_update() {
    echo ""
    echo -e "${YELLOW}🔄 ATUALIZAR SERVIÇOS${NC}"

    echo -n "Digite a TAG (ex: v11, latest): "
    read VERSION
    VERSION=${VERSION:-latest}

    echo "Atualizando serviços para ${IMAGE_NAME}:${VERSION}..."
    docker service update --image ${IMAGE_NAME}:${VERSION} ${STACK_NAME}_stockpro --force
    docker service update --image ${IMAGE_NAME}:${VERSION} ${STACK_NAME}_worker --force
    docker service update --image ${IMAGE_NAME}:${VERSION} ${STACK_NAME}_beat --force

    echo -e "${GREEN}✅ Serviços atualizados!${NC}"
}

# ==== LOGS ====
do_logs() {
    echo ""
    echo -e "${BLUE}📋 LOGS${NC}"
    echo "Serviços: stockpro, worker, beat, redis, migrate"
    echo -n "Qual serviço? [stockpro]: "
    read SERVICE
    SERVICE=${SERVICE:-stockpro}

    docker service logs -f ${STACK_NAME}_${SERVICE}
}

# ==== STATUS ====
do_status() {
    echo ""
    echo -e "${BLUE}📊 STATUS DA STACK${NC}"
    docker stack services ${STACK_NAME}
    echo ""
    echo -e "${BLUE}📦 Containers:${NC}"
    docker stack ps ${STACK_NAME} --format "table {{.Name}}\t{{.CurrentState}}\t{{.Error}}"
}

# ==== MIGRATE ====
do_migrate() {
    echo ""
    echo -e "${YELLOW}🔄 EXECUTANDO MIGRAÇÕES${NC}"
    docker service scale ${STACK_NAME}_migrate=1
    sleep 5
    docker service logs ${STACK_NAME}_migrate --follow
}

# ==== REMOVE ====
do_remove() {
    echo ""
    echo -e "${RED}⚠️  REMOVER STACK${NC}"
    read -p "Tem certeza que deseja remover ${STACK_NAME}? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        docker stack rm ${STACK_NAME}
        echo -e "${GREEN}✅ Stack removida!${NC}"
    else
        echo "Cancelado."
    fi
}

# ==== MAIN ====
main() {
    # Se passou argumento direto, usa ele
    case "${1:-menu}" in
        build)  do_build ;;
        deploy) do_deploy ;;
        update) do_update ;;
        logs)   do_logs ;;
        status) do_status ;;
        migrate) do_migrate ;;
        remove) do_remove ;;
        menu|*)
            while true; do
                show_menu
                echo -n "Opção: "
                read choice
                case $choice in
                    1|build)   do_build ;;
                    2|deploy)  do_deploy ;;
                    3|update)  do_update ;;
                    4|logs)    do_logs ;;
                    5|status)  do_status ;;
                    6|migrate) do_migrate ;;
                    7|remove)  do_remove ;;
                    0|exit|quit|q) echo "Bye!"; exit 0 ;;
                    *) echo -e "${RED}Opção inválida${NC}" ;;
                esac
            done
            ;;
    esac
}

main "$@"

echo -e "${BLUE}========================================${NC}"
