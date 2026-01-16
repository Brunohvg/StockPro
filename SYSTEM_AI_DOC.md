# 🤖 StockPro System Documentation (AI-Ready)

This document provides a comprehensive overview of the **StockPro** system architecture, domain rules, and technical implementation. It is designed to enable any AI agent to understand, maintain, and extend the system with high precision.

---

## 🎯 1. Core Mission & Domain Boundaries

**StockPro** is a dedicated **Physical Inventory Management System**.

### 🚫 Non-Negotiable Rules (Anti-Hallucination)
1. **Physical Focus Only**: Every movement (IN, OUT, ADJ) MUST correspond to a physical change in stock.
2. **No Sales Logic**: Do NOT implement Orders, Customers, Sales, Invoices, or Pricing logic (beyond cost).
3. **No Direct Edits**: Stock levels (`current_stock`) must NEVER be edited directly via Django Admin or shell without creating a corresponding `StockMovement` via the Service Layer.
4. **Immutability**: `StockMovement` records are immutable. No `UPDATE` or `DELETE` allowed.

---

## 🏗️ 2. High-Level Architecture

| Component | Technology | Description |
|-----------|------------|-------------|
| **Backend** | Django 5.2 (Modular Monolith) | Core business logic decoupled into independent apps (`accounts`, `products`, `inventory`, etc.). |
| **Frontend** | Django Templates + HTMX + Tailwind | Server-side rendering with reactive UI pieces. |
| **Multi-tenancy** | Middleware + Session | Multi-company isolation within a single database. |
| **Logic Layer** | Service Layer (`services.py`) | All domain logic resides in dedicated service classes. |
| **Task Queue** | Celery + Redis | Asynchronous processing for heavy imports (CSV/XML). |
| **Infrastructure** | Docker Swarm | Containerized deployment with Traefik as Load Balancer. |

---

## 🗄️ 3. Data Model & Relationships

### 🏢 Multi-tenancy (App: `tenants`, `accounts`)
- **Tenant**: Represents a company/organization. Tracks `plan`, `subscription_status`, and `trial_ends_at`.
- **Plan**: Defines limits (`max_products`, `max_users`).
- **TenantMembership**: Links `User` to `Tenant` with a **Role** (`OWNER`, `ADMIN`, `OPERATOR`).
- **TenantInvite**: Token-based invitation system for new members.

### 📦 Products & Inventory (App: `products`, `inventory`)
- **Category**: Product grouping with `rotation` classification (A, B, C).
- **Product**:
    - `product_type`: `SIMPLE` (single SKU) or `VARIABLE` (parent of variants).
    - `current_stock`: Denormalized field updated via services.
- **ProductVariant**: Specific version of a `VARIABLE` product (e.g., Size: M, Color: Blue).
- **VariantAttributeValue**: Pivot for dynamic attributes (AttributeType: Color -> Value: Blue).
- **StockMovement**: The ledger of all changes. Tracks `type` (IN, OUT, ADJ), `quantity`, `balance_after`, and `unit_cost`.

---

## ⚙️ 4. Critical Business Logic

### 🔄 Inventory Engine (`apps/core/services.py`)
All stock changes MUST use `StockService.create_movement()`.
- **Atomicity**: Uses `transaction.atomic()` to ensure balance update and movement record persist together.
- **Row Locking**: Uses `select_for_update()` to prevent race conditions during concurrent updates.
- **Costing**: Implements **Weighted Average Cost (Custo Médio Ponderado)** on every `IN` (Entry) movement.
- **Validation**: Prevents negative stock on `OUT` (Exit) movements.

### 🔐 Multi-tenant Security (`apps/tenants/middleware.py`)
- **Isolation**: `TenantMiddleware` injects `request.tenant` and `request.membership`.
- **Status Checks**: Blocks access if tenant is `SUSPENDED` or `CANCELLED`.
- **Trial Guard**: Flags `request.trial_expired` if Trial Period ends.
- **Decorators**:
    - `@trial_allows_read`: Blocks POST/PUT if trial is expired.
    - `@owner_required` / `@admin_required`: Enforce RBAC.

---

## 🚀 5. Workflows & Lifecycle

### 📥 Import Processes
1. **Upload**: User uploads CSV or XML (NF-e).
2. **Batch**: `ImportBatch` record is created with `PENDING` status.
3. **Queue**: Celery task is triggered.
4. **Execution**:
    - Validates idempotency via `ImportLog`.
    - Resolves products/variants by SKU or Barcode.
    - Calls `StockService` for each row.
5. **Completion**: Batch status updated to `COMPLETED`/`PARTIAL`/`ERROR`.

### 🛡️ Deployment Flow (`deploy.sh`)
- Uses Docker Swarm.
- **Build**: Compresses layers for ARM64 (production) and standard x86.
- **Migrate**: Runs as a one-off task within the Swarm context.
- **Stack**: Services: `app`, `worker`, `beat`, `redis`. (DB is usually external).

---

## 🛠️ 6. Guidelines for AI Assistants

- **Modifying Models**: Always check if the model inherits from `TenantMixin`. If so, ensure all queries filter by `tenant`.
- **Adding Features**: Ensure logic is placed in `services.py`, not in `views.py` or `models.py`.
- **UI Changes**: Use `HTMX` for partial page updates (look for `hx-` attributes in templates).
- **Static Assets**: Use Tailwind CSS classes. Do not write inline CSS.
- **Environment**: Always reference variables through `decouple.config`.

---

**Last Updated**: 2026-01-16
**Version**: 11.0 (Stable)
