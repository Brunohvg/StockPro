"""Patch 5: importação de NF-e de entrada (Beta)."""
import io
import zipfile
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.accounts.models import TenantMembership
from apps.core.services import StockService
from apps.inventory.models import NfeDocument, NfeSettings, StockLot, StockMovement
from apps.inventory.services import nfe as svc
from apps.partners.models import Supplier, SupplierProductMap
from apps.products.models import Product, ProductVariant
from tests.factories import TenantFactory, UserFactory

TENANT_CNPJ = '11222333000181'
SUPPLIER_CNPJ = '11444777000161'
KEY = '35' + '2610' + SUPPLIER_CNPJ + '55' + '001' + '000001234' + '1' + '12345678' + '9'


def _item(n, code, ean, desc, unit, qty, vun, vprod, extra='', imposto='', rastro=''):
    return f"""
      <det nItem="{n}">
        <prod>
          <cProd>{code}</cProd><cEAN>{ean}</cEAN><xProd>{desc}</xProd><NCM>96081000</NCM><CFOP>5102</CFOP>
          <uCom>{unit}</uCom><qCom>{qty}</qCom><vUnCom>{vun}</vUnCom><vProd>{vprod}</vProd>
          <cEANTrib>{ean}</cEANTrib><uTrib>{unit}</uTrib><qTrib>{qty}</qTrib><vUnTrib>{vun}</vUnTrib>
          {extra}{rastro}
        </prod>
        <imposto>{imposto}</imposto>
      </det>"""


def make_xml(items, key=KEY, dest=TENANT_CNPJ, emit=SUPPLIER_CNPJ, protocol=True, model='55'):
    prot = f"""<protNFe versao="4.00"><infProt><chNFe>{key}</chNFe><cStat>100</cStat></infProt></protNFe>""" if protocol else ''
    body = f"""<NFe xmlns="http://www.portalfiscal.inf.br/nfe"><infNFe Id="NFe{key}" versao="4.00">
      <ide><mod>{model}</mod><serie>1</serie><nNF>1234</nNF><dhEmi>2026-10-01T10:00:00-03:00</dhEmi><tpNF>1</tpNF></ide>
      <emit><CNPJ>{emit}</CNPJ><xNome>DISTRIBUIDORA TESTE LTDA</xNome><xFant>Distrib Teste</xFant><IE>123</IE>
        <enderEmit><xLgr>Rua A</xLgr><nro>1</nro><xMun>Sao Paulo</xMun><UF>SP</UF></enderEmit></emit>
      <dest><CNPJ>{dest}</CNPJ><xNome>BIBELO</xNome></dest>
      {''.join(items)}
      <total><ICMSTot><vProd>100.00</vProd><vNF>120.00</vNF></ICMSTot></total>
    </infNFe></NFe>"""
    if protocol:
        return f"""<?xml version="1.0" encoding="UTF-8"?><nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">{body}{prot}</nfeProc>""".encode()
    return f"""<?xml version="1.0" encoding="UTF-8"?>{body}""".encode()


CANETA = _item(1, 'F-100', '7891234567895', 'CANETA AZUL CX C/12', 'CX', '2.0000', '24.00', '48.00',
               extra='<vFrete>4.00</vFrete><vDesc>2.00</vDesc>',
               imposto='<ICMS><ICMS10><vICMSST>3.00</vICMSST></ICMS10></ICMS><IPI><IPITrib><vIPI>1.00</vIPI></IPITrib></IPI>')
LEITE = _item(2, 'F-200', 'SEM GTIN', 'LEITE CONDENSADO 395G', 'UN', '10', '5.20', '52.00',
              rastro='<rastro><nLote>L77</nLote><qLote>6</qLote><dFab>2026-09-01</dFab><dVal>2027-03-01</dVal></rastro>'
                     '<rastro><nLote>L78</nLote><qLote>4</qLote><dVal>2027-05-01</dVal></rastro>')


def _member(role='OWNER', cnpj=TENANT_CNPJ, **plan):
    tenant = TenantFactory(cnpj=cnpj, **{f'plan__{k}': v for k, v in plan.items()})
    u = UserFactory()
    TenantMembership.objects.create(user=u, tenant=tenant, role=role)
    return u, tenant


def _client(u):
    c = Client()
    c.force_login(u)
    return c


def _upload(c, content, name='nota.xml'):
    return c.post('/inventory/nfe/upload/', {'files': SimpleUploadedFile(name, content, 'text/xml')})


@pytest.mark.django_db
class TestLeitura:
    def test_le_itens_impostos_e_lotes(self):
        data = svc.parse_nfe_xml(make_xml([CANETA, LEITE]))
        assert data.access_key == KEY and data.authorized and data.number == '1234'
        caneta, leite = data.items
        assert caneta.ean == '7891234567895' and caneta.ipi == Decimal('1.00') and caneta.icms_st == Decimal('3.00')
        assert caneta.freight == Decimal('4.00') and caneta.discount == Decimal('2.00')
        assert leite.ean == '' and len(leite.lots) == 2 and leite.lots[0]['expiry'] == '2027-03-01'

    def test_xml_sem_namespace_e_sem_protocolo(self):
        xml = make_xml([CANETA], protocol=False).replace(b' xmlns="http://www.portalfiscal.inf.br/nfe"', b'')
        data = svc.parse_nfe_xml(xml)
        assert not data.authorized and len(data.items) == 1

    @pytest.mark.parametrize('payload', [
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><x>&e;</x>',
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><l>&b;</l>',
        b'nao e xml',
        b'<outro/>',
    ])
    def test_rejeita_xml_malicioso_ou_invalido(self, payload):
        with pytest.raises(svc.NfeError):
            svc.parse_nfe_xml(payload)

    def test_sugere_fator_de_caixa(self):
        assert svc.suggest_factor('CX', 'CANETA AZUL CX C/12') == 12
        assert svc.suggest_factor('DZ', 'OVOS') == 12
        assert svc.suggest_factor('UN', 'CANETA C/12') is None


@pytest.mark.django_db
class TestFluxo:
    def test_previa_nao_mexe_no_estoque_e_confirmacao_da_entrada(self):
        u, t = _member()
        p = Product.objects.create(tenant=t, name='Caneta Azul', sku='CAN-AZ', barcode='7891234567895')
        p.variants.update(barcode='7891234567895')
        c = _client(u)
        r = _upload(c, make_xml([CANETA, LEITE]))
        doc = NfeDocument.objects.get(tenant=t)
        assert r.status_code == 302 and r.url.endswith(f'/inventory/nfe/{doc.pk}/')
        assert StockMovement.objects.filter(tenant=t).count() == 0
        caneta, leite = doc.items.order_by('item_number')
        assert caneta.decision == 'LINK' and caneta.match_source == 'EAN'
        assert caneta.conversion_factor == 12 and caneta.factor_suggested
        assert leite.decision == 'PENDING'
        page = c.get(f'/inventory/nfe/{doc.pk}/').content.decode()
        assert 'Beta' in page and 'nada entrou no estoque' in page

        c.post(f'/inventory/nfe/{doc.pk}/', {
            'action': 'import',
            f'item-{leite.pk}-decision': 'CREATE', f'item-{leite.pk}-name': 'Leite Condensado 395g',
            f'item-{caneta.pk}-decision': 'LINK', f'item-{caneta.pk}-factor': '12',
        })
        doc.refresh_from_db()
        assert doc.status == 'IMPORTED'
        v = p.variants.first()
        assert v.current_stock == 24  # 2 caixas x 12
        # custo: 48 + IPI 1 + ST 3 + frete 4 - desconto 2 = 54 / 24 un
        assert StockMovement.objects.get(variant=v).unit_cost == Decimal('2.2500')
        novo = Product.objects.get(tenant=t, name='Leite Condensado 395g')
        assert novo.tracks_expiry and novo.variants.first().current_stock == 10
        lots = {l.lot_number: l.quantity for l in StockLot.objects.filter(variant__product=novo)}
        assert lots == {'L77': 6, 'L78': 4}
        sup = Supplier.objects.get(tenant=t, cnpj=SUPPLIER_CNPJ)
        mapa = SupplierProductMap.objects.get(supplier=sup, supplier_sku='F-100')
        assert mapa.variant == v and mapa.conversion_factor == 12

    def test_proxima_nota_ja_vem_vinculada_pelo_codigo_aprendido(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([LEITE]))
        doc = NfeDocument.objects.get(tenant=t)
        item = doc.items.get()
        c.post(f'/inventory/nfe/{doc.pk}/', {'action': 'import', f'item-{item.pk}-decision': 'CREATE',
                                              f'item-{item.pk}-factor': '1'})
        key2 = KEY[:-10] + '9999999990'
        _upload(c, make_xml([LEITE], key=key2))
        doc2 = NfeDocument.objects.get(tenant=t, access_key=key2)
        it2 = doc2.items.get()
        assert it2.decision == 'LINK' and it2.match_source == 'SUPPLIER_MAP'

    def test_nota_duplicada_e_recusada(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([CANETA]))
        r = _upload(c, make_xml([CANETA]))
        assert NfeDocument.objects.filter(tenant=t).count() == 1
        assert r.status_code == 302

    def test_destinatario_diferente_exige_confirmacao(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([CANETA], dest='99888777000166'))
        doc = NfeDocument.objects.get(tenant=t)
        item = doc.items.get()
        post = {'action': 'import', f'item-{item.pk}-decision': 'CREATE', f'item-{item.pk}-name': 'Caneta'}
        c.post(f'/inventory/nfe/{doc.pk}/', post)
        doc.refresh_from_db()
        assert doc.status == 'PREVIEW'
        c.post(f'/inventory/nfe/{doc.pk}/', dict(post, confirm_recipient='on'))
        doc.refresh_from_db()
        assert doc.status == 'IMPORTED'

    def test_nota_da_propria_empresa_e_bloqueada(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([CANETA], emit=TENANT_CNPJ, dest='99888777000166'))
        doc = NfeDocument.objects.get(tenant=t)
        assert doc.blocking_warnings
        with pytest.raises(svc.NfeError):
            svc.import_document(doc, u, confirm_recipient=True)

    def test_item_pendente_impede_importacao(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([LEITE]))
        doc = NfeDocument.objects.get(tenant=t)
        c.post(f'/inventory/nfe/{doc.pk}/', {'action': 'import'})
        doc.refresh_from_db()
        assert doc.status == 'PREVIEW' and not StockMovement.objects.exists()

    def test_falha_no_meio_nao_grava_nada(self):
        u, t = _member()
        arquivado = Product.objects.create(tenant=t, name='Velho', sku='VEL')
        StockService.create_movement(t, u, 'IN', 1, product=arquivado)
        c = _client(u)
        _upload(c, make_xml([LEITE, CANETA]))
        doc = NfeDocument.objects.get(tenant=t)
        leite, caneta = doc.items.order_by('item_number')
        leite.decision, caneta.decision = 'CREATE', 'LINK'
        leite.save()
        caneta.variant = arquivado.variants.first()
        caneta.save()
        Product.objects.filter(pk=arquivado.pk).update(is_active=False)  # arquivado depois da revisão
        with pytest.raises(svc.NfeError):
            svc.import_document(doc, u)
        assert not Product.objects.filter(tenant=t, name__icontains='leite').exists()
        assert StockMovement.objects.filter(tenant=t).count() == 1

    def test_limite_do_plano(self):
        u, t = _member(max_products=1)
        c = _client(u)
        _upload(c, make_xml([CANETA, LEITE]))
        doc = NfeDocument.objects.get(tenant=t)
        for item in doc.items.all():
            item.decision, item.new_product_name = 'CREATE', item.description
            item.save()
        with pytest.raises(svc.NfeError, match='plano'):
            svc.import_document(doc, u)
        assert not Product.objects.filter(tenant=t).exists()

    def test_desfazer_lanca_estorno(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([LEITE]))
        doc = NfeDocument.objects.get(tenant=t)
        item = doc.items.get()
        c.post(f'/inventory/nfe/{doc.pk}/', {'action': 'import', f'item-{item.pk}-decision': 'CREATE'})
        produto = Product.objects.get(tenant=t)
        c.post(f'/inventory/nfe/{doc.pk}/revert/')
        doc.refresh_from_db()
        assert doc.status == 'REVERTED'
        assert produto.variants.first().current_stock == 0
        tipos = sorted(StockMovement.objects.filter(variant__product=produto).values_list('type', flat=True))
        assert tipos == ['IN', 'IN', 'OUT', 'OUT']  # nada apagado
        # nota desfeita pode ser enviada de novo
        _upload(c, make_xml([LEITE]))
        assert NfeDocument.objects.filter(tenant=t, status='PREVIEW').count() == 1

    def test_desfazer_sem_saldo_falha_sem_gravar(self):
        u, t = _member()
        c = _client(u)
        _upload(c, make_xml([CANETA]))
        doc = NfeDocument.objects.get(tenant=t)
        item = doc.items.get()
        c.post(f'/inventory/nfe/{doc.pk}/', {'action': 'import', f'item-{item.pk}-decision': 'CREATE',
                                              f'item-{item.pk}-factor': '1'})
        v = ProductVariant.objects.get(tenant=t)
        StockService.create_movement(t, u, 'OUT', 1, variant=v)
        with pytest.raises(svc.NfeError):
            svc.revert_document(doc, u)
        doc.refresh_from_db()
        assert doc.status == 'IMPORTED' and ProductVariant.objects.get(pk=v.pk).current_stock == 1

    def test_configuracao_da_empresa_muda_custo_e_politica(self):
        u, t = _member()
        cfg = NfeSettings.for_tenant(t)
        c = _client(u)
        r = c.post('/inventory/nfe/settings/', {
            'new_product_policy': 'AUTO_CREATE', 'sku_policy': 'SUPPLIER_CODE',
            'match_supplier_code': 'on', 'match_ean': 'on', 'cost_include_ipi': 'on',
        })
        assert r.status_code == 302
        cfg.refresh_from_db()
        assert not cfg.cost_include_st and cfg.new_product_policy == 'AUTO_CREATE'
        _upload(c, make_xml([CANETA]))
        doc = NfeDocument.objects.get(tenant=t)
        item = doc.items.get()
        assert item.decision == 'CREATE'
        c.post(f'/inventory/nfe/{doc.pk}/', {'action': 'import', f'item-{item.pk}-factor': '1'})
        v = ProductVariant.objects.get(tenant=t)
        assert v.sku == 'F-100'
        assert StockMovement.objects.get(variant=v).unit_cost == Decimal('24.5000')  # (48 + IPI 1) / 2

    def test_zip_com_varias_notas(self):
        u, t = _member()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr('a.xml', make_xml([CANETA]))
            zf.writestr('b.xml', make_xml([LEITE], key=KEY[:-10] + '8888888880'))
            zf.writestr('leia.txt', 'ignorar')
        _upload(_client(u), buf.getvalue(), name='notas.zip')
        assert NfeDocument.objects.filter(tenant=t).count() == 2

    def test_operador_nao_acessa_e_outra_empresa_nao_ve(self):
        u, t = _member()
        _upload(_client(u), make_xml([CANETA]))
        doc = NfeDocument.objects.get(tenant=t)
        op = UserFactory()
        TenantMembership.objects.create(user=op, tenant=t, role='OPERATOR')
        assert _client(op).get('/inventory/nfe/').status_code == 302
        outro, _ = _member(cnpj='22333444000181')
        assert _client(outro).get(f'/inventory/nfe/{doc.pk}/').status_code == 404
        assert _client(outro).get(f'/inventory/nfe/{doc.pk}/xml/').status_code == 404

