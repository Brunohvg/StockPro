from unittest.mock import Mock, patch
import pytest
import requests
from django.test import Client
from apps.accounts.models import TenantMembership
from apps.partners.cnpj_lookup import lookup_cnpj, CNPJLookupError
from tests.factories import UserFactory, TenantFactory

CNPJ='00000000000191'
DATA={'cnpj':CNPJ,'razao_social':'Empresa de referência','nome_fantasia':'Referência','qsa':[{'nome_socio':'Não retornar'}]}

def response(data=DATA,status=200):
    r=Mock(status_code=status);r.json.return_value=data
    if status>=400: r.raise_for_status.side_effect=requests.HTTPError('Error')
    return r

@pytest.mark.django_db
def test_lookup_normalizes_and_caches_public_fields():
    with patch('apps.partners.cnpj_lookup.requests.get',return_value=response()) as get:
        result=lookup_cnpj('00.000.000/0001-91')
        assert result['fields']['company_name']=='Empresa de referência' and 'qsa' not in result
        assert lookup_cnpj(CNPJ)==result and get.call_count==1
        assert 'Authorization' not in get.call_args.kwargs['headers']

@pytest.mark.django_db
def test_timeout_uses_fallback_with_shared_cooldown():
    fallback={'cnpj':CNPJ,'nome':'Empresa de referência','fantasia':'Referência'}
    with patch('apps.partners.cnpj_lookup.requests.get',side_effect=[requests.Timeout(),response(fallback)]):
        assert lookup_cnpj(CNPJ)['provider']=='ReceitaWS'

@pytest.mark.django_db
def test_both_services_unavailable_give_useful_error():
    with patch('apps.partners.cnpj_lookup.requests.get',side_effect=requests.Timeout()):
        with pytest.raises(CNPJLookupError,match='preencha manualmente'): lookup_cnpj(CNPJ)

@pytest.mark.django_db
def test_lookup_rejects_invalid_cnpj_without_external_call():
    from django.core.exceptions import ValidationError
    with patch('apps.partners.cnpj_lookup.requests.get') as get:
        with pytest.raises(ValidationError): lookup_cnpj('11111111111111')
        get.assert_not_called()

@pytest.mark.django_db
def test_lookup_endpoint_requires_admin_and_keeps_registration_manual():
    u=UserFactory();t=TenantFactory();m=TenantMembership.objects.create(user=u,tenant=t,role='OPERATOR')
    c=Client();c.force_login(u)
    with patch('apps.partners.cnpj_lookup.requests.get',return_value=response()) as get:
        assert c.get('/partners/api/suppliers/cnpj/',{'cnpj':CNPJ}).status_code==403
        get.assert_not_called()
        m.role='OWNER';m.save()
        assert c.get('/partners/api/suppliers/cnpj/',{'cnpj':'bad'}).status_code==400
        r=c.get('/partners/api/suppliers/cnpj/',{'cnpj':CNPJ})
        assert r.status_code==200 and r.json()['fields']['company_name']
        assert not t.supplier_set.exists()
