import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stock_control.settings')

# Inicializa a aplicação Django normalmente
_django_app = get_wsgi_application()

def application(environ, start_response):
    """
    WSGI Interceptor:
    Responde instantaneamente ao healthcheck (/healthcheck/)
    Garante 200 OK sem passar pelo Django, Middleware ou Auth.
    """
    path = environ.get('PATH_INFO', '').rstrip('/')

    if path == '/healthcheck':
        start_response('200 OK', [('Content-Type', 'text/plain')])
        return [b"ok"]

    # Para qualquer outra rota, segue o fluxo normal do Django
    return _django_app(environ, start_response)
