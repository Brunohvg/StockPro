# 🧠 SYSTEM AI DOCUMENTATION (V16)

## 🏗️ Architectural Vision
O StockPro v16 evoluiu para um modelo de SaaS Multi-tenant robusto, onde a inteligência artificial não é apenas um "helper", mas a espinha dorsal da organização do catálogo.

---

### 🛡️ Core Rules (V16 Updates)
1. **Unicidade de SKU Global:** Um SKU é único no tenant, bloqueando colisões entre Produtos Simples e Variações.
2. **Standardization First:** Produtos novos geram SKUs no padrão `[SIM|VAR]-[CAT]-[ID]`.
3. **Ledger Imutável:** Movimentações de saída proíbem a exclusão do registro para manter trilha de auditoria (Safe Delete).
4. **Plan-Based Limits:** Limites de produtos e acesso a funções de IA são controlados dinamicamente via Plano.

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

#### 3. Auditoria de Inventário
O sistema opera em dois modos de importação CSV:
- **Carga Inicial/Entrada (Normal)**: Adiciona ao saldo atual.
- **Modo Inventário (Inventory)**: Considera o valor da planilha como a VERDADE ABSOLUTA, criando movimentos `ADJ` para corrigir o saldo.

---

### 📊 Business Intelligence Rules
- **Valor de Estoque**: Calculado somando `price * current_stock` de todas as variantes para produtos variáveis.
- **Curva ABC**: Baseia-se no Valor Total Imobilizado (Custo Médio * Estoque).
- **Formatos**: Moeda e Números seguem o padrão brasileiro (`pt-BR`).
