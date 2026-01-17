# 📦 StockPro V2 - Documentação Completa de Melhorias

**Versão:** 2.0.0  
**Data:** Janeiro 2026  
**Status:** ✅ Implementado  
**Arquiteto:** Engenharia de Software

---

## 📑 Sumário

1. [Visão Executiva](#1-visão-executiva)
2. [Arquitetura do Sistema](#2-arquitetura-do-sistema)
3. [Modelo de Dados](#3-modelo-de-dados)
4. [Service Layer](#4-service-layer)
5. [Motor de Importação Inteligente](#5-motor-de-importação-inteligente)
6. [Plano de Implementação](#6-plano-de-implementação)
7. [Guia de Migração](#7-guia-de-migração)
8. [Testes e Validação](#8-testes-e-validação)
9. [Checklist de Deploy](#9-checklist-de-deploy)

---

## 1. Visão Executiva

### 1.1 Objetivo

Transformar o StockPro em uma solução robusta para **Varejo Físico**, capaz de substituir sistemas legados, com foco em:

| Pilar | Descrição | Benefício |
|-------|-----------|-----------|
| **Rastreabilidade** | Controle por lote, validade e localização | Conformidade sanitária e fiscal |
| **Prevenção de Perdas** | Auditoria completa com motivos de ajuste | Redução de perdas em até 30% |
| **Importação Inteligente** | Deduplicação automática de NF-e | Zero duplicação de produtos |
| **Multi-Localização** | Estoque segregado por local físico | Visibilidade operacional |

### 1.2 Escopo da V2

```
┌─────────────────────────────────────────────────────────────┐
│                    STOCKPRO V2 - ESCOPO                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ✅ INCLUÍDO                    ❌ FORA DO ESCOPO           │
│  ─────────────                  ─────────────────           │
│  • Multi-Localização            • Módulo de Vendas          │
│  • Lotes e Validade             • Emissão de NF-e           │
│  • Fornecedores                 • Gestão de Clientes        │
│  • Import NF-e Inteligente      • E-commerce                │
│  • Auditoria de Ajustes         • Financeiro/Contas         │
│  • Transferência entre Locais   • Precificação              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Princípios de Design

| Princípio | Implementação |
|-----------|---------------|
| **Imutabilidade** | `StockMovement` é um ledger - nunca é editado/deletado |
| **Rastreabilidade** | Todo item rastreável até sua origem (fornecedor, NF-e, lote) |
| **Segregação** | Dados isolados por `Tenant` E por `Location` |
| **Deduplicação** | NUNCA criar produtos duplicados automaticamente |
| **Type Safety** | Type hints em 100% do código Python |

---

## 2. Arquitetura do Sistema

### 2.1 Stack Tecnológica

```
┌─────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│  Django Templates + HTMX + Tailwind CSS                     │
├─────────────────────────────────────────────────────────────┤
│                        BACKEND                               │
│  Django 5.2 (Modular Monolith)                              │
│  ├── apps/accounts     → Autenticação                       │
│  ├── apps/tenants      → Multi-tenancy                      │
│  ├── apps/products     → Catálogo                           │
│  ├── apps/inventory    → Estoque (V2)                       │
│  ├── apps/partners     → Fornecedores (NOVO)                │
│  ├── apps/reports      → Dashboard                          │
│  └── apps/core         → Utilitários                        │
├─────────────────────────────────────────────────────────────┤
│                     INFRAESTRUTURA                           │
│  PostgreSQL + Redis + Celery + Docker Swarm                 │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Diagrama de Dependências entre Apps

```
                    ┌─────────────┐
                    │   tenants   │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │ accounts │    │ products │    │ partners │
    └──────────┘    └────┬─────┘    └────┬─────┘
                         │               │
                         └───────┬───────┘
                                 │
                                 ▼
                         ┌─────────────┐
                         │  inventory  │
                         └──────┬──────┘
                                │
                                ▼
                         ┌─────────────┐
                         │   reports   │
                         └─────────────┘
```

### 2.3 Fluxo de Dados Principal

```
┌─────────┐    ┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│ Upload  │───▶│ NfeImport   │───▶│ StockService │───▶│ StockMove-  │
│  XML    │    │   Service   │    │              │    │    ment     │
└─────────┘    └─────────────┘    └──────────────┘    └─────────────┘
                     │                   │
                     ▼                   ▼
              ┌─────────────┐    ┌─────────────┐
              │  Supplier   │    │   Product   │
              │ProductMap   │    │  (stock++)  │
              └─────────────┘    └─────────────┘
```

---

## 3. Modelo de Dados

### 3.1 Visão Geral (ERD)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MODELO DE DADOS V2                            │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│    Tenant    │─────────│   Location   │─────────│StockMovement │
│              │   1:N   │              │   1:N   │              │
│ • name       │         │ • code       │         │ • type       │
│ • plan       │         │ • name       │         │ • quantity   │
│ • status     │         │ • type       │         │ • batch_no   │
└──────────────┘         │ • parent     │         │ • expiry_date│
                         │ • is_default │         │ • location   │
                         └──────────────┘         └──────────────┘
                                                         │
                                                         │ N:1
                                                         ▼
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│   Supplier   │─────────│SupplierProd- │─────────│   Product    │
│              │   1:N   │    uctMap    │   N:1   │              │
│ • cnpj       │         │              │         │ • sku        │
│ • name       │         │ • supplier_  │         │ • name       │
│ • address    │         │   sku        │         │ • barcode    │
│ • terms      │         │ • last_cost  │         │ • stock      │
└──────────────┘         └──────────────┘         └──────────────┘

┌──────────────┐         ┌──────────────┐
│ Adjustment   │─────────│   Pending    │
│   Reason     │         │ Association  │
│              │         │              │
│ • code       │         │ • supplier   │
│ • name       │         │ • nfe_key    │
│ • impact     │         │ • status     │
│ • requires_  │         │ • match_     │
│   note       │         │   suggestions│
└──────────────┘         └──────────────┘
```

### 3.2 Detalhamento dos Modelos

#### 3.2.1 Location (Multi-Localização)

**Arquivo:** `apps/inventory/models_v2.py`

```python
class Location(TenantMixin):
    """
    Representa um local físico de armazenamento.
    Suporta hierarquia: Depósito > Corredor > Prateleira
    """
    code: str           # "LOJ-001" (único por tenant)
    name: str           # "Loja Centro"
    location_type: str  # STORE, WAREHOUSE, SHELF, DISPLAY, TRANSIT, QUARANTINE
    parent: FK(self)    # Hierarquia opcional
    is_default: bool    # Local padrão para recebimento
    allows_negative: bool  # Permite estoque negativo (consignação)
```

**Regras de Negócio:**
- Todo tenant DEVE ter pelo menos 1 Location (criada automaticamente)
- Apenas 1 Location pode ser `is_default=True` por tenant
- Hierarquia não pode ser circular
- Transferências geram 2 movimentações (OUT origem + IN destino)

#### 3.2.2 Supplier (Fornecedores)

**Arquivo:** `apps/partners/models.py`

```python
class Supplier(TenantMixin):
    """
    Cadastro de fornecedores com validação de CNPJ.
    """
    cnpj: str              # Validado matematicamente
    company_name: str      # Razão Social
    trade_name: str        # Nome Fantasia
    state_registration: str
    payment_terms: str     # "30/60/90 DDL"
    lead_time_days: int    # Prazo médio entrega
    minimum_order: Decimal
```

**Regras de Negócio:**
- CNPJ validado com dígitos verificadores
- CNPJ único por tenant (permite mesmo fornecedor em empresas diferentes)
- Criação automática a partir da NF-e se não existir

#### 3.2.3 SupplierProductMap (Mapeamento de Produtos)

**Arquivo:** `apps/partners/models.py`

```python
class SupplierProductMap(TenantMixin):
    """
    ESSENCIAL para deduplicação de produtos na importação de NF-e.
    Vincula código do fornecedor ao produto interno.
    """
    supplier: FK(Supplier)
    product: FK(Product)
    variant: FK(ProductVariant, null=True)
    supplier_sku: str      # cProd da NF-e
    supplier_ean: str      # cEAN da NF-e
    supplier_name: str     # xProd da NF-e
    last_cost: Decimal
    last_purchase: Date
    total_purchased: int
```

**Regras de Negócio:**
- Unique: (tenant, supplier, supplier_sku)
- Atualizado automaticamente após cada importação
- Usado no Match PRATA do algoritmo de deduplicação

#### 3.2.4 AdjustmentReason (Motivos de Ajuste)

**Arquivo:** `apps/inventory/models_v2.py`

```python
class AdjustmentReason(TenantMixin):
    """
    Tipifica ajustes de estoque para auditoria de perdas.
    """
    code: str           # "FURTO", "AVARIA"
    name: str           # "Furto/Roubo"
    impact_type: str    # LOSS, GAIN, NEUTRAL
    requires_note: bool # Obriga observação
```

**Motivos Padrão (Seed):**

| Código | Nome | Impacto | Exige Nota |
|--------|------|---------|------------|
| FURTO | Furto/Roubo | LOSS | ✅ |
| AVARIA | Avaria/Quebra | LOSS | ✅ |
| VALIDADE | Produto Vencido | LOSS | ❌ |
| CONSUMO | Consumo Interno | LOSS | ❌ |
| ACHADO | Produto Encontrado | GAIN | ❌ |
| DOACAO | Doação Recebida | GAIN | ✅ |
| CORRECAO | Correção Sistema | NEUTRAL | ✅ |
| CONTAGEM | Ajuste Inventário | NEUTRAL | ❌ |

#### 3.2.5 StockMovement (Movimentações - V2)

**Arquivo:** `apps/inventory/models_v2.py`

```python
class StockMovement(TenantMixin):
    """
    Ledger IMUTÁVEL de movimentações de estoque.
    NUNCA editar ou deletar registros.
    """
    # Identificação
    id: UUID (PK)
    location: FK(Location)      # OBRIGATÓRIO
    product: FK(Product)        # Para produtos simples
    variant: FK(ProductVariant) # Para produtos variáveis
    
    # Movimento
    type: str                   # IN, OUT, ADJ, TRF_OUT, TRF_IN
    quantity: int
    balance_after: int
    unit_cost: Decimal
    
    # Rastreabilidade de Lote
    batch_number: str           # Número do lote
    expiry_date: Date           # Data de validade
    manufacturing_date: Date    # Data de fabricação
    
    # Auditoria
    adjustment_reason: FK(AdjustmentReason)  # Obrigatório se ADJ
    user: FK(User)
    reason: str                 # Observação livre
    
    # NF-e
    supplier: FK(Supplier)
    nfe_key: str                # Chave 44 dígitos
    nfe_number: str
    
    # Origem
    source: str                 # MANUAL, CSV, NFE, COUNT, TRANSFER, API
    source_doc: str
    
    # Transferência
    transfer_pair: FK(self)     # Movimentação par
```

**Novos Campos V2:**
- `location` - OBRIGATÓRIO
- `batch_number`, `expiry_date`, `manufacturing_date`
- `adjustment_reason`
- `supplier`, `nfe_key`, `nfe_number`
- `transfer_pair`

#### 3.2.6 PendingAssociation (Associações Pendentes)

**Arquivo:** `apps/inventory/models_v2.py`

```python
class PendingAssociation(TenantMixin):
    """
    Item de NF-e aguardando associação manual.
    NUNCA cria produto automaticamente.
    """
    import_batch: FK(ImportBatch)
    supplier: FK(Supplier)
    
    # Dados do XML
    nfe_key: str
    supplier_sku: str           # cProd
    supplier_ean: str           # cEAN
    supplier_name: str          # xProd
    ncm: str
    quantity: Decimal
    unit_cost: Decimal
    
    # Resolução
    status: str                 # PENDING, LINKED, CREATED, IGNORED
    resolved_product: FK(Product)
    match_suggestions: JSONField  # Lista de produtos similares
```

---

## 4. Service Layer

### 4.1 StockService

**Arquivo:** `apps/inventory/services.py`

#### Exceções Customizadas

```python
class StockError(Exception): pass
class InsufficientStockError(StockError): pass
class ExpiredBatchError(StockError): pass
class InvalidMovementError(StockError): pass
class LocationRequiredError(StockError): pass
class AdjustmentReasonRequiredError(StockError): pass
```

#### Método Principal: `create_movement()`

```python
@staticmethod
@transaction.atomic
def create_movement(
    tenant: Tenant,
    user: User,
    movement_type: Literal['IN', 'OUT', 'ADJ'],
    quantity: int,
    location: Location,                    # ← OBRIGATÓRIO
    product: Optional[Product] = None,
    variant: Optional[ProductVariant] = None,
    unit_cost: Optional[Decimal] = None,
    batch_number: Optional[str] = None,
    expiry_date: Optional[date] = None,
    adjustment_reason: Optional[AdjustmentReason] = None,  # ← OBRIGATÓRIO se ADJ
    supplier: Optional[Supplier] = None,
    nfe_key: Optional[str] = None,
    validate_expiry: bool = True,
    allow_negative: bool = False,
) -> MovementResult:
```

**Validações:**
1. `location` é OBRIGATÓRIO
2. `adjustment_reason` é OBRIGATÓRIO se `movement_type == 'ADJ'`
3. Estoque não pode ficar negativo (exceto se `allow_negative=True` ou `location.allows_negative=True`)
4. Lote vencido não pode sair (exceto se `validate_expiry=False`)
5. Produto VARIABLE não pode receber movimentação direta (deve especificar variante)

**Cálculo de Custo Médio:**
```python
# Custo Médio Ponderado
total_current_value = previous_stock * previous_cost
total_new_value = quantity * unit_cost
new_avg_cost = (total_current_value + total_new_value) / new_stock
```

#### Método: `transfer_between_locations()`

```python
@staticmethod
@transaction.atomic
def transfer_between_locations(
    tenant: Tenant,
    user: User,
    product: Product,
    from_location: Location,
    to_location: Location,
    quantity: int,
    variant: Optional[ProductVariant] = None,
) -> TransferResult:
```

**Gera 2 movimentações:**
1. `TRF_OUT` no `from_location`
2. `TRF_IN` no `to_location`
3. Ambas vinculadas via `transfer_pair`

### 4.2 StockQueryService

```python
class StockQueryService:
    @staticmethod
    def get_expiring_batches(tenant, days_ahead=30, location=None) -> List[ExpiringBatch]
    
    @staticmethod
    def get_stock_by_location(tenant, product=None, variant=None) -> Dict[Location, int]
    
    @staticmethod
    def get_movement_history(tenant, product, start_date, end_date, limit=100) -> List[StockMovement]
    
    @staticmethod
    def get_stock_valuation(tenant) -> Dict[str, Any]
```

---

## 5. Motor de Importação Inteligente

### 5.1 Arquitetura

**Arquivo:** `apps/partners/services.py`

```
┌─────────────────────────────────────────────────────────────────┐
│                    FLUXO DE IMPORTAÇÃO NF-e                     │
└─────────────────────────────────────────────────────────────────┘

     ┌───────────┐
     │  Upload   │
     │   XML     │
     └─────┬─────┘
           │
           ▼
     ┌───────────┐
     │ NfeParser │──────▶ Extrai: CNPJ, Itens, Valores
     └─────┬─────┘
           │
           ▼
     ┌───────────┐     ┌──────────────┐
     │  Busca/   │────▶│   Supplier   │
     │  Cria     │     │ (auto-create)│
     │Fornecedor │     └──────────────┘
     └─────┬─────┘
           │
           ▼
  ┌────────────────────────────────────┐
  │     PARA CADA ITEM DA NOTA         │
  │                                    │
  │  ┌─────────────────────────────┐   │
  │  │      ProductMatcher         │   │
  │  │                             │   │
  │  │  🥇 OURO: EAN Match         │   │
  │  │         (100% confiança)    │   │
  │  │            │                │   │
  │  │           NÃO               │   │
  │  │            ▼                │   │
  │  │  🥈 PRATA: SupplierMap      │   │
  │  │         (95% confiança)     │   │
  │  │            │                │   │
  │  │           NÃO               │   │
  │  │            ▼                │   │
  │  │  🥉 BRONZE: SKU Match       │   │
  │  │         (70% confiança)     │   │
  │  │            │                │   │
  │  │           NÃO               │   │
  │  │            ▼                │   │
  │  │  ⚠️ FALLBACK: Pending      │   │
  │  │         (usuário decide)    │   │
  │  └─────────────────────────────┘   │
  └────────────────────────────────────┘
           │
           ▼
     ┌───────────┐
     │ Resultado │
     │ • matched │
     │ • pending │
     │ • errors  │
     └───────────┘
```

### 5.2 Algoritmo de Deduplicação

```python
class ProductMatcher:
    def match(self, item: NfeItem) -> MatchResult:
        # 🥇 OURO - EAN Global (100% confiança)
        if item.has_valid_ean:
            result = self._match_by_ean(item)
            if result.is_matched:
                return result
        
        # 🥈 PRATA - SupplierProductMap (95% confiança)
        result = self._match_by_supplier_map(item)
        if result.is_matched:
            return result
        
        # 🥉 BRONZE - SKU Interno (70% confiança)
        result = self._match_by_sku(item)
        if result.is_matched:
            return result
        
        # ⚠️ FALLBACK - Sem match
        return self._create_pending_result(item)
```

**Níveis de Match:**

| Nível | Método | Confiança | Critério |
|-------|--------|-----------|----------|
| 🥇 OURO | `_match_by_ean` | 100% | `Product.barcode == item.cEAN` |
| 🥈 PRATA | `_match_by_supplier_map` | 95% | `SupplierProductMap` existente |
| 🥉 BRONZE | `_match_by_sku` | 70% | `Product.sku == item.cProd` |
| ⚠️ NONE | `_create_pending_result` | 0% | Cria `PendingAssociation` |

### 5.3 Resolução de Pendências

```python
# Vincular a produto existente
pending.resolve_with_existing(
    product=product,
    variant=variant,
    user=request.user,
    create_mapping=True  # Cria SupplierProductMap para futuras importações
)

# Criar novo produto
pending.resolve_with_new_product(
    product=new_product,
    user=request.user
)

# Ignorar item
pending.ignore(user=request.user)
```

### 5.4 NfeParser

```python
class NfeParser:
    """Parser de XML NF-e versão 4.00"""
    
    def parse(self) -> NfeData:
        """
        Extrai dados estruturados do XML:
        - nfe_key, nfe_number
        - supplier_cnpj, supplier_name
        - items: List[NfeItem]
        """
```

**Estrutura do XML:**
```xml
<nfeProc>
  <NFe>
    <infNFe Id="NFe35260155782486000159550010000979641238309566">
      <ide>
        <nNF>97964</nNF>
      </ide>
      <emit>
        <CNPJ>55782486000159</CNPJ>
        <xNome>FORNECEDOR LTDA</xNome>
      </emit>
      <det nItem="1">
        <prod>
          <cProd>ABC123</cProd>
          <cEAN>7893791143468</cEAN>
          <xProd>PRODUTO TESTE</xProd>
          <qCom>10</qCom>
          <vUnCom>15.50</vUnCom>
        </prod>
      </det>
    </infNFe>
  </NFe>
</nfeProc>
```

---

## 6. Plano de Implementação

### 6.1 Fases

```
┌─────────────────────────────────────────────────────────────────┐
│                    CRONOGRAMA DE IMPLEMENTAÇÃO                  │
└─────────────────────────────────────────────────────────────────┘

FASE 1: FUNDAÇÃO (Semana 1-2) ✅ CONCLUÍDO
├── [✅] Criar app partners
├── [✅] Implementar Supplier, SupplierProductMap
├── [✅] Implementar Location, AdjustmentReason
├── [✅] Atualizar StockMovement (novos campos)
├── [✅] Implementar StockService V2
└── [✅] Testes unitários

FASE 2: IMPORTAÇÃO INTELIGENTE (Semana 3-4) ✅ CONCLUÍDO
├── [✅] Implementar NfeParser
├── [✅] Implementar ProductMatcher
├── [✅] Implementar NfeImportService
├── [✅] Implementar PendingAssociation
├── [✅] Testes de integração
└── [✅] Documentação

FASE 3: INTEGRAÇÃO (Semana 5-6) 🔄 EM ANDAMENTO
├── [ ] Criar migrações consolidadas
├── [ ] Management command para seed
├── [ ] Atualizar views existentes
├── [ ] UI para resolução de pendências
└── [ ] Deploy em staging

FASE 4: POLIMENTO (Semana 7-8)
├── [ ] Dashboard de estoque por localização
├── [ ] Relatório de lotes vencendo
├── [ ] Otimização de queries
├── [ ] Testes de carga
└── [ ] Deploy em produção
```

### 6.2 Arquivos Criados/Modificados

| Arquivo | Status | Descrição |
|---------|--------|-----------|
| `apps/partners/__init__.py` | ✅ Criado | Inicialização do app |
| `apps/partners/apps.py` | ✅ Criado | Configuração do app |
| `apps/partners/models.py` | ✅ Criado | Supplier, SupplierProductMap |
| `apps/partners/services.py` | ✅ Criado | NfeImportService |
| `apps/partners/admin.py` | ✅ Criado | Admin config |
| `apps/inventory/models_v2.py` | ✅ Criado | Location, AdjustmentReason, etc. |
| `apps/inventory/services.py` | ✅ Criado | StockService V2 |
| `apps/inventory/tests_v2.py` | ✅ Criado | Testes unitários |

---

## 7. Guia de Migração

### 7.1 Pré-requisitos

```bash
# 1. Backup do banco de dados
./backup.sh

# 2. Verificar versão do Django
python -c "import django; print(django.VERSION)"
# Deve ser >= 5.2
```

### 7.2 Passos de Migração

```bash
# 1. Adicionar apps ao INSTALLED_APPS
# stock_control/settings.py
INSTALLED_APPS = [
    ...
    'apps.partners',  # NOVO
]

# 2. Gerar migrações
python manage.py makemigrations partners
python manage.py makemigrations inventory

# 3. Aplicar migrações
python manage.py migrate

# 4. Seed de dados iniciais
python manage.py seed_v2
```

### 7.3 Retrocompatibilidade

```python
# Movimentações existentes recebem Location padrão
from apps.inventory.models_v2 import Location, StockMovement

for tenant in Tenant.objects.all():
    # Garante Location padrão
    location = Location.ensure_default_exists(tenant)
    
    # Atualiza movimentações sem location
    StockMovement.objects.filter(
        tenant=tenant,
        location__isnull=True
    ).update(location=location)
```

---

## 8. Testes e Validação

### 8.1 Executar Testes

```bash
# Todos os testes V2
python manage.py test apps.inventory.tests_v2 apps.partners.tests -v 2

# Testes específicos
python manage.py test apps.inventory.tests_v2.StockServiceTests -v 2
python manage.py test apps.inventory.tests_v2.NfeImportServiceTests -v 2
```

### 8.2 Cenários de Teste

#### StockService

| Teste | Descrição | Esperado |
|-------|-----------|----------|
| `test_create_movement_in` | Entrada de estoque | stock += quantity |
| `test_create_movement_out` | Saída de estoque | stock -= quantity |
| `test_prevent_negative_stock` | Evitar negativo | Raise InsufficientStockError |
| `test_location_required` | Location obrigatório | Raise LocationRequiredError |
| `test_adjustment_requires_reason` | ADJ exige motivo | Raise AdjustmentReasonRequiredError |
| `test_weighted_average_cost` | Custo médio | Cálculo correto |
| `test_transfer_between_locations` | Transferência | 2 movimentações |

#### NfeImportService

| Teste | Descrição | Esperado |
|-------|-----------|----------|
| `test_parse_nfe_xml` | Parse do XML | Dados extraídos |
| `test_match_by_ean_gold` | Match por EAN | MatchLevel.GOLD |
| `test_match_by_supplier_map_silver` | Match por mapa | MatchLevel.SILVER |
| `test_pending_association_fallback` | Sem match | PendingAssociation criada |
| `test_never_create_duplicate` | Deduplicação | Nunca cria produto |
| `test_import_creates_supplier` | Auto-criar fornecedor | Supplier criado |
| `test_idempotent_import` | Idempotência | Impede reimportação |

### 8.3 Cobertura Esperada

| Módulo | Cobertura Mínima |
|--------|------------------|
| `partners/models.py` | 90% |
| `partners/services.py` | 95% |
| `inventory/services.py` | 95% |
| `inventory/models_v2.py` | 90% |

---

## 9. Checklist de Deploy

### 9.1 Pré-Deploy

- [ ] Backup do banco de dados
- [ ] Testes passando em staging
- [ ] Migrações testadas
- [ ] Documentação atualizada
- [ ] Code review aprovado

### 9.2 Deploy

```bash
# 1. Build nova imagem
docker build -t stockpro:v2 .

# 2. Push para registry
docker push registry.example.com/stockpro:v2

# 3. Atualizar stack
docker stack deploy -c docker-stack.yml stockpro

# 4. Executar migrações
docker exec -it $(docker ps -qf name=stockpro_app) python manage.py migrate

# 5. Seed dados
docker exec -it $(docker ps -qf name=stockpro_app) python manage.py seed_v2
```

### 9.3 Pós-Deploy

- [ ] Verificar health check
- [ ] Testar importação de NF-e
- [ ] Verificar dashboard
- [ ] Monitorar logs de erro
- [ ] Comunicar equipe

---

## Anexos

### A. Glossário

| Termo | Definição |
|-------|-----------|
| **cProd** | Código do produto no fornecedor (NF-e) |
| **cEAN** | Código de barras EAN-13/GTIN |
| **xProd** | Descrição do produto na NF-e |
| **NCM** | Nomenclatura Comum do Mercosul |
| **CFOP** | Código Fiscal de Operações |
| **Tenant** | Empresa/organização no sistema |
| **Match** | Correspondência entre item da nota e produto |
| **Ledger** | Livro-razão imutável de movimentações |

### B. Referências

- [Django 5.2 Documentation](https://docs.djangoproject.com/en/5.2/)
- [HTMX Documentation](https://htmx.org/docs/)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [Manual NF-e v4.00](http://www.nfe.fazenda.gov.br/)

---

**Documento atualizado em:** Janeiro 2026  
**Versão:** 2.0.0  
**Próxima revisão:** Fevereiro 2026
