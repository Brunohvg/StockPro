# 📦 StockPro V2 - Documentação de Melhorias Estruturais

**Versão:** 2.0.0  
**Data:** Janeiro 2026  
**Autor:** Arquitetura de Software  
**Status:** Plano de Implementação Aprovado

---

## 📋 Índice

1. [Visão Geral](#1-visão-geral)
2. [Arquitetura Proposta](#2-arquitetura-proposta)
3. [Modelo de Dados](#3-modelo-de-dados)
4. [Service Layer](#4-service-layer)
5. [Motor de Importação Inteligente](#5-motor-de-importação-inteligente)
6. [Plano de Implementação](#6-plano-de-implementação)
7. [Guia de Migração](#7-guia-de-migração)
8. [Testes e Validação](#8-testes-e-validação)

---

## 1. Visão Geral

### 1.1 Objetivo

Transformar o StockPro em uma solução robusta para **Varejo Físico**, capaz de substituir sistemas legados, com foco em:

- **Rastreabilidade**: Controle por lote, validade e localização
- **Prevenção de Perdas**: Auditoria completa com motivos de ajuste
- **Importação Fiscal Inteligente**: Deduplicação automática de NF-e
- **Multi-Localização**: Estoque segregado por local físico

### 1.2 Princípios de Design

| Princípio | Descrição |
|-----------|-----------|
| **Imutabilidade** | Movimentações são registros permanentes (ledger) |
| **Rastreabilidade** | Todo item pode ser rastreado até sua origem |
| **Segregação** | Dados isolados por tenant E por localização |
| **Deduplicação** | Nunca criar produtos duplicados automaticamente |
| **Type Safety** | Type hints em todo o código Python |

### 1.3 Escopo da V2

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
│  • Pedidos de Compra            • Precificação              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Arquitetura Proposta

### 2.1 Estrutura de Apps

```
apps/
├── accounts/          # Autenticação (sem alterações)
├── tenants/           # Multi-tenancy (sem alterações)
├── products/          # Catálogo de produtos
│   └── models.py      # + campo supplier_products (relacionamento)
├── inventory/         # Estoque e movimentações
│   ├── models.py      # + Location, AdjustmentReason, campos de lote
│   ├── services.py    # StockService refatorado (NOVO ARQUIVO)
│   └── tasks.py       # Celery tasks atualizadas
├── partners/          # NOVO APP - Fornecedores
│   ├── models.py      # Supplier, SupplierProductMap
│   ├── services.py    # NfeImportService
│   └── admin.py       # Painel administrativo
├── reports/           # Dashboard e relatórios
└── core/              # Utilitários compartilhados
    └── services.py    # Deprecado → movido para inventory/services.py
```

### 2.2 Diagrama de Dependências

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   tenants    │────▶│   accounts   │     │    core      │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   products   │◀────│  inventory   │────▶│   partners   │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   reports    │
                     └──────────────┘
```

---

## 3. Modelo de Dados

### 3.1 Novos Modelos

#### 3.1.1 Location (Multi-Localização)

```python
class Location(TenantMixin):
    """
    Representa um local físico de armazenamento.
    Exemplos: Loja Principal, Depósito, Prateleira A, Gôndola 1
    """
    LOCATION_TYPES = [
        ('STORE', 'Loja'),
        ('WAREHOUSE', 'Depósito'),
        ('SHELF', 'Prateleira'),
        ('DISPLAY', 'Expositor'),
        ('TRANSIT', 'Em Trânsito'),
    ]
    
    code: str           # Código único (ex: "LOJ-001")
    name: str           # Nome legível (ex: "Loja Centro")
    location_type: str  # Tipo do local
    parent: FK(self)    # Hierarquia (Depósito > Corredor > Prateleira)
    address: str        # Endereço (opcional)
    is_active: bool     # Ativo/Inativo
    is_default: bool    # Local padrão para novos produtos
```

**Regras de Negócio:**
- Todo tenant deve ter pelo menos 1 Location (criada automaticamente)
- Um Location pode ter filhos (hierarquia)
- Estoque é segregado por Location
- Transferências entre Locations geram 2 movimentações (OUT + IN)

#### 3.1.2 Supplier (Fornecedores)

```python
class Supplier(TenantMixin):
    """
    Cadastro de fornecedores.
    CNPJ é usado para match automático em importação de NF-e.
    """
    cnpj: str              # CNPJ formatado (único por tenant)
    company_name: str      # Razão Social
    trade_name: str        # Nome Fantasia
    state_registration: str # IE
    email: str
    phone: str
    contact_name: str      # Nome do contato
    
    # Condições Comerciais
    payment_terms: str     # Ex: "30/60/90 DDL"
    lead_time_days: int    # Prazo médio de entrega
    minimum_order: Decimal # Pedido mínimo
    
    # Endereço
    address: str
    city: str
    state: str
    zip_code: str
    
    notes: TextField
    is_active: bool
```

**Regras de Negócio:**
- CNPJ único por tenant (permite mesmo fornecedor em empresas diferentes)
- Ao importar NF-e, busca fornecedor pelo CNPJ do emitente
- Se não existir, cria automaticamente com dados da nota

#### 3.1.3 SupplierProductMap (Mapeamento de Produtos)

```python
class SupplierProductMap(TenantMixin):
    """
    Vincula o código do produto no fornecedor (cProd da NF-e)
    ao Product interno, evitando duplicidade.
    """
    supplier: FK(Supplier)
    product: FK(Product)
    variant: FK(ProductVariant, null=True)
    
    supplier_sku: str      # cProd da NF-e
    supplier_ean: str      # cEAN da NF-e (pode diferir do nosso)
    supplier_name: str     # xProd da NF-e (descrição original)
    
    last_cost: Decimal     # Último custo praticado
    last_purchase: Date    # Data da última compra
    
    class Meta:
        unique_together = ['tenant', 'supplier', 'supplier_sku']
```

**Regras de Negócio:**
- Permite que o mesmo fornecedor use códigos diferentes para o mesmo produto
- Guarda histórico de custo e última compra
- Usado na deduplicação de importação de NF-e

#### 3.1.4 AdjustmentReason (Motivos de Ajuste)

```python
class AdjustmentReason(TenantMixin):
    """
    Tipifica os motivos de ajuste de estoque para auditoria.
    """
    IMPACT_TYPES = [
        ('LOSS', 'Perda'),      # Reduz estoque (furto, avaria)
        ('GAIN', 'Ganho'),      # Aumenta estoque (achado, doação)
        ('NEUTRAL', 'Neutro'),  # Correção sem impacto fiscal
    ]
    
    code: str           # Código único (ex: "FURTO", "AVARIA")
    name: str           # Nome legível
    description: str    # Descrição detalhada
    impact_type: str    # Tipo de impacto
    requires_note: bool # Obriga preenchimento de observação
    is_active: bool
```

**Motivos Padrão (seed):**
- `FURTO` - Furto/Roubo (LOSS)
- `AVARIA` - Avaria/Quebra (LOSS)
- `VALIDADE` - Vencimento (LOSS)
- `CONSUMO` - Consumo Interno (LOSS)
- `ACHADO` - Produto Encontrado (GAIN)
- `DOACAO` - Recebimento de Doação (GAIN)
- `CORRECAO` - Correção de Inventário (NEUTRAL)
- `CONTAGEM` - Ajuste de Contagem Física (NEUTRAL)

### 3.2 Alterações em Modelos Existentes

#### 3.2.1 StockMovement (Novos Campos)

```python
class StockMovement(TenantMixin):
    # Campos existentes...
    
    # NOVOS CAMPOS
    location: FK(Location)              # Local da movimentação (OBRIGATÓRIO)
    
    # Rastreabilidade de Lote
    batch_number: str                   # Número do lote (opcional)
    expiry_date: Date                   # Data de validade (opcional)
    manufacturing_date: Date            # Data de fabricação (opcional)
    
    # Auditoria de Ajustes
    adjustment_reason: FK(AdjustmentReason)  # Motivo (obrigatório se type=ADJ)
    
    # Vínculo com Fornecedor (para entradas de NF-e)
    supplier: FK(Supplier, null=True)   # Fornecedor da entrada
    nfe_key: str                        # Chave da NF-e (44 dígitos)
    nfe_number: str                     # Número da NF-e
```

#### 3.2.2 Product (Novos Campos)

```python
class Product(TenantMixin):
    # Campos existentes...
    
    # NOVOS CAMPOS
    default_location: FK(Location)      # Local padrão para recebimento
    track_batch: bool                   # Controla lote/validade?
    shelf_life_days: int                # Prazo de validade padrão (dias)
```

### 3.3 Diagrama ER Completo

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│     Tenant      │───────│    Location     │───────│  StockMovement  │
└─────────────────┘       └─────────────────┘       └─────────────────┘
         │                        │                         │
         │                        │                         │
         ▼                        ▼                         ▼
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│    Supplier     │───────│SupplierProduct  │───────│    Product      │
└─────────────────┘       │      Map        │       └─────────────────┘
                          └─────────────────┘               │
                                                            │
                                                            ▼
                          ┌─────────────────┐       ┌─────────────────┐
                          │AdjustmentReason │       │ ProductVariant  │
                          └─────────────────┘       └─────────────────┘
```

---

## 4. Service Layer

### 4.1 StockService Refatorado

```python
class StockService:
    """
    Serviço central para todas as operações de estoque.
    Garante atomicidade, rastreabilidade e auditoria.
    """
    
    @staticmethod
    @transaction.atomic
    def create_movement(
        tenant: Tenant,
        user: User,
        movement_type: Literal['IN', 'OUT', 'ADJ'],
        quantity: int,
        location: Location,                    # OBRIGATÓRIO
        product: Optional[Product] = None,
        variant: Optional[ProductVariant] = None,
        reason: str = '',
        unit_cost: Optional[Decimal] = None,
        # Novos parâmetros
        batch_number: Optional[str] = None,
        expiry_date: Optional[date] = None,
        adjustment_reason: Optional[AdjustmentReason] = None,
        supplier: Optional[Supplier] = None,
        nfe_key: Optional[str] = None,
    ) -> StockMovement:
        """
        Cria uma movimentação de estoque.
        
        Validações:
        - Location é obrigatório
        - ADJ requer adjustment_reason
        - OUT não pode deixar estoque negativo
        - Lote vencido não pode sair (configurável)
        """
        pass
    
    @staticmethod
    def transfer_between_locations(
        tenant: Tenant,
        user: User,
        product: Product,
        variant: Optional[ProductVariant],
        quantity: int,
        from_location: Location,
        to_location: Location,
        reason: str = 'Transferência entre locais',
    ) -> Tuple[StockMovement, StockMovement]:
        """
        Transfere estoque entre locais.
        Gera 2 movimentações: OUT do origem + IN no destino.
        """
        pass
    
    @staticmethod
    def get_stock_by_location(
        tenant: Tenant,
        product: Product,
        variant: Optional[ProductVariant] = None,
    ) -> Dict[Location, int]:
        """
        Retorna estoque segregado por localização.
        """
        pass
    
    @staticmethod
    def get_expiring_batches(
        tenant: Tenant,
        days_ahead: int = 30,
    ) -> QuerySet:
        """
        Retorna lotes próximos do vencimento.
        """
        pass
```

### 4.2 NfeImportService

```python
class NfeImportService:
    """
    Serviço de importação inteligente de NF-e.
    Implementa lógica de deduplicação em 4 níveis.
    """
    
    def __init__(self, tenant: Tenant, user: User, location: Location):
        self.tenant = tenant
        self.user = user
        self.location = location
    
    def import_nfe(self, xml_content: bytes) -> ImportResult:
        """
        Importa uma NF-e completa.
        
        Fluxo:
        1. Parse do XML
        2. Busca/Cria Fornecedor pelo CNPJ
        3. Para cada item:
           a. Tenta match (Ouro → Prata → Bronze)
           b. Se match: cria movimentação
           c. Se não: marca como PENDING_ASSOCIATION
        4. Retorna resultado com estatísticas
        """
        pass
    
    def match_product(self, item: NfeItem) -> MatchResult:
        """
        Algoritmo de deduplicação em 4 níveis:
        
        🥇 OURO - Match por EAN Global:
           - Busca Product/Variant onde barcode == item.cEAN
           - Se encontrar, confiança 100%
        
        🥈 PRATA - Match por SupplierProductMap:
           - Busca mapeamento onde supplier == fornecedor E supplier_sku == item.cProd
           - Se encontrar, confiança 95%
        
        🥉 BRONZE - Match por SKU Interno:
           - Busca Product onde sku == item.cProd (código do fornecedor = nosso SKU)
           - Se encontrar, confiança 70%
        
        ⚠️ FALLBACK - Associação Pendente:
           - Cria PendingAssociation para usuário decidir
           - NUNCA cria produto automaticamente
        """
        pass
    
    def create_pending_association(self, item: NfeItem, supplier: Supplier) -> PendingAssociation:
        """
        Marca item para associação manual.
        Usuário pode: criar novo produto OU vincular a existente.
        """
        pass
```

---

## 5. Motor de Importação Inteligente

### 5.1 Fluxo de Importação de NF-e

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
     │  Parse    │──────▶ Extrai: CNPJ, Itens, Valores
     │   XML     │
     └─────┬─────┘
           │
           ▼
     ┌───────────┐     ┌──────────────┐
     │  Busca    │────▶│   Supplier   │
     │Fornecedor │     │ (cria se não │
     │ por CNPJ  │     │   existir)   │
     └─────┬─────┘     └──────────────┘
           │
           ▼
  ┌────────────────────────────────────┐
  │     PARA CADA ITEM DA NOTA         │
  └────────────────────────────────────┘
           │
           ▼
     ┌───────────┐     ┌──────────────┐
     │  Match    │────▶│ 🥇 EAN?     │───▶ SIM ───▶ MATCHED
     │  OURO     │     └──────────────┘
     └─────┬─────┘            │
           │                 NÃO
           ▼                  │
     ┌───────────┐     ┌──────────────┐
     │  Match    │────▶│ 🥈 Supplier  │───▶ SIM ───▶ MATCHED
     │  PRATA    │     │    Map?      │
     └─────┬─────┘     └──────────────┘
           │                  │
           │                 NÃO
           ▼                  │
     ┌───────────┐     ┌──────────────┐
     │  Match    │────▶│ 🥉 SKU      │───▶ SIM ───▶ MATCHED
     │  BRONZE   │     │   Interno?   │
     └─────┬─────┘     └──────────────┘
           │                  │
           │                 NÃO
           ▼                  │
     ┌───────────┐            │
     │ PENDING   │◀───────────┘
     │ASSOCIATION│
     └─────┬─────┘
           │
           ▼
     ┌───────────┐
     │  Usuário  │───▶ Criar Novo OU Vincular Existente
     │  Decide   │
     └───────────┘
```

### 5.2 Modelo de Associação Pendente

```python
class PendingAssociation(TenantMixin):
    """
    Item de NF-e aguardando associação manual.
    """
    STATUS_CHOICES = [
        ('PENDING', 'Aguardando'),
        ('LINKED', 'Vinculado'),
        ('CREATED', 'Produto Criado'),
        ('IGNORED', 'Ignorado'),
    ]
    
    import_batch: FK(ImportBatch)
    supplier: FK(Supplier)
    
    # Dados do XML
    nfe_key: str
    nfe_number: str
    item_number: int        # nItem do XML
    supplier_sku: str       # cProd
    supplier_ean: str       # cEAN
    supplier_name: str      # xProd
    ncm: str
    cfop: str
    unit: str               # uCom
    quantity: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    
    # Resolução
    status: str
    resolved_product: FK(Product, null=True)
    resolved_variant: FK(ProductVariant, null=True)
    resolved_by: FK(User, null=True)
    resolved_at: DateTime
    
    # Match info
    match_suggestions: JSONField  # Produtos similares encontrados
```

### 5.3 Interface de Resolução

A UI deve mostrar:
1. Lista de itens pendentes agrupados por NF-e
2. Para cada item:
   - Dados originais da nota (cProd, xProd, EAN, quantidade, custo)
   - Sugestões de match por similaridade
   - Opções: "Vincular a existente" ou "Criar novo produto"
3. Ao vincular: atualiza SupplierProductMap para futuras importações

---

## 6. Plano de Implementação

### 6.1 Fases de Desenvolvimento

```
┌─────────────────────────────────────────────────────────────────┐
│                    CRONOGRAMA DE IMPLEMENTAÇÃO                  │
└─────────────────────────────────────────────────────────────────┘

SEMANA 1-2: FUNDAÇÃO
├── [x] Criar app partners
├── [x] Implementar models: Location, Supplier, SupplierProductMap
├── [x] Implementar AdjustmentReason
├── [x] Migrar StockMovement (novos campos)
├── [x] Seed de dados iniciais
└── [x] Testes unitários de models

SEMANA 3-4: SERVICE LAYER
├── [x] Refatorar StockService
├── [x] Implementar validações de Location
├── [x] Implementar validações de Lote/Validade
├── [x] Implementar transferência entre locais
├── [x] Testes unitários de services
└── [x] Atualizar views existentes

SEMANA 5-6: IMPORTAÇÃO INTELIGENTE
├── [x] Implementar NfeImportService
├── [x] Implementar algoritmo de deduplicação
├── [x] Implementar PendingAssociation
├── [x] Criar UI de resolução de pendências
├── [x] Testes de integração
└── [x] Documentação

SEMANA 7-8: POLIMENTO
├── [ ] Dashboard de estoque por localização
├── [ ] Relatório de lotes vencendo
├── [ ] Otimização de queries
├── [ ] Testes de carga
└── [ ] Deploy em staging
```

### 6.2 Priorização (MoSCoW)

| Feature | Prioridade | Justificativa |
|---------|------------|---------------|
| Location | **MUST** | Base para segregação de estoque |
| Supplier | **MUST** | Base para importação de NF-e |
| SupplierProductMap | **MUST** | Deduplicação de produtos |
| AdjustmentReason | **MUST** | Auditoria de perdas |
| Batch/Validade | **SHOULD** | Importante para perecíveis |
| NfeImportService | **MUST** | Funcionalidade core |
| PendingAssociation | **MUST** | Fluxo de resolução |
| Transfer UI | **SHOULD** | UX de transferência |
| Relatório Vencimentos | **COULD** | Nice to have |

---

## 7. Guia de Migração

### 7.1 Migrações de Banco de Dados

```python
# Ordem de execução:
1. partners/migrations/0001_initial.py      # Supplier, SupplierProductMap
2. inventory/migrations/0002_location.py    # Location
3. inventory/migrations/0003_adjustment.py  # AdjustmentReason
4. inventory/migrations/0004_movement.py    # Novos campos em StockMovement
5. products/migrations/0002_tracking.py     # Novos campos em Product

# Comando:
python manage.py migrate
python manage.py seed_v2  # Seed de dados iniciais
```

### 7.2 Dados de Seed

```python
# Location padrão por tenant
Location.objects.get_or_create(
    tenant=tenant,
    code='PRINCIPAL',
    defaults={
        'name': 'Localização Principal',
        'location_type': 'STORE',
        'is_default': True,
    }
)

# AdjustmentReasons padrão
DEFAULT_REASONS = [
    ('FURTO', 'Furto/Roubo', 'LOSS'),
    ('AVARIA', 'Avaria/Quebra', 'LOSS'),
    ('VALIDADE', 'Produto Vencido', 'LOSS'),
    ('CONSUMO', 'Consumo Interno', 'LOSS'),
    ('ACHADO', 'Produto Encontrado', 'GAIN'),
    ('DOACAO', 'Doação Recebida', 'GAIN'),
    ('CORRECAO', 'Correção de Sistema', 'NEUTRAL'),
    ('CONTAGEM', 'Ajuste de Inventário', 'NEUTRAL'),
]
```

### 7.3 Retrocompatibilidade

```python
# Movimentações existentes recebem Location padrão
StockMovement.objects.filter(location__isnull=True).update(
    location=F('tenant__locations__is_default')
)

# Produtos existentes recebem default_location
Product.objects.filter(default_location__isnull=True).update(
    default_location=F('tenant__locations__is_default')
)
```

---

## 8. Testes e Validação

### 8.1 Cenários de Teste

#### Importação de NF-e

```python
class TestNfeImport(TestCase):
    """Testes de importação de NF-e"""
    
    def test_match_by_ean_gold(self):
        """Deve encontrar produto pelo EAN (match ouro)"""
        pass
    
    def test_match_by_supplier_map_silver(self):
        """Deve encontrar produto pelo mapeamento (match prata)"""
        pass
    
    def test_match_by_sku_bronze(self):
        """Deve encontrar produto pelo SKU (match bronze)"""
        pass
    
    def test_pending_association_fallback(self):
        """Deve criar pendência quando não encontrar match"""
        pass
    
    def test_never_create_duplicate(self):
        """Nunca deve criar produto duplicado automaticamente"""
        pass
    
    def test_supplier_auto_create(self):
        """Deve criar fornecedor se não existir"""
        pass
    
    def test_supplier_product_map_update(self):
        """Deve atualizar mapeamento após vincular"""
        pass
```

#### Movimentações

```python
class TestStockMovement(TestCase):
    """Testes de movimentação de estoque"""
    
    def test_location_required(self):
        """Deve exigir localização"""
        pass
    
    def test_adjustment_reason_required(self):
        """Deve exigir motivo para ajustes"""
        pass
    
    def test_prevent_negative_stock(self):
        """Deve impedir estoque negativo"""
        pass
    
    def test_expired_batch_warning(self):
        """Deve alertar sobre lote vencido"""
        pass
    
    def test_weighted_average_cost(self):
        """Deve calcular custo médio ponderado"""
        pass
```

### 8.2 Cobertura Esperada

| Módulo | Cobertura Mínima |
|--------|------------------|
| partners/models.py | 90% |
| partners/services.py | 95% |
| inventory/services.py | 95% |
| inventory/models.py | 90% |

---

## Anexos

### A. Estrutura do XML NF-e

```xml
<nfeProc>
  <NFe>
    <infNFe>
      <ide>
        <nNF>12345</nNF>           <!-- Número da nota -->
        <serie>1</serie>
      </ide>
      <emit>
        <CNPJ>12345678000199</CNPJ>  <!-- Fornecedor -->
        <xNome>Razão Social</xNome>
      </emit>
      <det nItem="1">
        <prod>
          <cProd>ABC123</cProd>      <!-- Código do fornecedor -->
          <cEAN>7891234567890</cEAN> <!-- EAN -->
          <xProd>Descrição</xProd>   <!-- Nome -->
          <NCM>12345678</NCM>
          <CFOP>5102</CFOP>
          <uCom>UN</uCom>
          <qCom>10</qCom>            <!-- Quantidade -->
          <vUnCom>15.50</vUnCom>     <!-- Custo unitário -->
        </prod>
      </det>
    </infNFe>
  </NFe>
</nfeProc>
```

### B. Glossário

| Termo | Definição |
|-------|-----------|
| **cProd** | Código do produto no fornecedor |
| **cEAN** | Código de barras EAN-13/GTIN |
| **xProd** | Descrição do produto na NF-e |
| **NCM** | Nomenclatura Comum do Mercosul |
| **CFOP** | Código Fiscal de Operações e Prestações |
| **Tenant** | Empresa/organização no sistema multi-tenant |
| **Match** | Correspondência entre item da nota e produto interno |

---

*Documento gerado em Janeiro 2026 - StockPro V2*
