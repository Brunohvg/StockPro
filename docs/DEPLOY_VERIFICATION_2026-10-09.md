# Verificação do deploy — 2026-10-09

## Versão em produção

- Branch do Coolify: `feature/bibelo-coolify-deploy`.
- Commit executável: `7f4249f784b4fe2cd135769d9577631a1d2068ca`.
- Deployment: `wbc7pg8ufzhwmzgjtaep4wqt`; terminou com Success em 2026-10-09, aproximadamente 14:59 UTC.
- Aplicação: Running; saiu de Degraded após substituir healthchecks HTTP herdados por verificações próprias de worker e Beat.
- URL: https://stock.optarys.com.br/
- PostgreSQL separado: `db-stockpro`, Running.
- Um deploy manual duplicado que aguardava na fila foi cancelado antes de iniciar.

## Logs examinados

| Container | Evidência observada |
| --- | --- |
| web | Banco disponível; `tenants.0004_enterprise_price_697... OK`; 166 estáticos coletados; Gunicorn ouvindo em 8000; healthcheck HTTP 200. |
| worker | Conectou ao Redis em 6379/0; backend em /1; concorrência 2; tarefas registradas; `celery@e230fa50f7d6 ready`. |
| beat | Iniciou PersistentScheduler; broker Redis /0; agenda em `/data/celerybeat/celerybeat-schedule`. |
| redis | Recuperou AOF persistente e ficou pronto para aceitar conexões em 6379. |
| PostgreSQL | Pronto para conexões; checkpoints concluídos normalmente, inclusive após a migração. |

Nenhuma falha operacional apareceu nas mensagens examinadas após a inicialização. Esta verificação cobre startup, conexão, migração, healthchecks e página pública; não é teste integral de importações, exportações ou execução futura de tarefas agendadas.

## Preços conferidos em produção

Página pública exibiu Gratuito, Profissional R$ 97/mês e Empresarial R$ 697/mês após o deploy. A migração altera apenas o preço padrão antigo 247 do plano EMPRESARIAL; preserva preços personalizados. A integração de pagamento continua indicada na página como futura.

Validação local focada com Django e SQLite: aplicação forward/reverse, repetição, preservação de valores personalizados e demais planos passou. A suíte completa do repositório não foi executada nesta sessão.

## Continuidade

Leia primeiro [AGENTS.md](../AGENTS.md), [COOLIFY.md](COOLIFY.md) e [PRICING.md](PRICING.md). Mudanças desta sessão estão na branch acima; não foram mescladas em `main`. Este registro é documentação posterior ao deploy e não modifica o código executável da versão verificada.

Nunca copie senhas, DATABASE_URL completa ou chaves de API para o Git.
