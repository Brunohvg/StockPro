Aqui está o arquivo Markdown estruturado e otimizado. Este documento foi desenhado para ser colado diretamente no chat do Gemini (Antigravity), garantindo que ele assuma a postura de arquiteto sênior e respeite todas as suas travas de domínio.

---

# 📦 PRD & TECHNICAL ARCHITECTURE: STOCK CONTROL SYSTEM

## 🎯 1. Domínio e Escopo (Regras Inegociáveis)

Este sistema é **exclusivamente** para controle de **ESTOQUE FÍSICO**.

* **Regra Máxima:** Chegou fisicamente  ENTRADA. Saiu fisicamente  SAÍDA.
* **Proibição Absoluta:** Não criar lógica de vendas, pedidos, clientes, faturamento ou regras comerciais.
* **Independência:** O sistema opera isolado de sistemas legados de vendas.
* **Responsabilidade:** Toda e qualquer alteração no saldo deve ter um usuário autenticado e um motivo.

## 🛠️ 2. Stack Tecnológica

* **Framework:** Django (Latest Stable) - Monolito com Django Templates.
* **API:** Django REST Framework (DRF) para futura integração mobile.
* **Async:** Celery + Redis (Obrigatório para importação de XML/NF-e e Planilhas).
* **Frontend:** Django Templates (Mobile-first) + HTMX para interatividade.
* **Infra:** Docker Swarm + Portainer (Stateless design).

## 🗄️ 3. Modelagem de Dados e Integridade

### Produto (`Product`)

* SKU (PK único), Nome, Categoria, Marca, UOM, Estoque Mínimo.
* `current_stock`: Campo informativo (denormalizado), atualizado **apenas** via Signals ou Service Layer após movimentação.

### Movimentação (`StockMovement`)

* **Imutável:** Não permite `UPDATE` ou `DELETE`.
* Campos: `product`, `type` (IN, OUT, ADJUSTMENT), `quantity`, `balance_before`, `balance_after`, `user`, `timestamp`, `reason`, `source`.
* **Auditoria:** Deve armazenar `idempotency_key` para evitar duplicidade via API.

## ⚙️ 4. Regras de Negócio Técnicas

1. **Atomicidade:** Toda movimentação deve usar `transaction.atomic()`. O saldo do produto e o registro da movimentação devem persistir juntos ou falhar juntos.
2. **Ajustes:** O tipo `ADJUSTMENT` é restrito a perfis de Administrador e exige justificativa textual.
3. **Importação:** O processamento de XML de NF-e deve ser assíncrono (Celery), extraindo chave da nota e fornecedor apenas para fins de histórico de entrada.
4. **Mobile:** As telas de movimentação devem ser otimizadas para leitura de QR Code/Barcode via navegador/app.

## 🚨 5. Diretrizes Anti-Alucinação

* NÃO gere modelos de `Customer`, `Order`, `Sale` ou `Invoice`.
* NÃO crie campos de "Preço de Venda".
* O estoque NUNCA deve ser editado diretamente no Django Admin sem gerar um `StockMovement`.

## 📂 6. Saída Esperada

Ao processar este prompt, forneça:

1. Modelos Django com `get_absolute_url` e `__str__` adequados.
2. Camada de Serviço (`services.py`) para processar entradas e saídas.
3. Configuração do Celery para as tarefas de importação.
4. Templates base usando um design limpo e funcional (Dashboard + Listagem + Formulários).

---

**STATUS:** VERSÃO FINAL · IMUTÁVEL

---


