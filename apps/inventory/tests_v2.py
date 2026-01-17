"""
StockPro V2 - Test Suite

Testes unitários para:
- Modelos V2 (Location, AdjustmentReason, PendingAssociation)
- Supplier e SupplierProductMap
- NfeImportService (deduplicação)

Executar: python manage.py test apps.inventory.tests_v2 -v 2
"""
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User

from apps.tenants.models import Tenant, Plan


class BaseTestCase(TestCase):
    """Caso base com fixtures comuns."""
    
    @classmethod
    def setUpTestData(cls):
        cls.plan = Plan.objects.create(
            name='FREE',
            display_name='Gratuito',
            max_products=100,
            max_users=5
        )
        
        cls.tenant = Tenant.objects.create(
            name='Empresa Teste',
            slug='empresa-teste',
            plan=cls.plan
        )
        
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123'
        )


# =============================================================================
# TESTS: LOCATION MODEL
# =============================================================================

class LocationModelTests(BaseTestCase):
    """Testes do modelo Location."""
    
    def test_create_location(self):
        """Deve criar localização corretamente."""
        from apps.inventory.models_v2 import Location, LocationType
        
        location = Location.objects.create(
            tenant=self.tenant,
            code='DEP-001',
            name='Depósito Central',
            location_type=LocationType.WAREHOUSE
        )
        
        self.assertEqual(location.code, 'DEP-001')
        self.assertEqual(location.name, 'Depósito Central')
        self.assertTrue(location.is_active)
    
    def test_unique_code_per_tenant(self):
        """Código deve ser único por tenant."""
        from apps.inventory.models_v2 import Location
        from django.db import IntegrityError
        
        Location.objects.create(
            tenant=self.tenant,
            code='LOJ-001',
            name='Loja 1'
        )
        
        with self.assertRaises(IntegrityError):
            Location.objects.create(
                tenant=self.tenant,
                code='LOJ-001',
                name='Loja 2'
            )
    
    def test_only_one_default_per_tenant(self):
        """Deve ter apenas um local padrão por tenant."""
        from apps.inventory.models_v2 import Location
        
        loc1 = Location.objects.create(
            tenant=self.tenant,
            code='LOC-1',
            name='Local 1',
            is_default=True
        )
        
        loc2 = Location.objects.create(
            tenant=self.tenant,
            code='LOC-2',
            name='Local 2',
            is_default=True
        )
        
        loc1.refresh_from_db()
        
        self.assertFalse(loc1.is_default)
        self.assertTrue(loc2.is_default)
    
    def test_hierarchical_location(self):
        """Deve suportar hierarquia de locais."""
        from apps.inventory.models_v2 import Location, LocationType
        
        warehouse = Location.objects.create(
            tenant=self.tenant,
            code='DEP-001',
            name='Depósito',
            location_type=LocationType.WAREHOUSE
        )
        
        shelf = Location.objects.create(
            tenant=self.tenant,
            code='PRAT-A1',
            name='Prateleira A1',
            location_type=LocationType.SHELF,
            parent=warehouse
        )
        
        self.assertEqual(shelf.parent, warehouse)
        self.assertEqual(shelf.full_path, 'Depósito > Prateleira A1')
    
    def test_ensure_default_exists(self):
        """Deve criar local padrão se não existir."""
        from apps.inventory.models_v2 import Location
        
        Location.objects.filter(tenant=self.tenant).delete()
        
        location = Location.ensure_default_exists(self.tenant)
        
        self.assertIsNotNone(location)
        self.assertTrue(location.is_default)
        self.assertEqual(location.code, 'PRINCIPAL')


# =============================================================================
# TESTS: SUPPLIER MODEL
# =============================================================================

class SupplierModelTests(BaseTestCase):
    """Testes do modelo Supplier."""
    
    def test_create_supplier(self):
        """Deve criar fornecedor corretamente."""
        from apps.partners.models import Supplier
        
        supplier = Supplier.objects.create(
            tenant=self.tenant,
            cnpj='12345678000199',
            company_name='Fornecedor LTDA',
            trade_name='Fornecedor'
        )
        
        self.assertEqual(supplier.cnpj, '12345678000199')
        self.assertEqual(supplier.company_name, 'Fornecedor LTDA')
        self.assertEqual(supplier.formatted_cnpj, '12.345.678/0001-99')
    
    def test_get_or_create_from_nfe(self):
        """Deve criar fornecedor a partir de dados da NF-e."""
        from apps.partners.models import Supplier
        
        supplier, created = Supplier.get_or_create_from_nfe(
            tenant=self.tenant,
            cnpj='55.782.486/0001-59',
            company_name='GITEX GASPARINI INDUSTRIA TEXTIL LTDA',
            state_registration='165077300116'
        )
        
        self.assertTrue(created)
        self.assertEqual(supplier.cnpj, '55782486000159')


# =============================================================================
# TESTS: ADJUSTMENT REASON MODEL
# =============================================================================

class AdjustmentReasonTests(BaseTestCase):
    """Testes do modelo AdjustmentReason."""
    
    def test_seed_defaults(self):
        """Deve criar motivos padrão."""
        from apps.inventory.models_v2 import AdjustmentReason
        
        created = AdjustmentReason.seed_defaults(self.tenant)
        
        self.assertGreater(len(created), 0)
        
        furto = AdjustmentReason.objects.filter(
            tenant=self.tenant,
            code='FURTO'
        ).first()
        
        self.assertIsNotNone(furto)
        self.assertEqual(furto.impact_type, 'LOSS')
        self.assertTrue(furto.requires_note)


# =============================================================================
# TESTS: NFE IMPORT SERVICE
# =============================================================================

class NfeImportServiceTests(BaseTestCase):
    """Testes do NfeImportService."""
    
    def setUp(self):
        from apps.products.models import Product, Category, Brand, ProductType
        
        self.category = Category.objects.create(
            tenant=self.tenant,
            name='Geral'
        )
        self.brand = Brand.objects.create(
            tenant=self.tenant,
            name='Sem Marca'
        )
        
        self.product_with_ean = Product.objects.create(
            tenant=self.tenant,
            sku='PROD-001',
            name='Produto Com EAN',
            barcode='7893791143468',
            product_type=ProductType.SIMPLE,
            category=self.category,
            brand=self.brand,
            current_stock=0
        )
    
    def test_parse_nfe_xml(self):
        """Deve fazer parse do XML corretamente."""
        from apps.partners.services import NfeParser
        
        xml_content = self._get_sample_xml()
        parser = NfeParser(xml_content)
        nfe_data = parser.parse()
        
        self.assertEqual(nfe_data.nfe_number, '97964')
        self.assertEqual(nfe_data.supplier_cnpj_clean, '55782486000159')
        self.assertGreater(len(nfe_data.items), 0)
    
    def test_match_by_ean_gold(self):
        """Deve encontrar produto pelo EAN (match ouro)."""
        from apps.partners.models import Supplier
        from apps.partners.services import ProductMatcher, MatchLevel, NfeItem
        
        supplier = Supplier.objects.create(
            tenant=self.tenant,
            cnpj='55782486000159',
            company_name='Fornecedor Teste'
        )
        
        matcher = ProductMatcher(self.tenant, supplier)
        
        item = NfeItem(
            item_number=1,
            supplier_sku='27440007',
            ean='7893791143468',
            description='Produto Teste',
            ncm='12345678',
            cfop='6101',
            unit='UN',
            quantity=Decimal('10'),
            unit_cost=Decimal('15.00'),
            total_cost=Decimal('150.00')
        )
        
        result = matcher.match(item)
        
        self.assertEqual(result.level, MatchLevel.GOLD)
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.product, self.product_with_ean)
    
    def test_pending_association_fallback(self):
        """Deve criar pendência quando não encontrar match."""
        from apps.partners.models import Supplier
        from apps.partners.services import ProductMatcher, MatchLevel, NfeItem
        
        supplier = Supplier.objects.create(
            tenant=self.tenant,
            cnpj='55782486000159',
            company_name='Fornecedor Teste'
        )
        
        matcher = ProductMatcher(self.tenant, supplier)
        
        item = NfeItem(
            item_number=1,
            supplier_sku='CODIGO-DESCONHECIDO',
            ean='',
            description='Produto Desconhecido',
            ncm='12345678',
            cfop='6101',
            unit='UN',
            quantity=Decimal('10'),
            unit_cost=Decimal('15.00'),
            total_cost=Decimal('150.00')
        )
        
        result = matcher.match(item)
        
        self.assertEqual(result.level, MatchLevel.NONE)
        self.assertIsNone(result.product)
    
    def test_never_create_duplicate(self):
        """Nunca deve criar produto duplicado automaticamente."""
        from apps.partners.services import NfeImportService
        from apps.inventory.models_v2 import PendingAssociation
        from apps.products.models import Product
        
        xml_content = self._get_sample_xml()
        
        # Remove produto para forçar pendência
        self.product_with_ean.delete()
        
        service = NfeImportService(self.tenant, self.user)
        result = service.import_from_bytes(xml_content)
        
        # Deve criar pendência, não produto
        self.assertGreater(result.pending_items, 0)
        
        # Verifica que não criou produto
        products_after = Product.objects.filter(tenant=self.tenant).count()
        self.assertEqual(products_after, 0)
        
        # Verifica que criou pendência
        pending = PendingAssociation.objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(pending)
        self.assertEqual(pending.status, 'PENDING')
    
    def test_import_creates_supplier(self):
        """Deve criar fornecedor automaticamente."""
        from apps.partners.models import Supplier
        from apps.partners.services import NfeImportService
        
        Supplier.objects.filter(tenant=self.tenant).delete()
        
        xml_content = self._get_sample_xml()
        
        service = NfeImportService(self.tenant, self.user)
        result = service.import_from_bytes(xml_content)
        
        supplier = Supplier.objects.filter(
            tenant=self.tenant,
            cnpj='55782486000159'
        ).first()
        
        self.assertIsNotNone(supplier)
        self.assertIn('GITEX', supplier.company_name)
    
    def _get_sample_xml(self) -> bytes:
        """Retorna XML de NF-e de exemplo."""
        return b'''<?xml version="1.0" encoding="UTF-8"?>
<nfeProc versao="4.00" xmlns="http://www.portalfiscal.inf.br/nfe">
<NFe xmlns="http://www.portalfiscal.inf.br/nfe">
<infNFe versao="4.00" Id="NFe35260155782486000159550010000979641238309566">
<ide>
<nNF>97964</nNF>
<serie>1</serie>
<dhEmi>2026-01-15T15:14:02-02:00</dhEmi>
</ide>
<emit>
<CNPJ>55782486000159</CNPJ>
<xNome>GITEX GASPARINI INDUSTRIA TEXTIL LTDA</xNome>
<xFant>GITEX</xFant>
<enderEmit>
<xLgr>RUA DIONISIO RODRIGUES DA SILVA</xLgr>
<nro>967</nro>
<xMun>AMERICANA</xMun>
<UF>SP</UF>
</enderEmit>
<IE>165077300116</IE>
</emit>
<det nItem="1">
<prod>
<cProd>27440007</cProd>
<cEAN>7893791143468</cEAN>
<xProd>VOIL CETIM BORDA 107 - VERMELHO</xProd>
<NCM>58063200</NCM>
<CFOP>6101</CFOP>
<uCom>RL</uCom>
<qCom>128.0000</qCom>
<vUnCom>7.8800000000</vUnCom>
<vProd>1008.64</vProd>
</prod>
</det>
</infNFe>
</NFe>
</nfeProc>'''


# =============================================================================
# TESTS: SUPPLIER PRODUCT MAP
# =============================================================================

class SupplierProductMapTests(BaseTestCase):
    """Testes do modelo SupplierProductMap."""
    
    def setUp(self):
        from apps.partners.models import Supplier
        from apps.products.models import Product, Category, Brand, ProductType
        
        self.supplier = Supplier.objects.create(
            tenant=self.tenant,
            cnpj='12345678000199',
            company_name='Fornecedor Teste'
        )
        
        category = Category.objects.create(tenant=self.tenant, name='Geral')
        brand = Brand.objects.create(tenant=self.tenant, name='Marca')
        
        self.product = Product.objects.create(
            tenant=self.tenant,
            sku='PROD-001',
            name='Produto Teste',
            product_type=ProductType.SIMPLE,
            category=category,
            brand=brand
        )
    
    def test_create_mapping(self):
        """Deve criar mapeamento corretamente."""
        from apps.partners.models import SupplierProductMap
        
        mapping = SupplierProductMap.objects.create(
            tenant=self.tenant,
            supplier=self.supplier,
            product=self.product,
            supplier_sku='COD-FORN-001',
            supplier_name='Produto no Fornecedor'
        )
        
        self.assertEqual(mapping.supplier_sku, 'COD-FORN-001')
        self.assertEqual(mapping.product, self.product)
    
    def test_update_purchase_info(self):
        """Deve atualizar informações de compra."""
        from apps.partners.models import SupplierProductMap
        
        mapping = SupplierProductMap.objects.create(
            tenant=self.tenant,
            supplier=self.supplier,
            product=self.product,
            supplier_sku='COD-001',
            total_purchased=0
        )
        
        mapping.update_purchase_info(
            cost=Decimal('15.50'),
            quantity=100
        )
        
        mapping.refresh_from_db()
        
        self.assertEqual(mapping.last_cost, Decimal('15.50'))
        self.assertEqual(mapping.total_purchased, 100)
    
    def test_find_mapping(self):
        """Deve encontrar mapeamento existente."""
        from apps.partners.models import SupplierProductMap
        
        SupplierProductMap.objects.create(
            tenant=self.tenant,
            supplier=self.supplier,
            product=self.product,
            supplier_sku='COD-BUSCA'
        )
        
        found = SupplierProductMap.find_mapping(
            tenant=self.tenant,
            supplier=self.supplier,
            supplier_sku='COD-BUSCA'
        )
        
        self.assertIsNotNone(found)
        self.assertEqual(found.product, self.product)
