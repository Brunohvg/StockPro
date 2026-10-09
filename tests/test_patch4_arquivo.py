"""Patch 4.1: produto com histórico é arquivado, nunca apagado; consolidação preserva estoque."""
import pytest
from django.test import Client
from rest_framework.test import APIClient

from apps.accounts.models import TenantMembership
from apps.core.services import StockService
from apps.inventory.models import StockLot, StockMovement
from apps.products.models import Product, ProductVariant
from apps.products.services import ArchiveError, ConsolidationService, ProductArchiveService
from tests.factories import TenantFactory, UserFactory

PWD = 'Senha!Forte123'


def _member(role='OWNER', tenant=None, **plan):
    tenant = tenant or TenantFactory(**{f'plan__{k}': v for k, v in plan.items()})
    u = UserFactory(password=PWD)
    TenantMembership.objects.create(user=u, tenant=tenant, role=role)
    return u, tenant


def _client(u):
    c = Client()
    c.force_login(u)
    return c


def _stock(p):
    return p.variants.first().current_stock


@pytest.mark.django_db
class TestArquivar:
    def test_produto_sem_movimentacao_e_excluido(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Erro de cadastro', sku='ERR-1')
        r = _client(u).post(f'/products/{p.pk}/delete/')
        assert r.status_code == 302
        assert not Product.objects.filter(pk=p.pk).exists()

    def test_produto_com_historico_e_arquivado_e_saldo_zerado(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        StockService.create_movement(t, u, 'IN', 10, product=p, unit_cost=2)
        StockService.create_movement(t, u, 'OUT', 3, product=p)
        _client(u).post(f'/products/{p.pk}/delete/')
        p.refresh_from_db()
        assert p.is_active is False
        assert p.variants.first().is_active is False
        assert _stock(p) == 0
        movs = list(StockMovement.objects.filter(product=p).order_by('created_at'))
        assert [m.type for m in movs] == ['IN', 'OUT', 'ADJ']  # nada apagado
        assert movs[-1].source == 'ARCHIVE'

    def test_arquivar_sem_zerar_mantem_saldo(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        StockService.create_movement(t, u, 'IN', 4, product=p)
        _client(u).post(f'/products/{p.pk}/delete/', {'zero_stock': 'off'})
        p.refresh_from_db()
        assert p.is_active is False and _stock(p) == 4
        assert StockMovement.objects.filter(product=p).count() == 1

    def test_arquivar_zera_lotes(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Leite', sku='LEI-1')
        StockService.create_movement(t, u, 'IN', 6, product=p, lot_number='L1', expiry_date='31/12/2099')
        ProductArchiveService.remove_product(p, u)
        assert StockLot.objects.get(lot_number='L1').quantity == 0

    def test_arquivado_nao_aceita_movimentacao(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        StockService.create_movement(t, u, 'IN', 1, product=p)
        ProductArchiveService.remove_product(p, u)
        with pytest.raises(ValueError, match='arquivado'):
            StockService.create_movement(t, u, 'IN', 1, product=p)

    def test_arquivado_some_da_lista_e_das_buscas(self):
        u, t = _member()
        ativo = Product.objects.create(tenant=t, name='Caneta azul', sku='CAN-A')
        velho = Product.objects.create(tenant=t, name='Caneta velha', sku='CAN-V')
        StockService.create_movement(t, u, 'IN', 1, product=velho)
        ProductArchiveService.remove_product(velho, u)
        c = _client(u)
        html = c.get('/products/').content.decode()
        assert 'Caneta azul' in html and 'Caneta velha' not in html
        assert 'Caneta velha' in c.get('/products/?status=archived').content.decode()
        busca = c.get('/inventory/api/products/search/?q=Caneta').json()
        assert [r['sku'] for r in busca['results']] == ['CAN-A']
        assert ativo.pk

    def test_reativar_respeita_limite_do_plano(self):
        u, t = _member(max_products=1)
        p = Product.objects.create(tenant=t, name='Velho', sku='V-1')
        StockService.create_movement(t, u, 'IN', 1, product=p)
        ProductArchiveService.remove_product(p, u)
        assert t.products_count == 0  # arquivado não conta no limite
        Product.objects.create(tenant=t, name='Novo', sku='N-1')
        with pytest.raises(ArchiveError):
            ProductArchiveService.restore_product(p)
        Product.objects.get(sku='N-1').delete()
        _client(u).post(f'/products/{p.pk}/restore/')
        p.refresh_from_db()
        assert p.is_active and p.variants.first().is_active

    def test_operador_nao_arquiva(self):
        dono, t = _member()
        op, _ = _member('OPERATOR', t)
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        _client(op).post(f'/products/{p.pk}/delete/')
        assert Product.objects.get(pk=p.pk).is_active

    def test_variacao_com_historico_e_arquivada(self):
        u, t = _member()
        pai = Product.objects.create(tenant=t, name='Camiseta', sku='CAM', product_type='VARIABLE')
        v = ProductVariant.objects.create(tenant=t, product=pai, sku='CAM-P', name='P')
        StockService.create_movement(t, u, 'IN', 2, variant=v)
        _client(u).post(f'/products/variants/{v.pk}/delete/')
        v.refresh_from_db()
        assert v.is_active is False and v.current_stock == 0
        assert StockMovement.objects.filter(variant=v).count() == 2

    def test_exclusao_em_massa_mista(self):
        u, t = _member()
        a = Product.objects.create(tenant=t, name='A', sku='A')
        b = Product.objects.create(tenant=t, name='B', sku='B')
        StockService.create_movement(t, u, 'IN', 1, product=b)
        _client(u).post('/products/bulk-delete/', {'product_ids': [a.pk, b.pk]})
        assert not Product.objects.filter(pk=a.pk).exists()
        assert Product.objects.get(pk=b.pk).is_active is False

    def test_api_delete_arquiva_e_lista_oculta(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        StockService.create_movement(t, u, 'IN', 1, product=p)
        api = APIClient()
        tok = api.post('/api/v1/auth/token/', {'username': u.username, 'password': PWD},
                       format='json').data['access']
        api.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        r = api.delete(f'/api/v1/products/{p.pk}/')
        assert r.status_code == 200 and r.data['status'] == 'archived'
        assert api.get('/api/v1/products/').data['count'] == 0
        assert api.get('/api/v1/products/?include_archived=1').data['count'] == 1

    def test_importacao_reativa_sku_arquivado(self):
        from django.core.files.base import ContentFile
        from apps.inventory.models import ImportBatch
        from apps.inventory.tasks import run_import
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Caneta', sku='CAN-1')
        StockService.create_movement(t, u, 'IN', 1, product=p)
        ProductArchiveService.remove_product(p, u)
        batch = ImportBatch.objects.create(tenant=t, user=u, type='CATALOG_DIRECT')
        batch.file.save('c.csv', ContentFile('nome;sku;estoque\nCaneta;CAN-1;5\n'.encode()))
        result = run_import(batch, dry_run=False)
        p.refresh_from_db()
        assert p.is_active and _stock(p) == 5
        assert 'reativado' in result


@pytest.mark.django_db
def test_consolidacao_preserva_estoque_e_historico():
    u, t = _member()
    a = Product.objects.create(tenant=t, name='LINHA - COR AZUL', sku='LIN-AZ')
    b = Product.objects.create(tenant=t, name='LINHA - COR ROSA', sku='LIN-RS')
    StockService.create_movement(t, u, 'IN', 7, product=a, unit_cost=3)
    parent = ConsolidationService(t).consolidate('LINHA', 'Cor', [a.pk, b.pk])
    variants = {v.sku: v for v in parent.variants.all()}
    assert set(variants) == {'LIN-AZ', 'LIN-RS'}
    assert variants['LIN-AZ'].current_stock == 7
    assert StockMovement.objects.filter(variant=variants['LIN-AZ'], product=parent).count() == 1
    assert not Product.objects.filter(pk__in=[a.pk, b.pk]).exists()

