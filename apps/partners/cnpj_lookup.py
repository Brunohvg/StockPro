"""Consulta pública de CNPJ; nenhum segredo nem URL fornecida pelo usuário."""
import re

import requests
from django.core.cache import cache

from .models import validate_cnpj


class CNPJLookupError(ValueError):
    def __init__(self, message, status=503):
        self.status = status
        super().__init__(message)


def _normalize(data, cnpj, provider):
    if not isinstance(data, dict):
        raise CNPJLookupError('Serviço de consulta retornou dados inválidos.')
    returned_cnpj = re.sub(r'\D', '', str(data.get('cnpj', '')))
    name = data.get('razao_social') if provider == 'BrasilAPI' else data.get('nome')
    if returned_cnpj != cnpj or not isinstance(name, str) or not name.strip():
        raise CNPJLookupError('Serviço de consulta retornou dados incompletos.')
    fields = {
        'company_name': name,
        'trade_name': data.get('nome_fantasia' if provider == 'BrasilAPI' else 'fantasia'),
        'email': data.get('email'),
        'phone': data.get('ddd_telefone_1' if provider == 'BrasilAPI' else 'telefone'),
        'zip_code': data.get('cep'),
        'address': ', '.join(str(data.get(k) or '').strip() for k in ['logradouro', 'numero', 'bairro'] if data.get(k)),
        'city': data.get('municipio'),
        'state': data.get('uf'),
    }
    return {'cnpj': cnpj, 'provider': provider, 'fields': {k: str(v or '').strip() for k, v in fields.items()}}


def lookup_cnpj(value):
    cnpj = re.sub(r'\D', '', value)
    validate_cnpj(cnpj)
    key = 'cnpj:public:v1:' + cnpj
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        response = requests.get('https://brasilapi.com.br/api/cnpj/v1/' + cnpj,
                                timeout=(3, 8), headers={'Accept': 'application/json'})
        if response.status_code == 404:
            raise CNPJLookupError('CNPJ não encontrado na base consultada. Você pode preencher manualmente.', 404)
        response.raise_for_status()
        result = _normalize(response.json(), cnpj, 'BrasilAPI')
    except CNPJLookupError as exc:
        if exc.status == 404:
            raise
        result = _fallback(cnpj)
    except (requests.RequestException, ValueError):
        result = _fallback(cnpj)
    cache.set(key, result, timeout=86400)
    return result


def _fallback(cnpj):
    # API pública ReceitaWS: 3/min; trava compartilhada espaça chamadas.
    if not cache.add('cnpj:receitaws:cooldown', True, timeout=21):
        raise CNPJLookupError('Consulta temporariamente indisponível. Aguarde um pouco ou preencha manualmente.')
    try:
        response = requests.get('https://receitaws.com.br/v1/cnpj/' + cnpj,
                                timeout=(3, 8), headers={'Accept': 'application/json'})
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get('status') == 'ERROR':
            raise CNPJLookupError('CNPJ não encontrado na base consultada. Você pode preencher manualmente.', 404)
        return _normalize(data, cnpj, 'ReceitaWS')
    except (requests.RequestException, ValueError) as exc:
        if isinstance(exc, CNPJLookupError):
            raise
        raise CNPJLookupError('Não foi possível consultar o CNPJ agora. Tente novamente ou preencha manualmente.') from exc
