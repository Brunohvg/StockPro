"""Patch 9: etiquetas Zebra, tela Repor, pedido ao fornecedor, alerta de mínimo e resumo semanal."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail
from django.test import Client
from django.utils import timezone

from apps.accounts.models import TenantMembership
from apps.core.models import SystemSetting
from apps.core.services import StockService
from apps.inventory.models import StockMovement
from apps.inventory.services import replenishment as rep
from apps.inventory.services.stock_alerts import send_low_stock_alerts, send_weekly_summaries, weekly_summary
from apps.labels import barcodes as bc
from apps.labels import zpl
from apps.labels.layout import Barcode, LabelItem, Text, build_label, format_price, text_width
from apps.labels.models import LabelSettings
from apps.labels.preview import render_svg
from apps.partners.models import Supplier, SupplierProductMap
from apps.products.models import Product
from tests.factories import TenantFactory, UserFactory

PWD = 'Senha!Forte123'


def _member(role='OWNER', tenant=None):
    tenant = tenant or TenantFactory()
    u = UserFactory(password=PWD)
    TenantMembership.objects.create(user=u, tenant=tenant, role=role)
    return u, tenant


def _client(u):
    c = Client()
    c.force_login(u)
    return c


def _product(t, name='Caneta gel azul', sku='CAN-1', barcode='', price='12.90', minimum=0):
    p = Product.objects.create(tenant=t, name=name, sku=sku, barcode=barcode or None,
                               sale_price=Decimal(price) if price else None)
    v = p.variants.first()
    if barcode:
        v.barcode = barcode
    v.minimum_stock = Decimal(minimum)
    v.save()
    return p, v


def _decode_code128(modules):
    """Lê os módulos de volta para valores e confere o dígito verificador."""
    table = {''.join(('1' if i % 2 == 0 else '0') * int(w) for i, w in enumerate(pat)): val
             for val, pat in enumerate(bc._C128)}
    values, i = [], 0
    while i < len(modules) - 13:
        values.append(table[modules[i:i + 11]])
        i += 11
    assert modules[i:] == '1100011101011'  # stop
    check = values[0] + sum(pos * v for pos, v in enumerate(values[1:-1], start=1))
    assert check % 103 == values[-1]
    return values


class TestCodigos:
    def test_ean13_valido_e_invalido(self):
        assert bc.is_valid_ean13('7891234567895')
        assert not bc.is_valid_ean13('7891234567890')
        assert len(bc.ean13_modules('7891234567895')) == 95

    def test_ean8(self):
        assert bc.is_valid_ean8('96385074')
        assert len(bc.ean8_modules('96385074')) == 67

    @pytest.mark.parametrize('text', ['CAN-AZ-07', '123456', 'A1234567890B', '1234567', 'x_y'])
    def test_code128_decodifica_com_verificador(self, text):
        values = _decode_code128(bc.code128_modules(text))
        assert values[0] in (104, 105)

    def test_code128_usa_subconjunto_c_para_numeros(self):
        assert bc.code128_tokens('12345678') == [('C', '12345678')]
        assert bc.code128_zpl_data('A1234567890B') == '>:A>51234567890>6B'

    def test_escolha_do_codigo(self):
        assert bc.choose_code('7891234567895', 'SKU-1')['kind'] == 'EAN13'
        assert bc.choose_code('', 'SKU-1')['value'] == 'SKU-1'
        assert bc.choose_code('7891234567895', 'SKU-1', 'sku')['value'] == 'SKU-1'
        assert bc.choose_code('', 'Ação>1') is None  # acento e '>' não entram no Code 128


class TestLayoutEZpl:
    def _cfg(self, **kw):
        base = dict(width_mm=50, height_mm=30, columns=1, column_gap_mm=Decimal('0'), dpi=203, store_text='')
        base.update(kw)
        return LabelSettings(**base)

    def test_preco_brasileiro(self):
        assert format_price(Decimal('1249.5')) == 'R$ 1.249,50'
        assert format_price(None) == ''

    @pytest.mark.parametrize('w,h,dpi', [(40, 25, 203), (50, 30, 203), (60, 40, 300), (100, 50, 203), (33, 22, 203)])
    def test_tudo_cabe_na_etiqueta(self, w, h, dpi):
        cfg = self._cfg(width_mm=w, height_mm=h, dpi=dpi)
        item = LabelItem('Caderno universitário espiral 10 matérias capa dura', 'Floral / 200 folhas',
                         Decimal('1249.50'), 'CAD-TIL-10M', '7891234567895', 'Bibelô Papelaria')
        label = build_label(item, cfg)
        for el in label.elements:
            assert 0 <= el.x and el.x + el.width <= label.width if isinstance(el, Text) else True
            if isinstance(el, Text):
                assert el.y + el.size <= label.height
                assert text_width(el.text, el.size) <= el.width + 1
            if isinstance(el, Barcode):
                assert el.x >= 0 and el.x + el.module * len(el.modules) <= label.width
                assert el.y + el.height <= label.height
                assert el.height >= 4 * (12 if dpi >= 300 else 8) - 1

    def test_zpl_tem_comandos_e_escapa_caracteres(self):
        cfg = self._cfg()
        label = build_label(LabelItem('Papel_A4 ^ ~ especial', '', Decimal('5'), 'PAP-1', '7891234567895'), cfg)
        out = zpl.render_row([label], cfg, copies=3)
        assert out.startswith('^XA^CI28^PW400^LL240')
        # EAN-13 barra a barra (^GB), números no padrão: 7 | 891234 | 567895
        assert '^GB' in out and '^FD7^FS' in out and '^FD891234^FS' in out and '^FD567895^FS' in out
        assert '_5F' in out and '_5E' in out and '_7E' in out
        assert 'Papel_A4' not in out
        assert out.rstrip().endswith('^PQ3,0,1,Y^XZ')

    def test_job_agrupa_linhas_iguais(self):
        cfg = self._cfg()
        a = build_label(LabelItem('A', '', None, 'AAA', ''), cfg)
        b = build_label(LabelItem('B', '', None, 'BBB', ''), cfg)
        job = zpl.render_job([(1, a)] * 5 + [(2, b)] * 2, cfg)
        assert job.count('^XA') == 2
        assert '^PQ5,0,1,Y' in job and '^PQ2,0,1,Y' in job

    def test_tres_colunas_numa_linha(self):
        cfg = self._cfg(width_mm=33, height_mm=22, columns=3, column_gap_mm=Decimal('2'))
        labels = [build_label(LabelItem(f'P{i}', '', None, f'S{i}', ''), cfg) for i in range(4)]
        job = zpl.render_job([(i, lb) for i, lb in enumerate(labels)], cfg)
        assert job.count('^XA') == 2  # 3 + 1
        assert '^PW824' in job  # 3*264 + 2*16

    def test_ajustes_de_impressora(self):
        cfg = self._cfg(offset_x_mm=Decimal('1.5'), offset_y_mm=Decimal('-1'), darkness=3, print_speed=2)
        out = zpl.render_row([build_label(LabelItem('X', '', None, 'X1', ''), cfg)], cfg)
        assert '^LS-12' in out and '^LT-8' in out and '^MD3' in out and '^PR2' in out

    def test_svg_da_previa_escapa_texto(self):
        cfg = self._cfg()
        svg = render_svg([build_label(LabelItem('<script>x</script>', '', None, 'S1', ''), cfg)], cfg)
        assert '<script>' not in svg and '&lt;script&gt;' in svg


@pytest.mark.django_db
class TestTelasEtiquetas:
    def test_tela_abre_com_produto_e_operador_pode_imprimir(self):
        u, t = _member('OPERATOR')
        p, v = _product(t, barcode='7891234567895')
        c = _client(u)
        r = c.get(f'/etiquetas/?product={p.pk}')
        assert r.status_code == 200
        assert b'labels-initial' in r.content and b'7891234567895' in r.content
        r = c.post('/etiquetas/gerar/', {f'q_{v.pk}': '3', 'formato': 'zpl'})
        assert r.status_code == 200
        assert r['X-Label-Count'] == '3'
        assert '^PQ3' in r.content.decode()

    def test_busca_e_isolamento_entre_empresas(self):
        u, t = _member()
        _product(t, name='Caneta minha', sku='MINHA-1')
        _, outra = _member()
        _, v2 = _product(outra, name='Caneta de outro', sku='OUTRA-1')
        c = _client(u)
        names = [x['name'] for x in c.get('/etiquetas/buscar/?q=Caneta').json()['results']]
        assert names == ['Caneta minha']
        r = c.post('/etiquetas/gerar/', {f'q_{v2.pk}': '1'})
        assert r.status_code == 400

    def test_previa_svg(self):
        u, t = _member()
        _, v = _product(t)
        r = _client(u).get(f'/etiquetas/previa.svg?v={v.pk}')
        assert r.status_code == 200 and r['Content-Type'].startswith('image/svg+xml')
        assert b'Caneta gel azul' in r.content

    def test_html_para_imprimir_pelo_navegador(self):
        u, t = _member()
        _, v = _product(t)
        r = _client(u).post('/etiquetas/gerar/', {f'q_{v.pk}': '2', 'formato': 'html'})
        assert r.status_code == 200
        html = r.content.decode()
        assert '@page { size: 50.00mm 30mm' in html and html.count('class="page"') == 2

    def test_limite_de_etiquetas(self):
        u, t = _member()
        _, v = _product(t)
        r = _client(u).post('/etiquetas/gerar/', {f'q_{v.pk}': '2001'})
        assert r.status_code == 400

    def test_nfe_importada_vira_lista(self):
        from apps.inventory.models import NfeDocument, NfeItem
        u, t = _member()
        _, v = _product(t)
        doc = NfeDocument.objects.create(tenant=t, access_key='1' * 44, number='123', status='IMPORTED',
                                         xml_file='nfe/x.xml', imported_at=timezone.now())
        NfeItem.objects.create(document=doc, item_number=1, description='Caneta cx', quantity=Decimal('2'),
                               conversion_factor=Decimal('12'), decision='LINK', variant=v)
        data = _client(u).get(f'/etiquetas/nfe/{doc.pk}/').json()
        assert data['results'][0]['qty'] == 24
        r = _client(u).get(f'/etiquetas/?nfe={doc.pk}')
        assert b'NF-e 123' in r.content

    def test_modelo_so_admin_e_salva(self):
        u, t = _member('OPERATOR')
        assert _client(u).get('/etiquetas/modelo/').status_code == 302
        a, _ = _member('ADMIN', tenant=t)
        r = _client(a).post('/etiquetas/modelo/', {
            'width_mm': 40, 'height_mm': 25, 'columns': 1, 'column_gap_mm': 0, 'dpi': 203, 'darkness': 0,
            'print_speed': 0, 'offset_x_mm': 0, 'offset_y_mm': 0, 'show_price': 'on', 'show_barcode': 'on',
            'code_source': 'auto'})
        assert r.status_code == 302
        cfg = LabelSettings.objects.get(tenant=t)
        assert (cfg.width_mm, cfg.height_mm, cfg.show_sku) == (40, 25, False)

    def test_modelo_recusa_linha_larga_demais(self):
        a, t = _member('ADMIN')
        r = _client(a).post('/etiquetas/modelo/', {
            'width_mm': 60, 'height_mm': 25, 'columns': 2, 'column_gap_mm': 2, 'dpi': 203, 'darkness': 0,
            'print_speed': 0, 'offset_x_mm': 0, 'offset_y_mm': 0, 'code_source': 'auto'})
        assert r.status_code == 200 and '104 mm' in r.content.decode()

    def test_trial_vencido_ainda_imprime(self):
        u, t = _member()
        t.subscription_status = 'TRIAL'
        t.trial_ends_at = timezone.now() - timedelta(days=1)
        t.save()
        _, v = _product(t)
        r = _client(u).post('/etiquetas/gerar/', {f'q_{v.pk}': '1'})
        assert r.status_code == 200

    def test_atalhos_na_ficha_e_no_menu(self):
        u, t = _member()
        p, v = _product(t)
        html = _client(u).get(f'/products/{p.pk}/').content.decode()
        assert f'/etiquetas/?product={p.pk}' in html
        assert '/inventory/repor/' in html  # menu do admin


@pytest.mark.django_db
class TestReposicao:
    def _setup(self):
        u, t = _member()
        sup = Supplier.objects.create(tenant=t, cnpj='11222333000181', company_name='Distribuidora Papel LTDA', trade_name='Papel Sul',
                                      lead_time_days=10, minimum_order=Decimal('500'), phone='(11) 98888-7777',
                                      contact_name='Marta Souza')
        p, v = _product(t, name='Caneta gel azul', sku='CAN-1', minimum=10)
        p.default_supplier = sup
        p.save()
        StockService.create_movement(t, u, 'IN', 40, variant=v, unit_cost=2)
        StockService.create_movement(t, u, 'OUT', 33, variant=v)  # sobra 7, abaixo do mínimo 10
        SupplierProductMap.objects.create(tenant=t, supplier=sup, product=p, variant=v, supplier_sku='PS-778',
                                          last_cost=Decimal('2.50'), conversion_factor=Decimal('12'))
        return u, t, sup, v

    def test_sugestao_por_giro_e_caixa_fechada(self):
        u, t, sup, v = self._setup()
        lines = rep.build(t, window=30, coverage=30)
        assert len(lines) == 1
        ln = lines[0]
        assert ln.status == 'below'
        assert ln.per_day == Decimal('1.10')  # 33 em 30 dias
        # 1,1 × (10 + 30) = 44 − 7 = 37 → caixas de 12 → 48
        assert ln.suggested == 48
        assert ln.supplier_sku == 'PS-778' and ln.unit_cost == Decimal('2.50')

    def test_arquivamento_nao_conta_como_venda(self):
        u, t, sup, v = self._setup()
        StockMovement.objects.filter(variant=v, type='OUT').update(source='ARCHIVE')
        ln = rep.build(t, window=30)[0]
        assert ln.sold == 0

    def test_tela_repor_e_pedido(self):
        u, t, sup, v = self._setup()
        c = _client(u)
        r = c.get('/inventory/repor/')
        assert r.status_code == 200
        html = r.content.decode()
        assert 'Papel Sul' in html and f'name="qty_{v.pk}" value="48"' in html
        assert 'Abaixo do pedido mínimo' in html  # 48 × 2,50 = 120 < 500
        r = c.get(f'/inventory/repor/pedido/?fornecedor={sup.pk}&qty_{v.pk}=48')
        html = r.content.decode()
        assert 'PS-778' in html and 'R$ 120,00' in html
        assert 'https://wa.me/5511988887777?text=' in html
        assert 'faltam' in html
        r = c.get(f'/inventory/repor/pedido/?fornecedor={sup.pk}&qty_{v.pk}=48&formato=csv')
        body = r.content.decode('utf-8-sig')
        assert r['Content-Disposition'].startswith('attachment; filename="pedido-papel-sul-')
        assert 'PS-778;CAN-1' in body and ';48;' in body

    def test_pedido_rejeita_quantidades_invalidas(self):
        u, t, sup, v = self._setup()
        c = _client(u)
        for qty in ['NaN', 'Infinity', '-2', '100001', '1.1234']:
            r = c.get(f'/inventory/repor/pedido/?fornecedor={sup.pk}&qty_{v.pk}={qty}')
            assert r.status_code == 400

    def test_pedido_rejeita_fornecedor_incorreto(self):
        u, t, sup, v = self._setup()
        other = Supplier.objects.create(tenant=t, cnpj='99888777000100', company_name='Outro Fornecedor')
        r = _client(u).get(f'/inventory/repor/pedido/?fornecedor={other.pk}&qty_{v.pk}=5')
        assert r.status_code == 400

    def test_repor_so_admin_e_isolado(self):
        u, t, sup, v = self._setup()
        op, _ = _member('OPERATOR', tenant=t)
        assert _client(op).get('/inventory/repor/').status_code == 302
        outro, _ = _member()
        r = _client(outro).get(f'/inventory/repor/pedido/?qty_{v.pk}=5')
        assert 'Caneta gel azul' not in r.content.decode()


@pytest.mark.django_db
class TestEmails:
    def _cfg(self, t):
        cfg = SystemSetting.get_settings(t)
        cfg.alert_email = 'dono@bibelo.com.br'
        cfg.low_stock_alerts_enabled = True
        cfg.weekly_summary_enabled = True
        cfg.save()
        return cfg

    def test_alerta_minimo_so_avisa_novidade(self, settings):
        settings.SITE_URL = 'https://stock.optarys.com.br'
        u, t = _member()
        self._cfg(t)
        _, v = _product(t, minimum=5)  # saldo 0 <= 5
        assert send_low_stock_alerts() == 1
        assert 'chegaram ao estoque mínimo' in mail.outbox[0].subject
        html = mail.outbox[0].alternatives[0][0]
        assert 'Caneta gel azul' in html and 'https://stock.optarys.com.br/inventory/repor/' in html
        assert send_low_stock_alerts() == 0  # nada novo
        _product(t, name='Lápis', sku='LAP-1', minimum=2)
        assert send_low_stock_alerts() == 1
        assert 'Lápis' in mail.outbox[1].body and 'Caneta' not in mail.outbox[1].body

    def test_alerta_desligado(self):
        u, t = _member()
        cfg = self._cfg(t)
        cfg.low_stock_alerts_enabled = False
        cfg.save()
        _product(t, minimum=5)
        assert send_low_stock_alerts() == 0

    def test_resumo_semanal(self):
        u, t = _member()
        self._cfg(t)
        _, v = _product(t, minimum=5)
        StockService.create_movement(t, u, 'IN', 20, variant=v, unit_cost=2)
        StockService.create_movement(t, u, 'OUT', 18, variant=v)
        data = weekly_summary(t)
        assert data['out_qty'] == 18 and data['in_qty'] == 20 and data['in_value'] == 40
        assert data['top'][0]['qty'] == 18 and data['low_count'] == 1
        assert send_weekly_summaries() == 1
        assert 'Resumo da semana' in mail.outbox[0].subject

    def test_configuracoes_salvam_os_avisos(self):
        u, t = _member()
        r = _client(u).post('/settings/', {'company_name': 'Bibelô', 'expiry_alert_days': 30,
                                           'alert_email': 'dono@bibelo.com.br', 'weekly_summary_enabled': 'on'})
        assert r.status_code == 302
        cfg = SystemSetting.get_settings(t)
        assert cfg.weekly_summary_enabled is True and cfg.low_stock_alerts_enabled is False

    def test_tarefas_no_agendador(self, settings):
        from django.conf import settings as dj
        beat = getattr(dj, 'CELERY_BEAT_SCHEDULE', {})
        if beat:
            assert beat['daily-low-stock-alerts']['task'] == 'apps.tenants.tasks.send_low_stock_alerts'
            assert beat['weekly-owner-summary']['task'] == 'apps.tenants.tasks.send_weekly_summaries'
        from apps.tenants import tasks
        assert callable(tasks.send_low_stock_alerts) and callable(tasks.send_weekly_summaries)
