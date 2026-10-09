"""
Proteção contra tentativa e erro de senha (django-axes).

Regra: 5 senhas erradas seguidas para o mesmo usuário, vindas do mesmo IP,
bloqueiam esse par (usuário + IP) por 15 minutos. Outro usuário no mesmo IP
(loja com várias pessoas na mesma internet) e o mesmo usuário em outro IP
continuam entrando. Login certo zera a contagem.

Desbloqueio manual: admin do Django → Axes → Access attempts, ou
``python manage.py axes_reset_username email@cliente.com``.
"""
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.http import JsonResponse
from django.shortcuts import render

from axes.backends import AxesStandaloneBackend


class AxesBackend(AxesStandaloneBackend):
    """Igual ao do axes, mas ignora chamadas internas sem request.

    authenticate() sem request só acontece em código do próprio servidor
    (shell, testes); login pela web, pelo admin e pela API sempre passa o request.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if request is None:
            return None
        return super().authenticate(request, username=username, password=password, **kwargs)


def client_ip(request):
    """Mesmo critério de IP do throttling da API (API_NUM_PROXIES).

    No Coolify o Traefik acrescenta o IP real do cliente no fim do
    X-Forwarded-For; com N proxies confiáveis, o cliente é o N-ésimo a partir
    do fim. Valores antes disso podem ter sido forjados pelo próprio cliente.
    """
    num_proxies = getattr(settings, 'AXES_NUM_PROXIES', 0)
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if num_proxies and xff:
        addrs = [a.strip() for a in xff.split(',') if a.strip()]
        if addrs:
            return addrs[-min(num_proxies, len(addrs))]
    return request.META.get('REMOTE_ADDR', '')


def normalize_username(request, credentials):
    """Chave do usuário para a contagem de tentativas.

    O login aceita e-mail ou username, com qualquer caixa. Tudo que aponta para
    a mesma conta vira a mesma chave (o username dela); assim 'Bruno@X.com',
    'bruno@x.com' e 'bruno' somam juntos, e o login certo (que o axes registra
    pelo username) zera a contagem de verdade.
    """
    from django.contrib.auth import get_user_model
    from django.db.models import Q

    credentials = credentials or {}
    typed = (credentials.get('username') or credentials.get('email') or '').strip()
    if not typed:
        return ''
    User = get_user_model()
    matches = list(
        User.objects.filter(Q(username__iexact=typed) | Q(email__iexact=typed))
        .values_list('username', flat=True)[:2]
    )
    if len(matches) == 1:
        return matches[0].lower()
    return typed.lower()


def _minutes():
    cool_off = settings.AXES_COOLOFF_TIME
    return int(cool_off.total_seconds() // 60) if cool_off else None


def lockout_response(request, original_response=None, credentials=None):
    minutes = _minutes()
    message = (
        f"Muitas tentativas de login com senha errada. Por segurança, este acesso "
        f"ficou bloqueado por {minutes} minutos. Se esqueceu a senha, fale com o "
        f"administrador da sua empresa."
    )
    wants_json = (
        request.path.startswith('/api/')
        or 'application/json' in request.headers.get('Accept', '')
        or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    )
    if wants_json:
        response = JsonResponse(
            {'detail': message, 'code': 'login_locked', 'retry_after_minutes': minutes},
            status=429,
        )
    else:
        response = render(request, 'registration/login.html', {
            'form': AuthenticationForm(request),
            'lockout_message': message,
        }, status=429)
    if minutes:
        response['Retry-After'] = str(minutes * 60)
    return response
