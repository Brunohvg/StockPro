from django.http import HttpResponse

class HealthCheckMiddleware:
    """
    Middleware minimalista para responder ao healthcheck do Docker Swarm
    antes que o ALLOWED_HOSTS ou o TenantMiddleware criem problemas.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == '/healthcheck/':
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
