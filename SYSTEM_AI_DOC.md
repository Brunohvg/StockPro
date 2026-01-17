# 🤖 StockPro System Documentation (AI-Ready) - V15

This document is the technical "brain" of the **StockPro** system. It provides high-precision details about architecture, domain rules, and AI integration to enable any AI agent to maintain or extend the system without hallucinations.

---

## 🎯 1. Core Mission & Domain Boundaries

**StockPro** is a physical-first **Inventory Management System**.

### 🚫 Non-Negotiable Rules
1. **Physical Ledger**: Every change MUST correspond to a physical movement.
2. **Service Layer Only**: Never edit `current_stock` directly. Use `StockService.create_movement()`.
3. **No Sales Logic**: Do NOT implement pricing (beyond cost), invoices, or customer orders.
4. **Immutability**: `StockMovement` records are immutable.
5. **AI Responsibility**: AI features (Insights/Extraction) must have a deterministic fallback (Regular Expressions/Cleaning).

---

## 🏗️ 2. High-Level Architecture

| Layer | Implementation |
|-------|----------------|
| **Core Logic** | Service Layer (`services.py`). Views must only orchestrate services. |
| **Data Isolation** | Multi-tenancy via `TenantMiddleware` and `TenantMixin`. |
| **Variations (V10)** | Normalized architecture: `Product` (Parent) ↔ `ProductVariant` (Child). |
| **AI Layer (V15)** | `AIService` (Grok-2) for unstructured data extraction and BI analytics. |
| **Worker Layer** | Celery + Redis for asynchronous NF-e and CSV large-scale imports. |

---

## 🗄️ 3. Domain Model Highlights

### 📦 Products (App: `products`)
- **ProductType**: `SIMPLE` (independent) or `VARIABLE` (container).
- **Consolidation**: `ConsolidationService` can transform multiple `SIMPLE` products into `VARIANTS` of a new `VARIABLE` parent.
- **Safe Delete**: Property `can_be_safely_deleted` blocks deletion if `OUT` movements exist.

### 📍 Inventory (App: `inventory`)
- **Location**: Physical storage hierarchy. `StockMovement` tracks the source/destination location.
- **Weighted Average**: Calculated only on `IN` movements.
- **Localized Numbers**: Dashboard displays localized BR formatting (`R$ . ,`).

### 🏭 Partners & NF-e (App: `partners`)
- **Supplier**: Autodetected from CNPJ in NF-e.
- **SupplierProductMap**: Critical for deduplication. Links Supplier's code to internal `Product/Variant`.

---

## 🤖 4. AI & Intelligence Services

### `AIService` (`apps/core/services.py`)
Centralized wrapper for Grok-2 API. Used for:
1. **Brand Extraction**: Cleaning "INDUSTRIA DE FELTROS SANTA FE S/A" → "Santa Fé".
2. **BI Insights**: Analyzing inventory JSON to generate actionable management cards.

### `NfeImportService` (`apps/partners/services.py`)
Implements the **4-Level Match Algorithm**:
- **GOLD**: Match by EAN-13.
- **SILVER**: Match by `SupplierProductMap`.
- **BRONZE**: Match by SKU.
- **FALLBACK**: Create `PendingAssociation` (Never auto-create duplicates).

---

## ⚙️ 5. Critical Workflows for Developers

### Creating a Movement
```python
from apps.inventory.services import StockService
StockService.create_movement(
    tenant=tenant,
    movement_type='IN',  # 'IN', 'OUT', 'ADJ'
    location=location_obj,
    product=product_obj,
    quantity=50,
    unit_cost=10.50,
    # Optional metadata
    supplier=supplier_obj,
    nfe_key='...'
)
```

### Safe Product Deletion
Check `p.can_be_safely_deleted` before calling `p.delete()`. If blocked, suggest deactivating the product (`is_active=False`) instead.

---

## 🧪 6. Verification Patterns

- **Stock Value**: Always verify if `Product.total_stock_value` is being used (handles variants) instead of `Product.current_stock` (which is 0 for Variable products).
- **Localization**: Ensure all currency values pass through `floatformat:2|intcomma`.
- **Multi-tenancy**: Every queryset MUST filter by `tenant`. Use `X.objects.filter(tenant=request.tenant)`.

---

**Last Update**: January 2026
**Version**: 15.0 - AI & Intelligence Redesign
