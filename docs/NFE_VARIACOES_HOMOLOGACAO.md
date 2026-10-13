# NF-e: agrupamento seguro de produtos configuráveis

## Regra
A nota fiscal não identifica de forma padronizada um "produto pai". A descrição do fornecedor
não é prova suficiente de que itens pertencem ao mesmo grupo. Por isso a criação de grupos
é **explícita na tela de revisão**, antes de registrar entradas.

Para cada item em **Criar produto novo**, o administrador pode informar:
- **SKU do pai**: mesmo valor para todas as variações do grupo.
- **Nome do pai**: obrigatório somente quando o pai ainda não existe.
- **Atributos**: `Cor:Azul; Tamanho:M` (obrigatórios se o SKU pai for informado).
- **Nome do item**: nome específico da variação.

Se o SKU pai estiver vazio, continua criando produto simples, como antes.
Se já existir um pai configurável com aquele SKU na mesma empresa, cria a variação dentro dele.
Nunca agrupar automaticamente por nomes parecidos.

## Segurança
- Banco utiliza transação para confirmação da NF-e; exceções anulam todos os lançamentos.
- Rejeita pai do tipo simples, atributos incompletos ou duplicados e variação repetida.
- Identifica o pai por empresa/SKU e preserva os vínculos aprendidos com o fornecedor.
- Limite do plano contabiliza produtos pais novos, não a quantidade de variações.
- NF-e não importada permanece em prévia se a validação falhar.
- Exige a migração `inventory.0005_nfe_variacoes`.

## Checklist obrigatório antes de merge/deploy
1. Executar `python manage.py check`, `makemigrations --check --dry-run` e `migrate`.
2. Executar `pytest -o addopts="" tests/test_patch5_nfe.py tests/test_patch10.py`.
3. Executar a suíte completa.
4. Homologar com duas cores/tamanhos do mesmo pai e conferir saldos separados.
5. Importar segunda NF-e com códigos de fornecedor já aprendidos: deve vincular, sem duplicar.
6. Confirmar estorno da nota e rejeição de importação duplicada.
7. Validar limite de plano, isolamento entre empresas, EAN duplicado e rollback em erro.
8. Tirar backup do PostgreSQL e comprovar restauração em ambiente separado.

Não realizar deploy só porque os commits foram publicados. A branch de deploy não foi alterada.
