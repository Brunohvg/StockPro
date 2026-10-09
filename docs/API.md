# API REST do StockPro (v1)

Base: `https://stock.optarys.com.br/api/v1/`. Respostas em JSON. Listas são paginadas (`?page=N`, 50 por página).

## Autenticação

```http
POST /api/v1/auth/token/
{"username": "email@empresa.com", "password": "..."}
→ {"access": "...", "refresh": "..."}
```

Use `Authorization: Bearer <access>` nas demais chamadas. O access vale 1 hora; renove com `POST /api/v1/auth/token/refresh/` enviando `{"refresh": "..."}` (o refresh vale 1 dia).

**Empresa:** X-Tenant-ID explícito sempre tem prioridade, inclusive com sessão. Busca mobile por sessão sem header usa a empresa selecionada. JWT não usa o cookie de sessão para escolher empresa. Se o usuário pertence a mais de uma empresa, envie também `X-Tenant-ID: <id da empresa>`. Sem o header, a API responde 400. Com uma empresa só, o header é opcional.

**Bloqueios:** empresa suspensa ou cancelada recebe 403 em tudo; trial vencido recebe 403 em escrita (POST/PUT/PATCH/DELETE).

**Limites de requisição** (configuráveis por variável de ambiente):

| Escopo | Padrão | Variável |
|---|---|---|
| Token e refresh | 20/minuto | `API_THROTTLE_AUTH` |
| Usuário autenticado | 1200/hora | `API_THROTTLE_USER` |
| Anônimo | 300/hora | `API_THROTTLE_ANON` |

Ao estourar o limite, a resposta é 429 com o cabeçalho `Retry-After`.

## Estoque

### Buscar produto
`GET /api/v1/products/search/?q=<nome, SKU ou código de barras>` (mínimo 2 caracteres, até 20 resultados)

```json
{"results": [{"variant_id": "12", "product_id": "8", "sku": "CAN-AZ", "barcode": "789...",
  "display_name": "Caneta Azul", "current_stock": 15.0, "minimum_stock": 5.0, "unit": "UN",
  "avg_unit_cost": 1.2, "product_type": "SIMPLE", "low_stock": false}], "count": 1}
```

### Entrada
`POST /api/v1/inventory/entry/`
```json
{"reference": "NF-001", "items": [{"sku": "CAN-AZ", "quantity": 10, "unit_cost": 1.5}]}
```
O `unit_cost` é opcional e, quando informado, atualiza o custo médio ponderado.

### Saída (pedido)
`POST /api/v1/inventory/consume/`
```json
{"external_order_id": "PED-123", "platform": "NUVEMSHOP", "items": [{"sku": "CAN-AZ", "quantity": 2}]}
```

Nas duas rotas a resposta é 200 se todos os itens foram processados, ou 207 com `errors` por item (SKU inexistente, saldo insuficiente, quantidade ≤ 0). Cada item é independente: os que deram certo ficam gravados.

## Catálogo

| Método | Rota | Observação |
|---|---|---|
| GET | `/products/` | Lista os produtos da empresa, com as variações |
| POST | `/products/` | Cria o produto. Campos: `name`, `sku`, `product_type` (`SIMPLE`/`VARIABLE`), `category`, `brand`, `barcode`, `minimum_stock`, `description`. Respeita o limite de produtos do plano |
| POST | `/products/?staged=true` | Não cria: envia o item para a **Curadoria** (ver abaixo) |
| GET/PATCH/DELETE | `/products/<id>/` | |
| GET | `/variants/` | Lista as variações |
| POST | `/variants/` | Cria uma variação: `{"product": <id de produto VARIABLE>, "sku": "...", "name": "...", "barcode": "..."}` |
| GET/PATCH/DELETE | `/variants/<id>/` | |

`current_stock` e `avg_unit_cost` são somente leitura. O estoque só muda pelas rotas de entrada e saída (ou pelas telas), para manter o histórico. SKU duplicado na empresa retorna 400. Validações prévias não substituem revisão de concorrência em todas as operações de catálogo.

## Curadoria (itens em staging)

Exige usuário OWNER ou ADMIN.

| Método | Rota | |
|---|---|---|
| GET | `/staging/?status=PENDING` | `PENDING` (padrão), `DONE`, `REJECTED` ou `ALL` |
| GET | `/staging/<id>/` | |
| POST | `/staging/<id>/approve/` | Cria o produto SIMPLE (ou vincula a um existente com o mesmo SKU) e registra a entrada, se houver quantidade |
| POST | `/staging/<id>/reject/` | Rejeita o item |

Pela interface web, o mesmo fica em **Curadoria (API)**, no menu lateral (somente administradores).

## Códigos de erro

| Código | Quando |
|---|---|
| 400 | Dados inválidos, SKU duplicado ou falta do `X-Tenant-ID` |
| 401 | Token ausente ou expirado |
| 403 | Empresa bloqueada, trial vencido (escrita), falta de permissão ou limite do plano |
| 404 | Recurso de outra empresa ou inexistente |
| 409 | Item da curadoria já processado |
| 429 | Limite de requisições |


## Cadastro por CNPJ

GET /partners/api/suppliers/cnpj/?cnpj=<14 dígitos>: OWNER/ADMIN, empresa ativa, limite20/min. Resposta {cnpj, provider, fields}; campos company_name,trade_name,email,phone,zip_code,address,city,state. Apenas consulta pública, não cria fornecedor. 400 inválido,404 não encontrado,429 limite,503 indisponível; preenchimento manual continua permitido. BrasilAPI primária e ReceitaWS fallback; dados podem estar incompletos/desatualizados, confira antes de salvar.

Cache padrão no Redis DB2. API_NUM_PROXIES=1 assume o Traefik como último proxy confiável para identificar IP no throttle anônimo/token; ajuste junto da arquitetura. Login web não é protegido pelo throttle DRF. Sem CACHE_URL/broker Redis, cache local é por processo; em produção mantenha Redis compartilhado.
