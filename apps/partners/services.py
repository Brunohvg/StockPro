"""
NFe Import Service - Intelligent NFe Import with Deduplication

Este módulo implementa a importação inteligente de Notas Fiscais Eletrônicas (NF-e)
com algoritmo de deduplicação em 4 níveis para evitar criação de produtos duplicados.

ALGORITMO DE DEDUPLICAÇÃO:
1. 🥇 OURO - Match por EAN Global (confiança 100%)
2. 🥈 PRATA - Match por SupplierProductMap (confiança 95%)
3. 🥉 BRONZE - Match por SKU Interno (confiança 70%)
4. ⚠️ FALLBACK - Associação Pendente (usuário decide)

Classes:
    NfeImportService: Serviço principal de importação
    NfeParser: Parser de XML de NF-e
    ProductMatcher: Algoritmo de deduplicação
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from apps.partners.models import SupplierProductMap
    from apps.products.models import Product, ProductVariant
    from apps.tenants.models import Tenant

from apps.inventory.services.matcher import ProductMatcher

# =============================================================================
# ENUMS E DATA CLASSES
# =============================================================================

class MatchLevel(Enum):
    """Níveis de confiança do match."""
    GOLD = 'GOLD'       # EAN match (100%)
    SILVER = 'SILVER'   # SupplierMap match (95%)
    BRONZE = 'BRONZE'   # SKU match (70%)
    NONE = 'NONE'       # Sem match


@dataclass
class NfeItem:
    """Item extraído da NF-e."""
    item_number: int           # nItem
    supplier_sku: str          # cProd
    ean: str                   # cEAN
    description: str           # xProd
    ncm: str                   # NCM
    cfop: str                  # CFOP
    unit: str                  # uCom
    quantity: Decimal          # qCom
    unit_cost: Decimal         # vUnCom
    total_cost: Decimal        # vProd

    @property
    def has_valid_ean(self) -> bool:
        """Verifica se tem EAN válido (não é placeholder)."""
        if not self.ean:
            return False
        invalid_eans = {'SEM GTIN', 'SEM EAN', '0000000000000', ''}
        return self.ean.upper() not in invalid_eans and len(self.ean) >= 8


@dataclass
class NfeData:
    """Dados extraídos da NF-e."""
    nfe_key: str
    nfe_number: str
    series: str
    emission_date: datetime

    supplier_cnpj: str
    supplier_name: str
    supplier_trade_name: str
    supplier_state_registration: str
    supplier_address: str
    supplier_city: str
    supplier_state: str

    items: List[NfeItem] = field(default_factory=list)
    total_products: Decimal = Decimal('0')
    total_nfe: Decimal = Decimal('0')

    @property
    def supplier_cnpj_clean(self) -> str:
        return re.sub(r'[^0-9]', '', self.supplier_cnpj)


@dataclass
class MatchResult:
    """Resultado do matching de um item."""
    item: NfeItem
    level: MatchLevel
    confidence: float
    product: Optional['Product'] = None
    variant: Optional['ProductVariant'] = None
    supplier_map: Optional['SupplierProductMap'] = None
    suggestions: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_matched(self) -> bool:
        return self.level != MatchLevel.NONE

# Redundant ProductMatcher and MatchLevel removed. Using apps.inventory.services.matcher.


@dataclass
class ImportResult:
    """Resultado da importação de uma NF-e."""
    success: bool
    batch_id: str
    nfe_key: str
    nfe_number: str
    supplier_name: str

    total_items: int = 0
    matched_items: int = 0
    pending_items: int = 0
    error_items: int = 0

    movements_created: int = 0
    pending_associations: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def has_pending(self) -> bool:
        return self.pending_items > 0


# =============================================================================
# NFE PARSER
# =============================================================================

class NfeParser:
    """Parser de XML de NF-e."""

    NAMESPACES = [
        {'nfe': 'http://www.portalfiscal.inf.br/nfe'},
        {'nfe': ''},
    ]

    def __init__(self, xml_content: bytes):
        self.xml_content = xml_content
        self.root = None
        self.ns = None
        self._parse()

    def _parse(self) -> None:
        try:
            self.root = ET.fromstring(self.xml_content)
        except ET.ParseError as e:
            raise ValueError(f"XML inválido: {str(e)}")

        for ns in self.NAMESPACES:
            inf_nfe = self.root.find('.//nfe:infNFe', ns)
            if inf_nfe is not None:
                self.ns = ns
                break

        if self.ns is None:
            inf_nfe = self.root.find('.//infNFe')
            if inf_nfe is not None:
                self.ns = {}
            else:
                raise ValueError("Estrutura infNFe não encontrada no XML")

    def _find(self, path: str, parent=None):
        base = parent if parent is not None else self.root
        if self.ns:
            return base.find(path, self.ns)
        return base.find(path.replace('nfe:', ''))

    def _find_text(self, path: str, parent=None, default: str = '') -> str:
        elem = self._find(path, parent)
        return elem.text if elem is not None and elem.text else default

    def _find_all(self, path: str, parent=None):
        base = parent if parent is not None else self.root
        if self.ns:
            return base.findall(path, self.ns)
        return base.findall(path.replace('nfe:', ''))

    def parse(self) -> NfeData:
        inf_nfe = self._find('.//nfe:infNFe')
        nfe_key = inf_nfe.get('Id', '').replace('NFe', '') if inf_nfe is not None else ''

        nfe_number = self._find_text('.//nfe:ide/nfe:nNF')
        series = self._find_text('.//nfe:ide/nfe:serie')
        emission_str = self._find_text('.//nfe:ide/nfe:dhEmi')

        try:
            emission_clean = emission_str[:19] if emission_str else ''
            emission_date = datetime.fromisoformat(emission_clean) if emission_clean else datetime.now()
        except ValueError:
            emission_date = datetime.now()

        emit = self._find('.//nfe:emit')
        supplier_cnpj = self._find_text('nfe:CNPJ', emit)
        supplier_name = self._find_text('nfe:xNome', emit)
        supplier_trade_name = self._find_text('nfe:xFant', emit)
        supplier_ie = self._find_text('nfe:IE', emit)

        ender_emit = self._find('nfe:enderEmit', emit)
        supplier_address = ''
        if ender_emit is not None:
            logr = self._find_text('nfe:xLgr', ender_emit)
            nro = self._find_text('nfe:nro', ender_emit)
            supplier_address = f"{logr}, {nro}" if logr else ''

        supplier_city = self._find_text('nfe:xMun', ender_emit) if ender_emit else ''
        supplier_state = self._find_text('nfe:UF', ender_emit) if ender_emit else ''

        items = []
        for det in self._find_all('.//nfe:det'):
            item_number = int(det.get('nItem', 0))
            prod = self._find('nfe:prod', det)

            if prod is None:
                continue

            supplier_sku = self._find_text('nfe:cProd', prod)
            ean = self._find_text('nfe:cEAN', prod)
            description = self._find_text('nfe:xProd', prod)
            ncm = self._find_text('nfe:NCM', prod)
            cfop = self._find_text('nfe:CFOP', prod)
            unit = self._find_text('nfe:uCom', prod)

            try:
                quantity = Decimal(self._find_text('nfe:qCom', prod) or '0')
                unit_cost = Decimal(self._find_text('nfe:vUnCom', prod) or '0')
                total_cost = Decimal(self._find_text('nfe:vProd', prod) or '0')
            except InvalidOperation:
                quantity = Decimal('0')
                unit_cost = Decimal('0')
                total_cost = Decimal('0')

            items.append(NfeItem(
                item_number=item_number,
                supplier_sku=supplier_sku,
                ean=ean,
                description=description,
                ncm=ncm,
                cfop=cfop,
                unit=unit,
                quantity=quantity,
                unit_cost=unit_cost,
                total_cost=total_cost,
            ))

        try:
            total_products = Decimal(self._find_text('.//nfe:ICMSTot/nfe:vProd') or '0')
            total_nfe = Decimal(self._find_text('.//nfe:ICMSTot/nfe:vNF') or '0')
        except InvalidOperation:
            total_products = Decimal('0')
            total_nfe = Decimal('0')

        return NfeData(
            nfe_key=nfe_key,
            nfe_number=nfe_number,
            series=series,
            emission_date=emission_date,
            supplier_cnpj=supplier_cnpj,
            supplier_name=supplier_name,
            supplier_trade_name=supplier_trade_name,
            supplier_state_registration=supplier_ie,
            supplier_address=supplier_address,
            supplier_city=supplier_city,
            supplier_state=supplier_state,
            items=items,
            total_products=total_products,
            total_nfe=total_nfe,
        )


# =============================================================================
# PRODUCT MATCHER
# =============================================================================

# Legacy ProductMatcher and support methods removed.


# =============================================================================
# NFE IMPORT SERVICE
# =============================================================================

class NfeImportService:
    """Serviço de importação inteligente de NF-e."""

    def __init__(self, tenant: 'Tenant', user: 'User'):
        self.tenant = tenant
        self.user = user

    @transaction.atomic
    def import_from_bytes(self, xml_content: bytes) -> ImportResult:
        from apps.core.services import StockService
        from apps.inventory.models import ImportBatch, PendingAssociation, PendingAssociationStatus
        from apps.partners.models import Supplier, SupplierProductMap

        # 1. Parse do XML
        try:
            parser = NfeParser(xml_content)
            nfe_data = parser.parse()
        except Exception as e:
            return ImportResult(
                success=False,
                batch_id='',
                nfe_key='',
                nfe_number='',
                supplier_name='',
                errors=[f"Erro ao ler XML: {str(e)}"]
            )

        # 2. Verifica duplicidade
        existing = ImportBatch.objects.filter(
            tenant=self.tenant,
            log__contains=nfe_data.nfe_key
        ).first()

        if existing:
            return ImportResult(
                success=False,
                batch_id=str(existing.id),
                nfe_key=nfe_data.nfe_key,
                nfe_number=nfe_data.nfe_number,
                supplier_name=nfe_data.supplier_name,
                errors=[f"NF-e {nfe_data.nfe_number} já foi importada"]
            )

        # 3. Busca/Cria Fornecedor
        supplier, _ = Supplier.get_or_create_from_nfe(
            tenant=self.tenant,
            cnpj=nfe_data.supplier_cnpj_clean,
            company_name=nfe_data.supplier_name,
            state_registration=nfe_data.supplier_state_registration,
            trade_name=nfe_data.supplier_trade_name,
            address=nfe_data.supplier_address,
            city=nfe_data.supplier_city,
            state=nfe_data.supplier_state,
        )

        # 4. Cria batch
        batch = ImportBatch.objects.create(
            tenant=self.tenant,
            user=self.user,
            type='XML_NFE',
            file='',
            status='PROCESSING',
            total_rows=len(nfe_data.items),
            log=f"NF-e: {nfe_data.nfe_key}\nFornecedor: {supplier.display_name}\n",
        )

        # 5. Processa itens
        result = ImportResult(
            success=True,
            batch_id=str(batch.id),
            nfe_key=nfe_data.nfe_key,
            nfe_number=nfe_data.nfe_number,
            supplier_name=supplier.display_name,
            total_items=len(nfe_data.items),
        )

        for item in nfe_data.items:
            try:
                # Unified V3 Matcher
                match_result = ProductMatcher.match(item, self.tenant, supplier)

                if match_result.is_matched:
                    # Cria movimentação usando StockService existente
                    StockService.create_movement(
                        tenant=self.tenant,
                        user=self.user,
                        movement_type='IN',
                        quantity=int(item.quantity),
                        product=match_result.product if not match_result.variant else None,
                        variant=match_result.variant,
                        reason=f"NF-e {nfe_data.nfe_number} item {item.item_number}",
                        unit_cost=item.unit_cost,
                        source='NFE',
                        source_doc=nfe_data.nfe_key,
                    )

                    # Atualiza/Cria mapeamento
                    SupplierProductMap.objects.get_or_create(
                        tenant=self.tenant,
                        supplier=supplier,
                        supplier_sku=item.supplier_sku,
                        defaults={
                            'product': match_result.product,
                            'variant': match_result.variant,
                            'supplier_ean': item.ean if item.has_valid_ean else '',
                            'supplier_name': item.description[:120],
                            'last_cost': item.unit_cost,
                            'last_purchase': timezone.now().date(),
                        }
                    )

                    result.matched_items += 1
                    result.movements_created += 1

                else:
                    # Cria pendência
                    pending = PendingAssociation.objects.create(
                        tenant=self.tenant,
                        import_batch=batch,
                        supplier=supplier,
                        nfe_key=nfe_data.nfe_key,
                        nfe_number=nfe_data.nfe_number,
                        item_number=item.item_number,
                        supplier_sku=item.supplier_sku,
                        supplier_ean=item.ean if item.has_valid_ean else '',
                        supplier_name=item.description[:120],
                        ncm=item.ncm,
                        cfop=item.cfop,
                        unit=item.unit,
                        quantity=item.quantity,
                        unit_cost=item.unit_cost,
                        total_cost=item.total_cost,
                        status=PendingAssociationStatus.PENDING,
                        match_suggestions=match_result.suggestion_data.get('detected_attributes', []),
                        match_score=float(match_result.confidence),
                    )

                    result.pending_items += 1
                    result.pending_associations.append(str(pending.id))

                batch.processed_rows += 1

            except Exception as e:
                result.error_items += 1
                result.errors.append(f"Item {item.item_number}: {str(e)}")

        # 6. Finaliza batch
        batch.success_count = result.matched_items
        batch.error_count = result.error_items
        batch.completed_at = timezone.now()

        if result.pending_items > 0:
            batch.status = 'PARTIAL'
            batch.log += f"\n{result.pending_items} itens aguardando associação manual"
        elif result.error_items > 0:
            batch.status = 'PARTIAL'
        else:
            batch.status = 'COMPLETED'

        batch.save()

        return result

    def import_from_file(self, file_path: str) -> ImportResult:
        with open(file_path, 'rb') as f:
            return self.import_from_bytes(f.read())
