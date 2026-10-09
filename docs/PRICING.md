# Preços de catálogo — 09/10/2026

| Plano | Mensalidade padrão |
| --- | --- |
| Gratuito | R$ 0 |
| Profissional | R$ 97 |
| Empresarial | R$ 697 |

O Empresarial passou de R$ 247 para R$ 697 por decisão comercial solicitada pelo mantenedor. É um preço inicial a validar com clientes, não uma comprovação de demanda ou comparação de mercado.

A fonte para landing page, painel de planos e mensagem de solicitação de upgrade é `Plan.price` no banco. A migração `0004_enterprise_price_697` atualiza apenas EMPRESARIAL com o preço padrão anterior (247). Preços personalizados ficam preservados. O fallback da landing também foi atualizado.

Não alterar migrações já aplicadas para mudar preços. Criar nova migração de dados; preservar limites, funcionalidades, identidade do plano e vínculos das empresas. O rollback desta migração devolve 697 para 247; faça-o somente se esse retorno de catálogo for desejado.

As telas de empresas já vinculadas ao registro EMPRESARIAL também passam a mostrar o novo preço de catálogo. O sistema atual não mantém preço contratado individual nessa estrutura; este ajuste não executa cobrança, não envia aviso ao cliente e não altera contrato externo. A cobrança segue manual.

Para aplicar em produção: deploy da branch com esta migração; o entrypoint web executa migrate automaticamente. Verificar landing com R$ 697 e logs da migração. Planos personalizados preservados podem exibir valores diferentes.

Valor comercial depende de resultado entregue, implantação, estabilidade e suporte. Limites técnicos e recursos existentes foram mantidos; nenhuma promessa funcional nova foi acrescentada.
