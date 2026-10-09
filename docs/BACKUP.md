# Backup e restauração do StockPro (Coolify)

## O que roda sozinho

| Quando | Tarefa | O que faz |
|---|---|---|
| 03:30 | `apps.tenants.backup_task.daily_backup` (worker) | `pg_dump` do PostgreSQL 17 (`--no-owner --no-privileges`) em `.sql.gz`, conferido (gzip íntegro e rodapé `PostgreSQL database dump complete`) + `.tar.gz` da mídia (fotos e XMLs, sem `media/exports`). Se `BACKUP_S3_BUCKET` estiver definido: criptografa com GPG AES-256 (se houver senha), envia ao bucket, confere o tamanho no destino e aplica a retenção remota. |
| 04:15 | `apps.tenants.backup_task.cleanup_old_exports` | Apaga exportações sem usuário (as que o backup antigo criava) e exportações com mais de `EXPORT_RETENTION_DAYS` dias. |

Cada execução fica registrada no admin em **Execuções de backup**, com o status, os tamanhos, as chaves no bucket e a mensagem de erro. Uma falha dispara um e-mail para `BACKUP_ALERT_EMAIL` (ou para `ADMINS`), o que exige SMTP configurado.

O dump `.sql.gz` também fica no volume `stockpro_backups` (`/data/backups`) por `BACKUP_RETENTION_DAYS` dias. **Ele não protege contra a perda do servidor:** para isso serve o bucket.

## Variáveis (Coolify → Environment Variables)

| Variável | Exemplo | Observação |
|---|---|---|
| `BACKUP_S3_BUCKET` | `stockpro-backups` | Vazio = backup só local |
| `BACKUP_S3_ENDPOINT_URL` | `https://s3.us-west-004.backblazeb2.com` | B2, R2 (`https://<conta>.r2.cloudflarestorage.com`), Wasabi, MinIO. Vazio para AWS |
| `BACKUP_S3_REGION` | `us-west-004` | R2 usa `auto` |
| `BACKUP_S3_ACCESS_KEY_ID` / `BACKUP_S3_SECRET_ACCESS_KEY` | | A chave deve ter acesso **só a este bucket** |
| `BACKUP_ENCRYPTION_PASSPHRASE` | (gere com `openssl rand -base64 32`) | **Guarde fora do servidor** (gerenciador de senhas). Sem ela o backup não abre |
| `BACKUP_S3_PREFIX` | `stockpro/` | |
| `BACKUP_REMOTE_RETENTION_DAYS` | `30` | Os 7 dumps mais recentes (`BACKUP_REMOTE_MIN_KEEP`) nunca são apagados |
| `BACKUP_INCLUDE_MEDIA` | `True` | |
| `BACKUP_ALERT_EMAIL` | `ti@empresa.com.br` | |

**Recomendado no bucket:** mantenha-o privado, ligue o versionamento ou o Object Lock (proteção contra exclusão por uma chave vazada) e configure uma regra de ciclo de vida de 35 dias como reforço.

## Tela de backups (painel da plataforma)

Superusuário: menu **Painel da plataforma → Ver backups** (`/admin-panel/backups/`).

- Mostra se o backup está em dia, atrasado (mais de 26 h sem concluir), falhando ou só no servidor; a configuração do bucket e da criptografia; o espaço no disco do servidor; e o histórico com tamanhos, chaves no bucket e mensagens de erro.
- **Fazer backup agora** e **Conferir último backup** rodam no worker (Celery). A conferência baixa o último dump do bucket, descriptografa e confere se está completo, e fica registrada no histórico como "Conferência".
- Não há download pelo navegador: o arquivo tem os dados de todas as empresas.
- Um backup "em andamento" há mais de 3 h aparece como **Interrompido** (worker reiniciado no meio) e não impede um novo.

Para o cliente, a tela **Exportar Dados** mostra "Seus dados estão protegidos" com a data do último backup concluído nas últimas 48 h. Se o backup estiver atrasado, o aviso simplesmente some (o cliente não vê erros técnicos).

## Comandos

```bash
# Backup na hora (dentro do container web ou worker)
python manage.py backup_now

# Baixa o último dump do bucket, descriptografa e confere a integridade
python manage.py backup_verify
```

## Restauração (teste mensal recomendado)

1. Baixe os arquivos pelo painel do bucket (ou com `aws s3 cp` / `rclone`).
2. Descriptografe:
   ```bash
   gpg -d -o stockpro_db_AAAAMMDD_HHMMSS.sql.gz stockpro_db_AAAAMMDD_HHMMSS.sql.gz.gpg
   gpg -d -o stockpro_media_AAAAMMDD_HHMMSS.tar.gz stockpro_media_AAAAMMDD_HHMMSS.tar.gz.gpg
   ```
3. **Teste em um banco temporário** (nunca direto em produção):
   ```bash
   createdb -h HOST -U USUARIO stockpro_restore_teste
   gunzip -c stockpro_db_*.sql.gz | psql -h HOST -U USUARIO -d stockpro_restore_teste -v ON_ERROR_STOP=1
   psql -h HOST -U USUARIO -d stockpro_restore_teste -c "select count(*) from products_product;"
   ```
4. Restauração real (desastre): crie um banco vazio, restaure como no passo 3 e aponte o `DATABASE_URL` do Coolify para ele. Depois extraia a mídia no volume `stockpro_media`:
   ```bash
   tar xzf stockpro_media_*.tar.gz -C /caminho/do/volume/media
   ```
5. Registre a data e o resultado do teste em `docs/COOLIFY.md`.

## Limites

- O backup é lógico (`pg_dump`) e diário. Não há recuperação ponto a ponto. Se precisar, ative o backup do próprio PostgreSQL gerenciado.
- A criptografia acontece só na cópia que vai para o bucket. O dump local fica no volume do servidor, sem criptografia, como antes.
