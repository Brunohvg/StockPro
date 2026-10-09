# Revisão do parecer externo — 09/10/2026

## Escopo e decisão

Revisão do código da branch feature/bibelo-coolify-deploy, após 8356182. Não foram executados ataques ou alterações de contas/dados em produção. Os 10 testes enviados pelo usuário demonstram comportamento vulnerável; para regressão devem ser invertidos para exigir a rejeição do ataque. Não confundir teste de exploração passando com sistema seguro.

**Corrigir autenticação e autorização antes de piloto real ou venda.** O deploy Running comprova disponibilidade, não segurança. As correções de CSS/sendfile desta sessão não resolvem os problemas abaixo.

## Confirmado por inspeção do código atual

| Achado | Evidência | Prioridade |
| --- | --- | --- |
| Login sem verificar senha quando a consulta é ambígua | apps/accounts/backends.py, ramo MultipleObjectsReturned retorna o primeiro e-mail sem check_password nem user_can_authenticate. Signup compara email de forma sensível a maiúsculas. | Crítica |
| Upgrade sem autorização ou pagamento | apps/tenants/views.py, billing_upgrade tem somente login_required, define plano e ACTIVE no POST. | Crítica |
| Mobile sem tenant | TenantMiddleware isenta /mobile/; mobile_views._get_tenant usa apenas request.tenant. | Alta |
| Operador pode executar ações administrativas | core.views.employee_create/system_settings só exigem login; EmployeeForm permite criar e-mail/username e a view transforma o toggle em role ADMIN. Exclusões de produtos/categorias também não exigem papel administrativo. | Alta |
| Histórico removido em exclusões | products.views apaga StockMovement de entradas/ajustes antes de excluir produtos/variantes. | Alta |
| API resolve primeiro membership sem validar status | core.api.views e inventory.api_views usam fallback por membership ativo sem política de assinatura/trial; não oferecem seleção explícita consistente. | Alta |
| XSS no gráfico | reports.html injeta category_labels com safe dentro de script. A view fornece nomes de categorias. Substituir por json_script e JSON.parse. | Alta |
| Quantidade negativa no serviço | StockService.create_movement converte Decimal e OUT subtrai a quantidade sem exigir positivo/finito; referência de location também não é validada por tenant ali. | Alta |
| Dados de outro usuário no detalhe | reports.views.employee_detail busca User apenas por id; movimentos são filtrados por tenant, mas o usuário não. | Alta |
| IA sem verificação de plano | products.views.ai_enhance_product_api tem apenas login_required antes de AIService.call_ai. | Alta |
| Trial depende de proteções parciais | middleware apenas marca trial_expired; cleanup_expired_trials conta/loga, sem bloquear; vários endpoints não usam trial_allows_read. | Alta |
| Cookies seguros/HTTPS Django ausentes | settings não define SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE, SECURE_SSL_REDIRECT ou HSTS. Traefik redireciona HTTPS, mas isso não configura flags dos cookies. | Alta |

## Evidência parcial / não revalidada integralmente

- Árvore Git contém db.sqlite3.bak_fresh e XMLs/CSV em imports/. Não abri esses arquivos nem verifiquei os números de usuários/produtos do parecer, nem se as senhas ainda são usadas. A limpeza requer preservar documentos necessários e decidir histórico/rotação; remover arquivo de HEAD não apaga versões antigas.
- Há NfeParser/NfeImportService, mas a task de importação informa NF-e/legado descontinuado. A existência das classes não comprova fluxo utilizável. Revisar promessa comercial.
- Não há EMAIL_* em settings; a falha SMTP é plausível, mas não foi testado envio nem inspecionado segredo/env do painel.
- Backup cria ExportBatch por tenant. Não foi testada restauração, destino externo nem toda retenção.
- Não reproduzi os números 60/17 da suíte externa; não declarar 17 falhas confirmadas nesta sessão. O teste novo de estáticos passou isoladamente com versões de produção.

## Ordem de correção

1. Eliminar retorno de usuário sem senha em todas as situações e rejeitar identidades ambíguas; auditar duplicatas, normalizar e-mail e adicionar unicidade sem alterar contas silenciosamente.
2. Bloquear mudanças de plano/status pela rota de cliente enquanto não existir confirmação confiável de pagamento. A administração já possui fluxo exclusivo de superusuário.
3. Remover dados de operação de futuras imagens/Git HEAD e definir tratamento do histórico e credenciais sem apagar documentos de produção.
4. Restaurar resolução de tenant no mobile e testar operador real em ambiente isolado.
5. Centralizar política de papéis, assinatura/trial e seleção de empresa entre web/API; proteger histórico.
6. Corrigir XSS, validações de quantidade/localização, exposição de usuário, recursos de IA e flags de produção.
7. Revalidar suíte/CI, e-mail, NF-e e backups.

Não liberar cadastro/comercialização apenas porque os primeiros quatro itens forem feitos: os demais achados altos também precisam de correção e regressão.

## Verificações adicionais feitas nesta sessão

- API do GitHub retornou private=false, visibility=public para Brunohvg/StockPro. O histórico desses arquivos precisa ser tratado como público; não basta excluir apenas da branch atual. Não foram apagados arquivos nem reescrito histórico nesta revisão.
- Teste local com código real do EmailBackend, Django 5.2.10 e SQLite isolado: duas contas fictícias com e-mail equivalente em maiúsculas/minúsculas; uma senha incorreta autenticou a primeira conta. Falha crítica reproduzida independentemente, sem acessar contas de produção.
- As demais confirmações são inspeção de código; não foi executada a suíte integral nem os dez testes externos.
- Ajuste de CSS/sendfile implantado em 1c3776b. Autenticação, cobrança, papéis e demais achados acima continuam pendentes.
