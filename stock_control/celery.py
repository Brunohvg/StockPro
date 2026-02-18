import os

from celery import Celery
from decouple import config

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stock_control.settings')

app = Celery('stock_control')

# Só configura conexão real se tiver broker — padrão Flowlog
broker_url = config('CELERY_BROKER_URL', default='')
if broker_url:
    app.config_from_object('django.conf:settings', namespace='CELERY')
    app.autodiscover_tasks()
else:
    app.conf.update(
        broker_url=None,
        result_backend=None,
        task_always_eager=False,
    )
