# 📦 StockPro Enterprise v16.0

StockPro é uma plataforma de gestão de estoque de alta performance desenvolvida para empresas que buscam rigor na auditoria, inteligência na consolidação de dados e conformidade total com os padrões fiscais brasileiros.

---

## 🚀 Novidades da V16 (Premium Release)
- **💎 Gestão de Planos Dinâmica:** Controle total de limites (produtos/usuários) e ativação de empresas via Admin.
- **👥 Gestão de Equipe Enterprise:** Papéis granulares (Owner, Admin, Operator) com isolamento estrito via `TenantMembership`.
- **🔐 Strict Isolation Shield:** Arquitetura de segurança que garante 100% de segregação de dados entre empresas.
- **🏷️ SKU Standardization:** Gerador automático de códigos profissionais (`SIM-CAT-0001` / `VAR-CAT-0001-BLUE`).
- **🔍 Consolidação Universal:** Inteligência que agrupa qualquer tipo de variação de produto via prefixo comum.
- **📥 Modo Inventário (Sobrescrever):** Novo modo de upload CSV focado em contagem física (ajuste absoluto).
- **🛡️ Safe Delete Engine:** Motor de exclusão segura que preserva a integridade do Ledger fiscal.

---

## 🎯 Visão Geral
Sistema SaaS B2B completo para gestão física de estoque com **Inteligência Artificial**, multi-localização, e foco em alta performance operacional.

### 🤖 Inteligência Artificial (AI-Powered)
- **Extração de Marcas**: Identificação automática de marcas reais a partir de nomes de fornecedores em XMLs de NF-e (IA Grok-2).
- **AI Insights**: Geração de sugestões estratégicas e acionáveis no dashboard de BI baseadas no comportamento do estoque.
- **Deduplicação Inteligente**: Algoritmo de 4 níveis para evitar duplicidade de produtos na importação.

### 📊 Business Intelligence Premium
- **Redesign Glassmorphism**: Interface analítica com estética moderna, dark mode e micro-animações.
- **Curva ABC Automatizada**: Identificação instantânea de produtos com maior capital imobilizado (Rankings Ouro, Prata e Bronze).
- **Performance de Variáveis**: Cálculos precisos de custo e valor total somando dinamicamente variações.

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
│   ├── products/     # Catálogo (Simple/Variable/Consolidated)
│   ├── inventory/    # Ledger, Locais & Import Tasks
│   ├── partners/     # Fornecedores & Mapeamento NF-e
│   ├── reports/      # BI & AI Insights
│   └── core/         # AIService & Global Utils
├── templates/        # UI (Modern/Glassmorphism)
├── static/           # Tailwind CSS & Assets
└── stock_control/    # Django Core Settings
```

## Deploy atual e continuidade para IAs

O ambiente validado usa **Coolify + Docker Compose**, PostgreSQL 17 externo e Redis/Celery incluídos na stack. A configuração de produção está em `docker-compose.yml` e `docker-compose.coolify.yml` (iguais). O item Docker Swarm da tabela acima refere-se à infraestrutura legada, não ao deploy atual.

- [Guia de deploy, rede, segredos e diagnóstico](docs/COOLIFY.md)
- [Orientações para agentes e manutenção](AGENTS.md)
- [Regras funcionais para IAs](docs/SYSTEM_AI_DOC.md)

A configuração de domínio, branch, servidor e rede predefinida no painel Coolify também precisa ser preservada; veja o guia antes de atualizar ou recriar recursos.

Preços padrão atuais: Gratuito R$ 0, Profissional R$ 97/mês, Empresarial R$ 697/mês. Veja [precificação e migração](docs/PRICING.md).
