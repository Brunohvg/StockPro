import os
import django
from celery import Celery
from django.conf import settings

# Setup Django if not already (for shell usage)
if not settings.configured:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stock_control.settings')
    django.setup()

print("--- DIAGNÓSTICO CELERY/REDIS ---")
broker = settings.CELERY_BROKER_URL
print(f"Buscando Broker em: {broker}")

try:
    from redis import Redis
    # Parse redis URL
    if "redis://" in broker:
        # Simple parse for diagnosis
        parts = broker.split("://")[1].split("/")[0].split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 6379
        db = int(broker.split("/")[-1]) if len(broker.split("/")) > 3 else 0

        r = Redis(host=host, port=port, db=db, socket_timeout=5)
        r.ping()
        print(f"✅ Conexão direta com REDIS ({host}:{port}) OK!")
    else:
        print("❌ Broker URL não reconhecida como Redis.")
except Exception as e:
    print(f"❌ Falha ao conectar no REDIS: {e}")

try:
    from stock_control.celery import app as celery_app
    i = celery_app.control.inspect()
    active = i.active()
    if active:
        print(f"✅ Workers Ativos Detectados: {list(active.keys())}")
        for worker, tasks in active.items():
            print(f"   - {worker}: {len(tasks)} tasks em execução")
    else:
        print("⚠️ Nenhum worker ativo detectado via inspect. Verifique se o serviço 'stockpro_worker' está rodando.")
except Exception as e:
    print(f"❌ Falha ao inspecionar workers: {e}")

try:
    print("Enviando tarefa de teste (delay)...")
    from apps.tenants.tasks import cleanup_expired_trials
    result = cleanup_expired_trials.delay()
    print(f"✅ Tarefa enviada! ID: {result.id}")
    print("DICA: Verifique os logs do worker para ver se esta tarefa foi recebida.")
except Exception as e:
    print(f"❌ Falha ao enviar tarefa: {e}")
