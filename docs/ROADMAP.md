# 🚀 StockPro - Roadmap & Ideias de Melhorias

**Última atualização:** Janeiro 2026
**Versão atual:** V15 (AI & Intelligence)

---

## ✅ Concluído (V15 - Entregue)

### 1. Inteligência Artificial
- [x] Extração inteligente de Marcas via IA (Grok-2) no import NF-e.
- [x] Insights automáticos de inventário baseados em dados reais.
- [x] Detecção de anomalias/ajustes sugeridos por IA.

### 2. Analytics & BI
- [x] Redesign Premium (Glassmorphism) da página de Inteligência.
- [x] Curva ABC Automatizada com medalhas (🥇🥈🥉).
- [x] Cálculos de Valor em Estoque precisos para Variáveis.

### 3. Logística e Segurança V2
- [x] Múltiplos Locais de estoque (Depósito, Loja, etc).
- [x] Safe Delete (Bloqueio de exclusão com histórico de vendas).
- [x] Consolidação de produtos simples em variantes.
- [x] Localização Brasileira (R$ 1.234,56).

---

## 📌 Próximos Sprints (Q2 2026)

### 1. Notificações em Tempo Real (V16)
- [ ] WebSocket com Django Channels para alertas instantâneos.
- [ ] Push notifications (PWA) de estoque baixo.
- [ ] Email digest diário com relatório de movimentações.

### 2. Pedidos de Compra (V17)
- [ ] Model `PurchaseOrder` (vínculo com fornecedor).
- [ ] Sugestão de compra baseada em algoritmos preditivos.
- [ ] Fluxo de aprovação OWNER/ADMIN.
- [ ] Recebimento parcial de pedidos.

### 3. App Mobile Operacional (V18)
- [ ] Leitor de código de barras via câmera (ZXing/Quagga).
- [ ] Fluxo de "Picking & Packing" direto no celular.
- [ ] Conferência cega de mercadoria recebida.

---

## 🔧 Melhorias Técnicas Planejadas
- [ ] Cache agressivo com Redis para consultas complexas de BI.
- [ ] Export de relatórios para PDF (ReportLab/WeasyPrint).
- [ ] API v2 Pública (DRF com OpenAPI 3).
- [ ] Auditoria visual de alterações (Audit Log com Diff).

---

*Este documento é um living document e é atualizado a cada grande release.*
