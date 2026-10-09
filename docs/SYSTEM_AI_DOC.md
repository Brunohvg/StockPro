# 🧠 SYSTEM AI DOCUMENTATION (V16)

## 🏗️ Architectural Vision
O StockPro v16 evoluiu para um modelo de SaaS Multi-tenant robusto, onde a inteligência artificial não é apenas um "helper", mas a espinha dorsal da organização do catálogo.

---

### 🛡️ Core Rules (V16 Updates)
1. **Unicidade de SKU Global:** Um SKU é único no tenant, bloqueando colisões entre Produtos Simples e Variações.
2. **Standardization First:** Produtos novos geram SKUs no padrão `[SIM|VAR]-[CAT]-[ID]`.
3. **Ledger Imutável:** Movimentações de saída proíbem a exclusão do registro para manter trilha de auditoria (Safe Delete).
4. **Plan-Based Limits:** Limites de produtos e acesso a funções de IA são controlados dinamicamente via Plano.

### 🔐 Security & Isolation (Strict Tenant Model)
- **Tenant Isolation:** A arquitetura garante isolamento total de dados no nível da aplicação (`Application-Level Isolation`).
- **View-Level Security:** TODAS as views críticas (ex: listas de funcionários, produtos, fornecedores) aplicam filtros obrigatórios pelo `request.tenant` ou `TenantMembership`.
- **Membership Model:** O acesso de funcionários agora é gerenciado exclusivamente via `TenantMembership`, permitindo que um usuário (email) pertença a múltiplas empresas com permissões distintas (OWNER, ADMIN, OPERATOR) sem vazamento de dados.

---

### ⚙️ Domínios de Inteligência

#### 1. Consolidação Universal (Prefix-Match)
O `ConsolidationService` utiliza uma lógica de **Longest Common Prefix** para agrupar produtos que não possuem tags de atributos explícitas (ex: Cor, Tamanho). Se 70% do nome for comum, o sistema sugere a unificação em um produto variável.

#### 2. Deduplicação em 4 Níveis
Ao importar dados externos (XML/CSV):
1. **Match por EAN**: Código de barras idêntico.
2. **Match por Mapeamento**: Tradução SKU_FORNECEDOR -> SKU_INTERNO.
3. **Match por SKU Interno**: Código idêntico após limpeza de caracteres.
4. **Match por IA**: Análise semântica do nome se houver dúvida.

#### 3. Auditoria e Contagem (InventoryAudit)
O sistema utiliza o modelo `InventoryAudit` para sessões formais de contagem física.
- **Snapshot:** Congela o saldo esperado (`snapshot_stock`) no momento da criação.
- **Contagem:** Usuário insere o saldo real (`counted_stock`).
- **Conciliação:** O sistema gera automaticamente movimentações de ajuste (`ADJ`) para alinhar o estoque virtual com o físico.
- **Modo Cego:** Opção para ocultar o saldo esperado do operador durante a contagem.

---

### 📊 Business Intelligence Rules
- **Valor de Estoque**: Calculado somando `price * current_stock` de todas as variantes para produtos variáveis.
- **Curva ABC**: Baseia-se no Valor Total Imobilizado (Custo Médio * Estoque).
- **Formatos**: Moeda e Números seguem o padrão brasileiro (`pt-BR`).

---

## Deploy e continuidade operacional

Leia [../AGENTS.md](../AGENTS.md) e [COOLIFY.md](COOLIFY.md) antes de alterar infraestrutura. O deploy validado em 09/10/2026 usa Coolify Compose, PostgreSQL 17 separado e rede externa `coolify`. O guia registra o incidente de DNS do banco, a configuração necessária no painel, volumes, bootstrap e evidências de sucesso. Preserve as duas cópias de Compose ao integrar mudanças entre branches.
