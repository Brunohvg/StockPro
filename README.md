# 📦 StockPro - Sistema de Gestão de Estoque Inteligente

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![Django](https://img.shields.io/badge/Django-5.2-green.svg)
![IA](https://img.shields.io/badge/IA-Grok--2-purple.svg)
![Version](https://img.shields.io/badge/Version-15.0-orange.svg)

Sistema SaaS B2B completo para gestão física de estoque com **Inteligência Artificial**, multi-localização, e foco em alta performance operacional.

---

## 🎯 Visão Geral
StockPro é uma plataforma robusta desenvolvida para resolver a complexidade do controle de estoque em empresas com múltiplos canais e variações de produtos. Com arquitetura **V10 (Normalizada)** e **Integração de IA (V15)**, o sistema automatiza processos de importação, gera insights estratégicos e garante a integridade dos dados financeiros.

---

## 🆕 Novidades V15 (Inteligência & Analytics)

### 🤖 Inteligência Artificial (AI-Powered)
- **Extração de Marcas**: Identificação automática de marcas reais a partir de nomes de fornecedores em XMLs de NF-e (IA Grok-2).
- **AI Insights**: Geração de sugestões estratégicas e acionáveis no dashboard de BI baseadas no comportamento do estoque.
- **Deduplicação Inteligente**: Algoritmo de 4 níveis para evitar duplicidade de produtos na importação.

### 📊 Business Intelligence Premium
- **Redesign Glassmorphism**: Interface analítica com estética moderna, dark mode e micro-animações.
- **Curva ABC Automatizada**: Identificação instantânea de produtos com maior capital imobilizado (Rankings Ouro, Prata e Bronze).
- **Performance de Variáveis**: Cálculos precisos de custo e valor total somando dinamicamente variações (Cores, Tamanhos, etc).

### 🇧🇷 Localização & UX
- **Padrão Brasileiro**: Formatação nativa de moeda (R$ 1.234,56) e quantidades em todo o sistema.
- **Safe Delete**: Bloqueio de deleção de itens com histórico de saída, protegendo a integridade fiscal.
- **Bulk Operations**: Gerenciamento em massa de produtos e variações.

---

## 🚀 Funcionalidades Principais

### Core Multi-tenant
- Isolamento completo de dados entre empresas.
- Hierarquia de usuário: OWNER, ADMIN e OPERATOR.
- Sistema de convites com tokens seguros.
- Trial Mode com controle de escrita dinâmico.

### Catálogo de Produtos
- **SIMPLE**: Produtos unitários.
- **VARIABLE**: Produtos com variantes (Pai/Filhos).
- **Atributos Dinâmicos**: Defina Cor, Tamanho, Voltagem, etc.
- **Consolidação**: Serviço inteligente para converter produtos simples em variações de um pai.

### Logística V2
- **Múltiplos Locais**: Controle de estoque por Depósito, Loja, Prateleira ou Trânsito.
- **Custo Médio Ponderado**: Recalculado automaticamente em cada entrada (IN).
- **Rastreabilidade**: Ledger completo de todas as movimentações (IN, OUT, ADJ).

---

## 🛠️ Stack Tecnológica

| Camada | Tecnologia |
|--------|------------|
| **Backend** | Django 5.2, Django Rest Framework |
| **IA/LLM** | Grok-2 (X.AI API) |
| **Frontend** | Tailwind CSS, HTMX, Lucide Icons, Chart.js |
| **Database** | PostgreSQL |
| **Cache/Worker** | Redis, Celery + Celery Beat |
| **Infra** | Docker Swarm, Traefik, Whitenoise |

---

## 📁 Arquitetura de Pastas

```
StockPro/
├── apps/
│   ├── accounts/     # Auth & Tenant Membership
│   ├── tenants/      # Multi-tenancy & Plan Guard
│   ├── products/     # Catálogo (Simple/Variable/Consolidade)
│   ├── inventory/    # Ledger, Locais & Import Tasks
│   ├── partners/     # Fornecedores & Mapeamento NF-e
│   ├── reports/      # BI & AI Insights
│   └── core/         # AIService & Global Utils
├── templates/        # UI (Modern/Glassmorphism)
├── static/           # Tailwind CSS & Assets
└── stock_control/    # Django Core Settings
```

---

## ⚡ Instalação Rápida (Dev)

1. **Clone & Venv**:
   ```bash
   git clone https://github.com/Brunohvg/StockPro.git
   cd StockPro
   python -m venv venv
   source venv/bin/activate
   ```

2. **Deps & Env**:
   ```bash
   pip install -r requirements.txt
   cp .env.example .env  # Configure suas chaves de API (XAI_API_KEY)
   ```

3. **DB & Seed**:
   ```bash
   python manage.py migrate
   python manage.py seed_db
   python manage.py seed_v2
   ```

4. **Run**:
   ```bash
   python manage.py runserver
   ```

---

## 🐳 Deploy Enterprise
O sistema está pronto para **Docker Swarm**. Use o script `deploy.sh` para gerenciar a stack:
```bash
./deploy.sh build v15
./deploy.sh deploy
```

---

## 👨‍💻 Autor
**Bruno Vidal** - [@Brunohvg](https://github.com/Brunohvg)
*Especialista em Engenharia de Software e IA Aplicada.*

---
⭐ Deixe sua estrela se este sistema foi útil para você!
