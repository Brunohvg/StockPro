#!/bin/bash

# ===========================================
# StockPro V16 - Script de Deploy para Docker Hub
# ===========================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

IMAGE_NAME="brunobh51/stockpro"
STACK_NAME="stockpro"
ENV_FILE=".env"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   StockPro V16 - Deploy Script${NC}"
echo -e "${BLUE}========================================${NC}"

if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}❌ Docker não está rodando ou você não tem permissão.${NC}"
    exit 1
fi

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
    echo -n "Digite a TAG da versão (ex: v1, v2, latest): "
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
        echo -e "${RED}❌ Falha no Build.${NC}"
        return 1
    fi

    echo ""
    echo -e "${GREEN}[2/3] Enviando para o Docker Hub...${NC}"
    docker push $FULL_IMAGE_NAME
    docker push $LATEST_IMAGE_NAME

    echo ""
    echo -e "${GREEN}[3/3] SUCESSO! Imagem: ${FULL_IMAGE_NAME}${NC}"
    echo -e "${YELLOW}Agora execute a opção 3 (update) para atualizar os serviços.${NC}"
}

# ==== DEPLOY STACK ====
do_deploy() {
    echo ""
    echo -e "${YELLOW}🚀 DEPLOY DA STACK NO SWARM${NC}"

    if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
        echo -e "${RED}❌ Docker Swarm não está ativo!${NC}"
        echo -e "${YELLOW}Execute: docker swarm init${NC}"
        return 1
    fi

    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${RED}❌ Arquivo .env não encontrado!${NC}"
        echo -e "${YELLOW}Copie: cp .env.example .env${NC}"
        return 1
    fi

    export $(cat $ENV_FILE | grep -v '^#' | grep -v '^$' | xargs)

    echo "Criando networks..."
    docker network create --driver overlay traefik_public 2>/dev/null || true
    docker network create --driver overlay app_network 2>/dev/null || true

    echo "Deployando stack..."
    docker stack deploy -c docker-stack.yml ${STACK_NAME} --with-registry-auth

    echo ""
    echo -e "${GREEN}✅ Stack ${STACK_NAME} deployada!${NC}"
    sleep 5
    docker stack services ${STACK_NAME}
}

# ==== UPDATE SERVICES ====
do_update() {
    echo ""
    echo -e "${YELLOW}🔄 ATUALIZAR SERVIÇOS${NC}"
    echo -n "Digite a TAG (ex: v2, latest): "
    read VERSION
    VERSION=${VERSION:-latest}

    # Nomes reais dos serviços: stockpro, stockpro_worker, stockpro_beat
    echo "Atualizando ${STACK_NAME}_stockpro..."
    docker service update --image ${IMAGE_NAME}:${VERSION} ${STACK_NAME}_stockpro --force

    echo "Atualizando ${STACK_NAME}_stockpro_worker..."
    docker service update --image ${IMAGE_NAME}:${VERSION} ${STACK_NAME}_stockpro_worker --force

    echo "Atualizando ${STACK_NAME}_stockpro_beat..."
    docker service update --image ${IMAGE_NAME}:${VERSION} ${STACK_NAME}_stockpro_beat --force

    echo ""
    echo -e "${GREEN}✅ Serviços atualizados para ${VERSION}!${NC}"
}

# ==== LOGS ====
do_logs() {
    echo ""
    echo -e "${BLUE}📋 LOGS${NC}"
    echo "Serviços: stockpro, stockpro_worker, stockpro_beat, stockpro_redis, migration"
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

    # Pega container do serviço stockpro (app principal)
    CONTAINER=$(docker ps --filter name=${STACK_NAME}_stockpro --format "{{.ID}}" | head -1)

    if [ -z "$CONTAINER" ]; then
        echo -e "${RED}❌ Container stockpro não encontrado. Stack está rodando?${NC}"
        return 1
    fi

    echo "Container: $CONTAINER"
    docker exec -it $CONTAINER python manage.py migrate --noinput
    echo "Coletando arquivos estáticos..."
    docker exec -it $CONTAINER python manage.py collectstatic --noinput
    echo -e "${GREEN}✅ Migrate e Collectstatic concluídos!${NC}"
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
    case "${1:-menu}" in
        build)   do_build ;;
        deploy)  do_deploy ;;
        update)  do_update ;;
        logs)    do_logs ;;
        status)  do_status ;;
        migrate) do_migrate ;;
        remove)  do_remove ;;
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
