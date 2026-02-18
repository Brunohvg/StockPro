#!/bin/bash

# ==============================================================================
# STOCKPRO ENTERPRISE - AUTOMATED DEPLOY SCRIPT
# ==============================================================================

set -e # Aborta se qualquer comando falhar

# Cores para o terminal
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  🚀 STOCKPRO ENTERPRISE - DEPLOY PIPELINE  ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# 1. Configurações
IMAGE_NAME="brunobh51/stockpro"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TAG=${1:-latest} # Aceita tag como argumento, padrão 'latest'

echo -e "\n📦 ${BLUE}Building image:${NC} ${IMAGE_NAME}:${TAG}..."

# 2. Build da Imagem
if docker build -t ${IMAGE_NAME}:${TAG} -t ${IMAGE_NAME}:latest .; then
    echo -e "✅ ${GREEN}Build concluído com sucesso!${NC}"
else
    echo -e "❌ ${RED}Falha no build da imagem.${NC}"
    exit 1
fi

# 3. Sugestão de Próximos Passos
echo -e "\n🚀 ${BLUE}Próximos passos recomendados:${NC}"
echo -e "1. Push para o Docker Hub:"
echo -e "   ${GREEN}docker push ${IMAGE_NAME}:${TAG}${NC}"
echo -e "   ${GREEN}docker push ${IMAGE_NAME}:latest${NC}"
echo -e "\n2. Fazer o deploy no Swarm (Cloud):"
echo -e "   ${GREEN}docker stack deploy -c docker-stack.yml stockpro${NC}"
echo -e "\n3. Subir localmente para testes (Compose):"
echo -e "   ${GREEN}docker-compose up -d${NC}"

echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
