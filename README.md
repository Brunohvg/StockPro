# 📦 StockPro V11 - Sistema de Gestão de Estoque Multi-tenant

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Django](https://img.shields.io/badge/Django-5.2-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)
![Version](https://img.shields.io/badge/Version-11.0-orange.svg)

Sistema completo de gestão de estoque SaaS B2B multi-tenant, com produtos simples e variáveis, import/export inteligente, autenticação multi-empresa e operação mobile-first.

---

## 🆕 Novidades V11

### Smart Auth & Multi-Empresa
- ✅ **TenantMembership**: Usuário pode pertencer a múltiplas empresas
- ✅ **Roles**: OWNER, ADMIN, OPERATOR com permissões diferenciadas
- ✅ **SmartLogin**: Detecção automática de empresa (1, N ou 0)
- ✅ **Convites**: Sistema de convites com token e expiração 7 dias
- ✅ **Trial Mode**: Bloqueio de escrita quando trial expira

### Produtos com Variações (V10)
- ✅ **SIMPLE/VARIABLE**: Produtos simples ou com variações
- ✅ **ProductVariant**: SKU, estoque e atributos por variação
- ✅ **AttributeType**: Cor, Tamanho, Voltagem, etc.
- ✅ **Import CSV**: Detecta tipo automaticamente

---

## 🚀 Funcionalidades

### Core
| Feature | Descrição |
|---------|-----------|
| **Multi-tenant** | Isolamento completo de dados por empresa |
| **Dashboard** | Métricas em tempo real (estoque, valor, movimentações) |
| **Produtos** | Simples e variáveis com SKU, categoria, marca |
| **Variações** | Atributos dinâmicos (cor, tamanho, etc.) |
| **Movimentações** | Entrada, saída, ajuste com auditoria |
| **Import CSV** | Produtos simples, variáveis e variantes |
| **Import XML** | NF-e (Nota Fiscal Eletrônica) |
| **Export** | CSV, Excel, JSON |

### Autenticação V11
| Feature | Descrição |
|---------|-----------|
| **Multi-empresa** | Usuário vinculado a N empresas |
| **Roles** | OWNER (tudo), ADMIN (gerenciar), OPERATOR (operar) |
| **Convites** | Convite por email com token 7 dias |
| **Trial** | Bloqueio de escrita quando expira |
| **SmartLogin** | Redirect inteligente baseado em empresas |

### SaaS
| Feature | Descrição |
|---------|-----------|
| **Landing Page** | Página de vendas com planos |
| **Self-Onboarding** | Cadastro self-service |
| **Planos** | FREE, STARTER, PRO, ENTERPRISE |
| **Billing** | Tela de upgrade quando bloqueado |

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|------------|
| Backend | Django 5.2, DRF, Celery |
| Frontend | Tailwind CSS, HTMX, Lucide Icons |
| Database | PostgreSQL (prod) / SQLite (dev) |
| Cache/Broker | Redis |
| Task Queue | Celery + Beat |
| Deploy | Docker Swarm, Traefik, Gunicorn |

---

## 📁 Estrutura do Projeto

```
StockPro/
├── apps/
│   ├── accounts/           # Auth, TenantMembership, Invites
│   │   ├── models.py       # TenantMembership, TenantInvite
│   │   └── views.py        # SmartLoginView, convites
│   ├── tenants/            # Multi-tenancy, Plans
│   │   ├── models.py       # Tenant, Plan
│   │   ├── middleware.py   # TenantMiddleware, decorators
│   │   └── views.py        # Landing, Billing, Signup
│   ├── products/           # Catálogo de produtos
│   │   ├── models.py       # Product, ProductVariant, Attributes
│   │   ├── views.py        # CRUD produtos/variações
│   │   └── forms.py        # Forms de produto
│   ├── inventory/          # Estoque e movimentações
│   │   ├── models.py       # StockMovement, ImportBatch
│   │   ├── views.py        # Movimentações, imports
│   │   └── tasks.py        # Celery tasks para import
│   ├── reports/            # Dashboard e relatórios
│   │   ├── views.py        # Dashboard, analytics
│   │   └── exports.py      # ProductExporter
│   └── core/               # Utilitários
│       ├── services.py     # StockService
│       └── context_processors.py
├── templates/              # Templates HTML
│   ├── accounts/           # Login, seleção empresa, convites
│   ├── products/           # Listagem, forms, detalhes
│   ├── inventory/          # Movimentações, imports
│   └── base.html           # Layout principal
├── stock_control/          # Configurações Django
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── docker-stack.yml        # Stack Docker Swarm
├── deploy.sh               # Script de deploy
├── Dockerfile              # Imagem Docker
└── .env.example            # Template de variáveis
```

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

# Instalar dependências
pip install -r requirements.txt

# Rodar migrações
python manage.py migrate

# Seed inicial (planos + admin)
python manage.py seed_db

# Iniciar servidor
python manage.py runserver
```

Acesse: http://localhost:8000
Login: `admin` / `admin123`

---

## 🐳 Deploy com Docker Swarm

### Arquitetura

```
┌─────────────────────────────────────────────────┐
│                 DOCKER SWARM                    │
├─────────────────────────────────────────────────┤
│  ┌───────────┐  ┌───────────┐  ┌───────────┐   │
│  │ stockpro  │  │  worker   │  │   beat    │   │
│  │ (Django)  │  │ (Celery)  │  │(Schedule) │   │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘   │
│        └──────────────┼──────────────┘         │
│                       │                        │
│                 ┌─────▼─────┐                  │
│                 │   Redis   │                  │
│                 └───────────┘                  │
└─────────────────────────────────────────────────┘
                        │
                  ┌─────▼─────┐
                  │PostgreSQL │ ← EXTERNO
                  └───────────┘
```

### 1. Configurar Variáveis
```bash
cp .env.example .env
nano .env  # Editar configurações
```

### 2. Build e Push
```bash
./deploy.sh build
# Digite a versão: v11
```

### 3. Deploy
```bash
./deploy.sh deploy
```

### Comandos do deploy.sh
```bash
./deploy.sh          # Menu interativo
./deploy.sh build    # Build + Push Docker Hub
./deploy.sh deploy   # Deploy no Swarm
./deploy.sh update   # Atualizar serviços
./deploy.sh status   # Ver status
./deploy.sh logs     # Ver logs
./deploy.sh migrate  # Executar migrações
./deploy.sh remove   # Remover stack
```

---

## 🔐 Variáveis de Ambiente

| Variável | Descrição | Exemplo |
|----------|-----------|---------|
| `SECRET_KEY` | Chave secreta Django | `gere-uma-chave-64-chars` |
| `DEBUG` | Modo debug | `False` |
| `ALLOWED_HOSTS` | Hosts permitidos | `stockpro.com.br,localhost` |
| `CSRF_TRUSTED_ORIGINS` | Origins para CSRF | `https://stockpro.com.br` |
| `DOMAIN` | Domínio para Traefik | `stockpro.com.br` |
| `DB_HOST` | Host PostgreSQL | `postgres-host` |
| `DB_NAME` | Nome do banco | `stockpro_db` |
| `DB_USER` | Usuário do banco | `stockpro_user` |
| `DB_PASSWORD` | Senha do banco | `senha-segura` |
| `DB_PORT` | Porta PostgreSQL | `5432` |
| `CELERY_BROKER_URL` | URL do Redis | `redis://redis:6379/0` |
| `DJANGO_SUPERUSER_EMAIL` | Email do admin | `admin@exemplo.com` |
| `DJANGO_SUPERUSER_PASSWORD` | Senha do admin | `senha-admin` |

---

## 📊 Modelo de Dados

### Autenticação V11

```
User ─────┬───── TenantMembership ─────┬───── Tenant
          │      (role, is_active)     │      (plan, status)
          │                            │
          └──── TenantInvite ──────────┘
               (token, expires_at)
```

### Produtos V10

```
Product (SIMPLE) ──── StockMovement
    │
    └── current_stock

Product (VARIABLE) ──┬── ProductVariant ──── StockMovement
                     │   (sku, stock)
                     │
                     └── VariantAttributeValue
                         (Cor: Vermelho)
```

---

## 📈 Import CSV

### Formato
```csv
sku,name,type,category,brand,stock,cost,attr_cor,attr_tamanho
PROD001,Produto Simples,SIMPLE,Categoria,Marca,100,10.50,,
CAMISETA,Camiseta,VARIABLE,Roupas,Nike,,,
CAM-VM-P,Camiseta Vermelho P,VARIANT:CAMISETA,,,50,25.00,Vermelho,P
CAM-VM-M,Camiseta Vermelho M,VARIANT:CAMISETA,,,50,25.00,Vermelho,M
```

### Tipos
- `SIMPLE`: Produto único com estoque próprio
- `VARIABLE`: Produto pai (sem estoque, soma das variantes)
- `VARIANT:SKU_PAI`: Variação de um produto variável

---

## 🔒 Roles e Permissões

| Role | Produtos | Estoque | Usuários | Billing |
|------|----------|---------|----------|---------|
| OWNER | ✅ | ✅ | ✅ | ✅ |
| ADMIN | ✅ | ✅ | ✅ | ❌ |
| OPERATOR | ✅ | ✅ | ❌ | ❌ |

### Decorators Disponíveis
```python
from apps.tenants.middleware import trial_allows_read, owner_required, admin_required

@login_required
@trial_allows_read  # Bloqueia POST quando trial expirado
def create_product(request):
    ...

@owner_required     # Só OWNER pode acessar
def billing_view(request):
    ...
```

---

## 📋 Changelog

### V11 (atual)
- Smart Auth com multi-empresa
- TenantMembership (substitui UserProfile)
- SmartLoginView com detecção de empresa
- Sistema de convites com expiração
- Trial mode com bloqueio de escrita
- Banner de upgrade no header

### V10
- Produtos SIMPLE e VARIABLE
- ProductVariant com atributos dinâmicos
- Import CSV inteligente
- ExportProductExporter (CSV/Excel/JSON)
- StockService com custo médio ponderado

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
