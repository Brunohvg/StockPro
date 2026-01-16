# 📦 StockPro - Sistema de Gestão de Estoque Multi-tenant

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Django](https://img.shields.io/badge/Django-5.2-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

Sistema completo de gestão de estoque desenvolvido como SaaS multi-tenant, com dashboard em tempo real, importação de NF-e, Business Intelligence e operação mobile.

---

## 🚀 Funcionalidades

### Core
- ✅ **Multi-tenant**: Isolamento completo de dados por empresa
- ✅ **Dashboard**: Métricas em tempo real (estoque, valor, movimentações)
- ✅ **Produtos**: Cadastro completo com SKU, categoria, marca e custo médio
- ✅ **Movimentações**: Entrada, saída e ajuste de inventário com auditoria
- ✅ **Importação**: CSV de produtos e XML de NF-e (Nota Fiscal Eletrônica)

### SaaS
- ✅ **Landing Page**: Página de vendas com planos de assinatura
- ✅ **Self-Onboarding**: Cadastro self-service com consulta CNPJ automática
- ✅ **Planos**: Free, Starter, Pro e Enterprise com limites configuráveis
- ✅ **Configurações**: Personalização por empresa (logo, nome, regras)

### Técnico
- ✅ **API REST**: Endpoints para integração externa
- ✅ **Celery**: Processamento assíncrono de importações
- ✅ **Mobile-first**: Interface responsiva com Tailwind CSS
- ✅ **Docker Swarm**: Stack pronta para produção

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|------------|
| Backend | Django 5.2, Django REST Framework |
| Frontend | Tailwind CSS, HTMX, Chart.js, Lucide Icons |
| Database | PostgreSQL (prod) / SQLite (dev) |
| Cache/Broker | Redis |
| Task Queue | Celery |
| Deploy | Docker Swarm, Traefik, Gunicorn |

---

## ⚡ Instalação Local

### Pré-requisitos
- Python 3.11+
- Redis (opcional, para Celery)

### Setup
```bash
# Clonar repositório
git clone https://github.com/Brunohvg/StockPro.git
cd StockPro

# Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# Instalar dependências
pip install -r requirements.txt

# Rodar migrações
python manage.py migrate

# Criar superusuário
python manage.py createsuperuser

# Iniciar servidor
python manage.py runserver
```

Acesse: http://localhost:8000

---

## 🐳 Deploy com Docker Swarm

### 1. Configurar Variáveis
```bash
cp .env.example .env
nano .env  # Editar configurações
```

### 2. Build e Push
```bash
./deploy.sh latest build
./deploy.sh latest push
```

### 3. Deploy
```bash
./deploy.sh latest deploy
```

### Comandos Úteis
```bash
./deploy.sh latest status   # Ver status
./deploy.sh latest logs     # Ver logs
./deploy.sh latest update   # Atualizar imagem
./deploy.sh latest remove   # Remover stack
```

---

## 📁 Estrutura do Projeto

```
StockPro/
├── core/                   # App principal
│   ├── models.py          # Modelos (Tenant, Product, etc)
│   ├── views.py           # Views Django
│   ├── api.py             # API REST
│   ├── services.py        # Lógica de negócio
│   ├── tasks.py           # Tarefas Celery
│   ├── middleware.py      # TenantMiddleware
│   └── templates/         # Templates HTML
├── stock_control/          # Configurações Django
│   ├── settings.py        # Settings
│   ├── urls.py            # URLs raiz
│   ├── celery.py          # Config Celery
│   └── wsgi.py            # WSGI
├── docker-stack.yml        # Stack Docker Swarm
├── deploy.sh               # Script de deploy
├── Dockerfile              # Imagem Docker
├── requirements.txt        # Dependências Python
└── .env.example            # Template de variáveis
```

---

## 🔐 Variáveis de Ambiente

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `SECRET_KEY` | Chave secreta Django | `sua-chave-unica` |
| `DEBUG` | Modo debug | `False` |
| `ALLOWED_HOSTS` | Hosts permitidos | `stockpro.com.br` |
| `DB_HOST` | Host PostgreSQL | `postgres` |
| `DB_NAME` | Nome do banco | `stockpro_db` |
| `DB_USER` | Usuário do banco | `stockpro_user` |
| `DB_PASSWORD` | Senha do banco | `senha-segura` |
| `CELERY_BROKER_URL` | URL do Redis | `redis://redis:6379/0` |

---

## 📊 API Endpoints

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/v1/products/` | Listar produtos |
| POST | `/api/v1/products/` | Criar produto |
| GET | `/api/v1/movements/` | Listar movimentações |
| POST | `/api/v1/movements/` | Criar movimentação |

---

## 📄 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

## 👨‍💻 Autor

Desenvolvido por **Bruno Vidal**

- GitHub: [@Brunohvg](https://github.com/Brunohvg)
- Email: brunovidal27.19@gmail.com

---

⭐ Se este projeto te ajudou, deixe uma estrela no repositório!
