# 🤖 StockPro System Documentation (AI-Ready) - V2

This document provides a comprehensive overview of the **StockPro V2** system architecture, domain rules, and technical implementation. It is designed to enable any AI agent to understand, maintain, and extend the system with high precision.

---

## 🎯 1. Core Mission & Domain Boundaries

**StockPro** is a dedicated **Physical Inventory Management System** for retail businesses.

### 🚫 Non-Negotiable Rules (Anti-Hallucination)
1. **Physical Focus Only**: Every movement (IN, OUT, ADJ) MUST correspond to a physical change in stock.
2. **No Sales Logic**: Do NOT implement Orders, Customers, Sales, Invoices, or Pricing logic (beyond cost).
3. **No Direct Edits**: Stock levels (`current_stock`) must NEVER be edited directly via Django Admin or shell without creating a corresponding `StockMovement` via the Service Layer.
4. **Immutability**: `StockMovement` records are immutable. No `UPDATE` or `DELETE` allowed.
5. **Location Required**: All movements MUST specify a `Location` (V2).
6. **Never Auto-Create Products**: When importing NF-e, NEVER create duplicate products automatically. Use `PendingAssociation` for manual resolution.

---

## 🏗️ 2. High-Level Architecture

| Component | Technology | Description |
|-----------|------------|-------------|
| **Backend** | Django 5.2 (Modular Monolith) | Core business logic decoupled into independent apps. |
| **Frontend** | Django Templates + HTMX + Tailwind | Server-side rendering with reactive UI pieces. |
| **Multi-tenancy** | Middleware + Session | Multi-company isolation within a single database. |
| **Logic Layer** | Service Layer (`services.py`) | All domain logic resides in dedicated service classes. |
| **Task Queue** | Celery + Redis | Asynchronous processing for heavy imports (CSV/XML). |
| **Infrastructure** | Docker Swarm | Containerized deployment with Traefik as Load Balancer. |

### 📁 App Structure (V2)

```
apps/
├── accounts/          # Authentication & user management
├── tenants/           # Multi-tenancy isolation
├── products/          # Product catalog (SIMPLE/VARIABLE)
├── inventory/         # Stock movements, locations, imports
│   ├── models.py      # Legacy models
│   ├── models_v2.py   # V2: Location, AdjustmentReason, PendingAssociation
│   ├── services.py    # StockService, StockQueryService
│   └── tasks.py       # Celery tasks for imports
├── partners/          # V2: Suppliers & product mapping
│   ├── models.py      # Supplier, SupplierProductMap
│   └── services.py    # NfeImportService
├── reports/           # Dashboard & analytics
└── core/              # Shared utilities
```

---

## 🗄️ 3. Data Model & Relationships (V2)

### 🏢 Multi-tenancy (App: `tenants`, `accounts`)
- **Tenant**: Represents a company/organization. Tracks `plan`, `subscription_status`, and `trial_ends_at`.
- **Plan**: Defines limits (`max_products`, `max_users`).
- **TenantMembership**: Links `User` to `Tenant` with a **Role** (`OWNER`, `ADMIN`, `OPERATOR`).

### 📦 Products & Inventory (App: `products`, `inventory`)
- **Category**: Product grouping with `rotation` classification (A, B, C).
- **Product**:
    - `product_type`: `SIMPLE` (single SKU) or `VARIABLE` (parent of variants).
    - `current_stock`: Denormalized field updated via services.
    - `barcode`: EAN-13/GTIN for deduplication.
- **ProductVariant**: Specific version of a `VARIABLE` product.
- **VariantAttributeValue**: Pivot for dynamic attributes.
- **StockMovement**: The ledger of all changes. Tracks `type`, `quantity`, `balance_after`, `location`, `batch_number`, `expiry_date`.

### 📍 Locations (V2 - App: `inventory`)
- **Location**: Physical storage locations with hierarchy support.
    - Types: `STORE`, `WAREHOUSE`, `SHELF`, `DISPLAY`, `TRANSIT`, `QUARANTINE`
    - `is_default`: Default location for new entries
    - `allows_negative`: For consignment scenarios
    - `parent`: Enables hierarchy (Warehouse > Aisle > Shelf)

### 🏭 Partners (V2 - App: `partners`)
- **Supplier**: Vendor registry with CNPJ-based matching.
    - Auto-created from NF-e if not exists
    - Unique per tenant by CNPJ
- **SupplierProductMap**: Links supplier's product code to internal product.
    - Enables deduplication in future imports
    - Tracks `last_cost`, `last_purchase`, `total_purchased`

### 📋 Audit & Adjustments (V2 - App: `inventory`)
- **AdjustmentReason**: Categorizes stock adjustments.
    - Impact types: `LOSS`, `GAIN`, `NEUTRAL`
    - `requires_note`: Forces observation on adjustment
    - Default reasons: FURTO, AVARIA, VALIDADE, CONSUMO, ACHADO, DOACAO, CORRECAO, CONTAGEM

### 📥 Import System (V2 - App: `inventory`)
- **ImportBatch**: Import job metadata with NF-e support.
    - Status: `PENDING`, `PROCESSING`, `COMPLETED`, `PARTIAL`, `ERROR`, `PENDING_REVIEW`
    - Tracks `nfe_key`, `nfe_number`, `supplier`
- **ImportLog**: Idempotency control per row.
- **PendingAssociation**: Items awaiting manual product linking.
    - Created when no automatic match is found
    - Status: `PENDING`, `LINKED`, `CREATED`, `IGNORED`
    - Includes `match_suggestions` for user guidance

---

## ⚙️ 4. Critical Business Logic

### 🔄 Inventory Engine (`apps/inventory/services.py`)

All stock changes MUST use `StockService.create_movement()`.

```python
result = StockService.create_movement(
    tenant=tenant,
    user=user,
    movement_type='IN',  # IN, OUT, ADJ
    quantity=100,
    location=location,      # REQUIRED in V2
    product=product,
    unit_cost=Decimal('15.50'),
    # V2 fields
    batch_number='LOT-2026-001',
    expiry_date=date(2026, 12, 31),
    supplier=supplier,
    nfe_key='35260155782486...',
)
```

**Validations:**
- `location` is REQUIRED
- `ADJ` movements require `adjustment_reason`
- `OUT` movements cannot cause negative stock (unless `location.allows_negative`)
- Expired batches cannot be moved out (configurable)

**Calculations:**
- **Weighted Average Cost**: `new_avg = (old_qty * old_cost + new_qty * new_cost) / total_qty`
- Applied on every `IN` movement with `unit_cost`

### 🔍 NFe Import Deduplication (`apps/partners/services.py`)

The `NfeImportService` implements a 4-level deduplication algorithm:

```
┌─────────────────────────────────────────────────────────────┐
│                 NFe IMPORT DEDUPLICATION                    │
├─────────────────────────────────────────────────────────────┤
│ 🥇 GOLD   (100%) │ Match by EAN (cEAN → Product.barcode)    │
│ 🥈 SILVER (95%)  │ Match by SupplierProductMap              │
│ 🥉 BRONZE (70%)  │ Match by SKU (cProd → Product.sku)       │
│ ⚠️ FALLBACK     │ Create PendingAssociation (user decides) │
└─────────────────────────────────────────────────────────────┘
```

**CRITICAL**: The system NEVER creates duplicate products automatically. When no match is found, it creates a `PendingAssociation` for manual resolution.

### 🔐 Multi-tenant Security (`apps/tenants/middleware.py`)
- **Isolation**: `TenantMiddleware` injects `request.tenant` and `request.membership`.
- **Status Checks**: Blocks access if tenant is `SUSPENDED` or `CANCELLED`.
- **Trial Guard**: Flags `request.trial_expired` if Trial Period ends.
- **Decorators**:
    - `@trial_allows_read`: Blocks POST/PUT if trial is expired.
    - `@owner_required` / `@admin_required`: Enforce RBAC.

---

## 🚀 5. Workflows & Lifecycle

### 📥 NF-e Import Process (V2)

```
┌──────────────┐
│ Upload XML   │
└──────┬───────┘
       │
       ▼
┌──────────────┐     ┌─────────────────┐
│ Parse XML    │────▶│ Extract: CNPJ,  │
│ (NfeParser)  │     │ Items, Values   │
└──────┬───────┘     └─────────────────┘
       │
       ▼
┌──────────────┐     ┌─────────────────┐
│ Get/Create   │────▶│ Supplier        │
│ Supplier     │     │ (by CNPJ)       │
└──────┬───────┘     └─────────────────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│           FOR EACH ITEM                       │
├──────────────────────────────────────────────┤
│  🥇 EAN match?     → Create StockMovement    │
│  🥈 SupplierMap?   → Create StockMovement    │
│  🥉 SKU match?     → Create StockMovement    │
│  ⚠️ No match?     → Create PendingAssociation│
└──────────────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│ Update Batch │
│ Status       │
└──────────────┘
```

### 🔄 Pending Association Resolution

When user links a pending item to an existing product:
1. `PendingAssociation.resolve_with_existing()` is called
2. `SupplierProductMap` is created for future imports
3. `StockMovement` is created with the quantity/cost from NF-e
4. `ImportBatch.pending_count` is decremented

### 🛡️ Deployment Flow (`deploy.sh`)
- Uses Docker Swarm.
- **Build**: Compresses layers for ARM64 (production) and standard x86.
- **Migrate**: Runs as a one-off task within the Swarm context.
- **Seed**: Run `python manage.py seed_v2` after migrations.

---

## 🛠️ 6. Guidelines for AI Assistants

### General Rules
- **Modifying Models**: Always check if the model inherits from `TenantMixin`. If so, ensure all queries filter by `tenant`.
- **Adding Features**: Ensure logic is placed in `services.py`, not in `views.py` or `models.py`.
- **UI Changes**: Use `HTMX` for partial page updates (look for `hx-` attributes in templates).
- **Static Assets**: Use Tailwind CSS classes. Do not write inline CSS.
- **Environment**: Always reference variables through `decouple.config`.

### V2 Specific Rules
- **Movements**: ALWAYS include `location` parameter.
- **Adjustments**: ALWAYS include `adjustment_reason` for ADJ type.
- **NF-e Import**: NEVER create products automatically. Use `PendingAssociation`.
- **Suppliers**: Use `Supplier.get_or_create_from_nfe()` for auto-creation from NF-e.
- **Product Mapping**: Use `SupplierProductMap.find_mapping()` for lookups.

### Key Services
```python
# Stock operations
from apps.inventory.services import StockService, StockQueryService

# NF-e import
from apps.partners.services import NfeImportService, ProductMatcher

# Examples
StockService.create_movement(...)  # Create stock movement
StockService.transfer_between_locations(...)  # Transfer stock
StockQueryService.get_expiring_batches(...)  # Query expiring items
NfeImportService.import_from_bytes(xml_content)  # Import NF-e
```

### Key Models (V2)
```python
from apps.inventory.models_v2 import (
    Location, LocationType,
    AdjustmentReason, ImpactType,
    StockMovement, MovementType, MovementSource,
    PendingAssociation, PendingAssociationStatus,
)
from apps.partners.models import Supplier, SupplierProductMap
```

---

## 📊 7. Database Schema Overview (V2)

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│     Tenant      │───────│    Location     │───────│  StockMovement  │
└─────────────────┘       └─────────────────┘       └─────────────────┘
         │                        │                         │
         │                        │                         ├── batch_number
         │                        │                         ├── expiry_date
         ▼                        ▼                         └── nfe_key
┌─────────────────┐       ┌─────────────────┐       
│    Supplier     │───────│SupplierProduct  │       ┌─────────────────┐
└─────────────────┘       │      Map        │───────│    Product      │
         │                └─────────────────┘       └─────────────────┘
         │                                                  │
         ▼                                                  │
┌─────────────────┐       ┌─────────────────┐              ▼
│  ImportBatch    │───────│PendingAssociation│      ┌─────────────────┐
└─────────────────┘       └─────────────────┘      │ ProductVariant  │
                                                    └─────────────────┘
```

---

## 🧪 8. Testing

Run the V2 test suite:
```bash
python manage.py test apps.inventory.tests_v2 apps.partners -v 2
```

Key test scenarios:
- `test_match_by_ean_gold` - EAN deduplication
- `test_match_by_supplier_map_silver` - SupplierMap deduplication  
- `test_never_create_duplicate` - Ensure no auto-creation
- `test_location_required` - Location validation
- `test_adjustment_requires_reason` - ADJ validation
- `test_weighted_average_cost` - Cost calculation

---

**Last Updated**: January 2026  
**Version**: 12.0 (V2 - Multi-Location, Suppliers, NF-e Import)
