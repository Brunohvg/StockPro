# Homologação: lotes, etiquetas e backup

## Exportação de lotes
`ProductExporter(tenant).export_lots_csv()` gera um relatório separado dos saldos por lote:
SKU, produto, número do lote, validade, fabricação e saldo de lote. É uma **fotografia
informativa**, não um arquivo para reimportar automaticamente. A exportação normal
do catálogo continua contendo o saldo total por variação.

Não carregar o CSV de lotes no importador de catálogo: ele usa estoque absoluto
para a primeira linha e acumula lotes adicionais. Repetir a importação de lotes
pode duplicar saldo. A restauração de dados deve utilizar o backup completo do
PostgreSQL, não a reimportação de CSV. Idempotência dos lotes permanece item
de bloqueio antes de homologar com dados relevantes.

## Etiquetas
Operadores podem imprimir etiquetas, mas apenas OWNER/ADMIN podem gravar
nome e código de etiqueta personalizados que afetam toda a empresa.

## Backup e restauração: checklist operacional
1. Conferir backup recente do PostgreSQL no Coolify, sua integridade e retenção.
2. Restaurar em **banco isolado de homologação**, nunca no banco de produção.
3. Aplicar as migrações necessárias; conferir produtos, variações, lotes,
   movimentos, usuários e empresas contra contagens do backup original.
4. Verificar que o somatório por lote não supera o estoque da variação.
5. Validar que a aplicação de homologação tem segredos e serviços próprios.
6. Executar importação de NF-e repetida: duplicidade deve ser bloqueada.
7. Conferir importação e estorno de nota com 2 lotes e 2 variações.
8. Registrar prova da restauração (logs, data, duração, resultados).
Nenhum destes testes de restauração foi executado pela publicação de código.

## Validação
`python manage.py check`
`python manage.py makemigrations --check --dry-run`
`pytest -o addopts="" tests/`

Deploy somente após CI verde e revisão operacional.
