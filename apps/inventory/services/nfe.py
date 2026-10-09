"""
Importação de NF-e de entrada (XML) — Beta.

Fluxo: upload -> prévia (NfeDocument PREVIEW + NfeItem com sugestões) ->
o usuário revisa item a item -> confirmar (tudo numa transação) -> pode desfazer.

O padrão de cada empresa (custo, como encontrar produto, produtos novos, local)
fica em NfeSettings.
"""
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

MAX_XML_BYTES = 5 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 50
INVALID_EANS = {'', 'SEM GTIN', 'SEM EAN'}
PACKAGE_UNITS = {'CX', 'CAIXA', 'PCT', 'PC', 'PACOTE', 'FD', 'FARDO', 'DZ', 'DUZIA', 'KIT', 'EMB', 'DP', 'DISPLAY'}


class NfeError(Exception):
    def __init__(self, message, document=None):
        super().__init__(message)
        self.document = document  # nota já existente (duplicada), quando houver


# ---------------------------------------------------------------- leitura

@dataclass
class ParsedItem:
    item_number: int
    supplier_code: str
    ean: str
    description: str
    ncm: str
    cfop: str
    unit: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal
    freight: Decimal = Decimal('0')
    insurance: Decimal = Decimal('0')
    discount: Decimal = Decimal('0')
    other: Decimal = Decimal('0')
    ipi: Decimal = Decimal('0')
    icms_st: Decimal = Decimal('0')
    lots: list = field(default_factory=list)


@dataclass
class ParsedNfe:
    access_key: str
    number: str
    series: str
    model: str
    operation_type: str
    issued_at: datetime
    supplier_cnpj: str
    supplier_name: str
    supplier_trade_name: str
    supplier_ie: str
    supplier_city: str
    supplier_state: str
    recipient_cnpj: str
    total_products: Decimal
    total_invoice: Decimal
    authorized: bool
    items: list


def _digits(value):
    return re.sub(r'\D', '', value or '')


def _dec(value):
    try:
        return Decimal((value or '0').strip())
    except (InvalidOperation, AttributeError):
        raise NfeError(f"Valor numérico inválido na nota: '{value}'.")


def _date(value):
    if not value:
        return None
    text = value.strip()[:10]
    try:
        return datetime.strptime(text, '%Y-%m-%d').date().isoformat()
    except ValueError:
        return None


def parse_nfe_xml(content: bytes) -> ParsedNfe:
    """Lê a NF-e com lxml sem DTD, entidades ou rede (proteção contra XXE/bomba de entidades)."""
    from lxml import etree

    if len(content) > MAX_XML_BYTES:
        raise NfeError("Arquivo maior que 5 MB.")
    head = content[:2048].upper()
    if b'<!DOCTYPE' in head or b'<!ENTITY' in content.upper():
        raise NfeError("XML com DOCTYPE/ENTITY não é aceito.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False,
                             huge_tree=False, remove_comments=True, remove_pis=True)
    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise NfeError(f"XML inválido: {exc}")

    def find(node, path):
        return node.find(path) if node is not None else None

    def text(node, path, default=''):
        el = find(node, path)
        return (el.text or '').strip() if el is not None and el.text else default

    inf = root.find('.//{*}infNFe')
    if inf is None:
        raise NfeError("Não é uma NF-e (grupo infNFe não encontrado).")
    ide = find(inf, '{*}ide')
    emit = find(inf, '{*}emit')
    dest = find(inf, '{*}dest')
    ender = find(emit, '{*}enderEmit')

    key = _digits(inf.get('Id', ''))
    prot_key = text(root, './/{*}protNFe/{*}infProt/{*}chNFe')
    if not key and prot_key:
        key = prot_key
    if len(key) != 44:
        raise NfeError("Chave de acesso ausente ou inválida.")
    c_stat = text(root, './/{*}protNFe/{*}infProt/{*}cStat')

    issued_raw = text(ide, '{*}dhEmi') or text(ide, '{*}dEmi')
    try:
        issued_at = datetime.fromisoformat(issued_raw) if issued_raw else None
    except ValueError:
        issued_at = None

    items = []
    for det in inf.findall('{*}det'):
        prod = find(det, '{*}prod')
        if prod is None:
            continue
        imposto = find(det, '{*}imposto')
        ipi = text(imposto, '{*}IPI/{*}IPITrib/{*}vIPI')
        st = Decimal('0')
        icms = find(imposto, '{*}ICMS')
        if icms is not None:
            for group in icms:
                st += _dec(text(group, '{*}vICMSST')) + _dec(text(group, '{*}vFCPST'))
        ean = text(prod, '{*}cEAN')
        if ean.upper() in INVALID_EANS:
            ean = text(prod, '{*}cEANTrib')
        if ean.upper() in INVALID_EANS or not ean.isdigit():
            ean = ''
        lots = []
        for rastro in prod.findall('{*}rastro'):
            lots.append({
                'lot': text(rastro, '{*}nLote')[:60],
                'quantity': str(_dec(text(rastro, '{*}qLote'))),
                'manufacture': _date(text(rastro, '{*}dFab')),
                'expiry': _date(text(rastro, '{*}dVal')),
            })
        quantity = _dec(text(prod, '{*}qCom'))
        if quantity <= 0:
            raise NfeError(f"Item {det.get('nItem')}: quantidade inválida.")
        items.append(ParsedItem(
            item_number=int(det.get('nItem') or len(items) + 1),
            supplier_code=text(prod, '{*}cProd')[:60],
            ean=ean[:14],
            description=text(prod, '{*}xProd')[:255] or f"Item {det.get('nItem')}",
            ncm=text(prod, '{*}NCM')[:10],
            cfop=text(prod, '{*}CFOP')[:4],
            unit=text(prod, '{*}uCom')[:10].upper(),
            quantity=quantity,
            unit_price=_dec(text(prod, '{*}vUnCom')),
            total=_dec(text(prod, '{*}vProd')),
            freight=_dec(text(prod, '{*}vFrete')),
            insurance=_dec(text(prod, '{*}vSeg')),
            discount=_dec(text(prod, '{*}vDesc')),
            other=_dec(text(prod, '{*}vOutro')),
            ipi=_dec(ipi),
            icms_st=st,
            lots=lots,
        ))
    if not items:
        raise NfeError("A nota não tem itens.")

    return ParsedNfe(
        access_key=key,
        number=text(ide, '{*}nNF'),
        series=text(ide, '{*}serie'),
        model=text(ide, '{*}mod'),
        operation_type=text(ide, '{*}tpNF'),
        issued_at=issued_at,
        supplier_cnpj=_digits(text(emit, '{*}CNPJ')),
        supplier_name=text(emit, '{*}xNome')[:200],
        supplier_trade_name=text(emit, '{*}xFant')[:200],
        supplier_ie=text(emit, '{*}IE')[:20],
        supplier_city=text(ender, '{*}xMun')[:100],
        supplier_state=text(ender, '{*}UF')[:2],
        recipient_cnpj=_digits(text(dest, '{*}CNPJ')),
        total_products=_dec(text(inf, '{*}total/{*}ICMSTot/{*}vProd')),
        total_invoice=_dec(text(inf, '{*}total/{*}ICMSTot/{*}vNF')),
        authorized=c_stat in ('100', '150'),
        items=items,
    )


def iter_uploaded_xmls(uploaded_files):
    """Aceita .xml e .zip (com XMLs dentro). Retorna [(nome, bytes)]."""
    out = []
    for f in uploaded_files:
        name = f.name or 'arquivo'
        data = f.read(MAX_XML_BYTES * 10 + 1)
        if name.lower().endswith('.zip'):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    for info in zf.infolist():
                        if info.is_dir() or not info.filename.lower().endswith('.xml'):
                            continue
                        if info.file_size > MAX_XML_BYTES:
                            out.append((info.filename, None))
                            continue
                        out.append((info.filename, zf.read(info)))
            except zipfile.BadZipFile:
                out.append((name, None))
        else:
            out.append((name, data))
        if len(out) > MAX_FILES_PER_UPLOAD:
            raise NfeError(f"Envie no máximo {MAX_FILES_PER_UPLOAD} notas por vez.")
    return out


# ------------------------------------------------------------- sugestões

def suggest_factor(unit, description):
    """Sugere o fator de conversão para unidades de embalagem (CX c/ 12, DZ...)."""
    unit = (unit or '').upper()
    if unit in ('DZ', 'DUZIA'):
        return Decimal('12')
    if unit not in PACKAGE_UNITS:
        return None
    m = re.search(r'(?:C/|C\s*/\s*|COM\s+|CX\s*C?/?\s*|X\s*)(\d{1,4})\s*(?:UN|UND|UNID|PCS?|P[ÇC]S)?\b',
                  (description or '').upper())
    if m and int(m.group(1)) > 1:
        return Decimal(m.group(1))
    return None


def find_match(tenant, cfg, supplier, item):
    """Retorna (variant, origem, fator_aprendido) segundo a ordem configurada pela empresa."""
    from apps.partners.models import SupplierProductMap
    from apps.products.models import ProductVariant

    active = ProductVariant.objects.filter(tenant=tenant, is_active=True, product__is_active=True)
    if cfg.match_supplier_code and supplier and item.supplier_code:
        mapping = SupplierProductMap.objects.filter(
            tenant=tenant, supplier=supplier, supplier_sku=item.supplier_code, is_active=True,
        ).select_related('variant', 'product').first()
        if mapping:
            variant = mapping.variant or mapping.product.variants.first()
            if variant and variant.is_active and variant.product.is_active:
                return variant, 'SUPPLIER_MAP', mapping.conversion_factor
    if cfg.match_ean and item.ean:
        variant = active.filter(barcode=item.ean).first()
        if variant:
            return variant, 'EAN', None
    if cfg.match_sku and item.supplier_code:
        variant = active.filter(sku__iexact=item.supplier_code).first()
        if variant:
            return variant, 'SKU', None
    return None, '', None


def _supplier_for(tenant, cnpj):
    from apps.partners.models import Supplier
    if not cnpj:
        return None
    return Supplier.objects.filter(tenant=tenant, cnpj=cnpj).first()


def _clean_name(name, cfg):
    name = re.sub(r'\s+', ' ', name or '').strip()
    if cfg.title_case_names and name.isupper():
        small = {'De', 'Da', 'Do', 'Das', 'Dos', 'E', 'Com', 'C/', 'Para'}
        words = []
        for i, w in enumerate(name.title().split(' ')):
            words.append(w.lower() if i and w in small else w)
        name = ' '.join(words)
    return name[:255]


# --------------------------------------------------------------- prévia

@transaction.atomic
def create_preview(tenant, user, filename, content):
    """Lê o XML e cria o documento em revisão. Nada entra no estoque aqui."""
    from apps.inventory.models import NfeDocument, NfeItem, NfeSettings

    data = parse_nfe_xml(content)
    cfg = NfeSettings.for_tenant(tenant)

    existing = NfeDocument.objects.filter(tenant=tenant, access_key=data.access_key,
                                          status__in=['PREVIEW', 'IMPORTED']).first()
    if existing:
        verb = 'já foi importada' if existing.status == 'IMPORTED' else 'já está em revisão'
        raise NfeError(f"A NF-e {data.number} ({data.supplier_name}) {verb}.", existing)

    tenant_cnpj = _digits(tenant.cnpj)
    warnings = []
    if data.model and data.model != '55':
        warnings.append({'code': 'MODEL', 'blocking': True,
                         'text': f"Modelo {data.model} não é NF-e de compra (modelo 55)."})
    if tenant_cnpj and data.supplier_cnpj == tenant_cnpj:
        warnings.append({'code': 'OWN_NOTE', 'blocking': True,
                         'text': "Esta nota foi emitida pela própria empresa (é uma venda, não uma compra)."})
    if cfg.require_recipient_cnpj:
        if not tenant_cnpj:
            warnings.append({'code': 'NO_TENANT_CNPJ', 'blocking': False, 'confirm': True,
                             'text': "Cadastre o CNPJ da empresa em Configurações para o sistema conferir o destinatário."})
        elif data.recipient_cnpj != tenant_cnpj:
            warnings.append({'code': 'RECIPIENT', 'blocking': False, 'confirm': True,
                             'text': f"O destinatário da nota (CNPJ {data.recipient_cnpj or 'não informado'}) "
                                     "não é o CNPJ desta empresa. Confirme antes de importar."})
    if not data.authorized:
        warnings.append({'code': 'NO_PROTOCOL', 'blocking': False,
                         'text': "O XML não traz o protocolo de autorização da SEFAZ. Prefira o XML autorizado (nfeProc)."})

    supplier = _supplier_for(tenant, data.supplier_cnpj)
    doc = NfeDocument(
        tenant=tenant, access_key=data.access_key, number=data.number, series=data.series,
        issued_at=data.issued_at if data.issued_at is None or data.issued_at.tzinfo
        else timezone.make_aware(data.issued_at),
        supplier_cnpj=data.supplier_cnpj, supplier_name=data.supplier_name,
        supplier_trade_name=data.supplier_trade_name, supplier_ie=data.supplier_ie,
        supplier_city=data.supplier_city, supplier_state=data.supplier_state, supplier=supplier,
        recipient_cnpj=data.recipient_cnpj, total_products=data.total_products,
        total_invoice=data.total_invoice, authorized=data.authorized, warnings=warnings,
        created_by=user,
    )
    doc.xml_file.save(f"{data.access_key}.xml", ContentFile(content), save=False)
    try:
        doc.save()
    except IntegrityError:
        raise NfeError(f"A NF-e {data.number} já está em revisão ou importada.")

    for it in data.items:
        variant, source, learned_factor = find_match(tenant, cfg, supplier, it)
        factor, suggested = Decimal('1'), False
        if learned_factor:
            factor = learned_factor
        elif not variant or source != 'SUPPLIER_MAP':
            guess = suggest_factor(it.unit, it.description)
            if guess:
                factor, suggested = guess, True
        if variant:
            decision = 'LINK'
        else:
            decision = 'CREATE' if cfg.new_product_policy == 'AUTO_CREATE' else 'PENDING'
        NfeItem.objects.create(
            document=doc, item_number=it.item_number, supplier_code=it.supplier_code, ean=it.ean,
            description=it.description, ncm=it.ncm, cfop=it.cfop, unit=it.unit, quantity=it.quantity,
            unit_price=it.unit_price, total=it.total, freight=it.freight, insurance=it.insurance,
            discount=it.discount, other=it.other, ipi=it.ipi, icms_st=it.icms_st, lots=it.lots,
            decision=decision, variant=variant, match_source=source,
            conversion_factor=factor, factor_suggested=suggested,
            new_product_name=_clean_name(it.description, cfg),
            new_product_category=cfg.default_category,
        )
    return doc


def apply_decisions(doc, post):
    """Grava as escolhas da tela de revisão. Retorna lista de erros (por item)."""
    from apps.products.models import Category, ProductVariant

    errors = []
    tenant = doc.tenant
    for item in doc.items.all():
        prefix = f"item-{item.pk}-"
        decision = post.get(prefix + 'decision', item.decision)
        if decision not in ('LINK', 'CREATE', 'IGNORE', 'PENDING'):
            decision = 'PENDING'
        item.decision = decision
        raw_factor = (post.get(prefix + 'factor') or '').strip().replace(',', '.')
        if raw_factor:
            try:
                factor = Decimal(raw_factor)
                if not factor.is_finite() or factor <= 0 or factor > 100000:
                    raise InvalidOperation
                if factor != item.conversion_factor:
                    item.factor_suggested = False
                item.conversion_factor = factor
            except InvalidOperation:
                errors.append(f"Item {item.item_number}: fator de conversão inválido.")
        if decision == 'LINK':
            ref = (post.get(prefix + 'sku') or '').strip()
            if ref and (not item.variant or ref.lower() not in (item.variant.sku.lower(), (item.variant.barcode or '').lower())):
                variant = (ProductVariant.objects.filter(tenant=tenant, sku__iexact=ref).first()
                           or ProductVariant.objects.filter(tenant=tenant, barcode=ref).first())
                if not variant:
                    errors.append(f"Item {item.item_number}: produto '{ref}' não encontrado.")
                elif not (variant.is_active and variant.product.is_active):
                    errors.append(f"Item {item.item_number}: o produto '{ref}' está arquivado.")
                else:
                    item.variant, item.match_source = variant, 'MANUAL'
        if decision == 'CREATE':
            name = (post.get(prefix + 'name') or '').strip()
            if name:
                item.new_product_name = name[:255]
            cat_id = post.get(prefix + 'category')
            if cat_id:
                item.new_product_category = Category.objects.filter(tenant=tenant, pk=cat_id).first()
            elif cat_id == '':
                item.new_product_category = None
        item.save()
    return errors


def validate_ready(doc):
    """Erros que impedem a importação."""
    errors = [w['text'] for w in doc.blocking_warnings]
    for item in doc.items.select_related('variant__product'):
        if item.decision == 'PENDING':
            errors.append(f"Item {item.item_number} ({item.description[:40]}): escolha vincular, criar ou ignorar.")
        elif item.decision == 'LINK' and not item.variant_id:
            errors.append(f"Item {item.item_number}: informe o produto do sistema.")
        elif item.decision == 'LINK' and not (item.variant.is_active and item.variant.product.is_active):
            errors.append(f"Item {item.item_number}: o produto vinculado está arquivado.")
        elif item.decision == 'CREATE' and not item.new_product_name.strip():
            errors.append(f"Item {item.item_number}: informe o nome do produto novo.")
    if all(i.decision == 'IGNORE' for i in doc.items.all()):
        errors.append("Todos os itens estão marcados para ignorar.")
    return errors


# -------------------------------------------------------------- importar

def _new_sku(tenant, cfg, item):
    from apps.products.models import Product, ProductVariant
    candidate = None
    if cfg.sku_policy == 'SUPPLIER_CODE' and item.supplier_code:
        candidate = item.supplier_code[:50]
    elif cfg.sku_policy == 'EAN' and item.ean:
        candidate = item.ean
    if candidate and not (ProductVariant.objects.filter(tenant=tenant, sku__iexact=candidate).exists()
                          or Product.objects.filter(tenant=tenant, sku__iexact=candidate).exists()):
        return candidate
    return None  # Product.save gera SIM-CAT-0001


@transaction.atomic
def import_document(doc, user, confirm_recipient=False):
    from apps.core.services import StockService
    from apps.inventory.models import NfeDocument, NfeSettings
    from apps.partners.models import Supplier, SupplierProductMap
    from apps.products.models import Product, ProductType, ProductVariant
    from apps.tenants.models import Tenant

    tenant = Tenant.objects.select_for_update().get(pk=doc.tenant_id)
    doc = NfeDocument.objects.select_for_update().get(pk=doc.pk)
    if doc.status != 'PREVIEW':
        raise NfeError("Esta nota não está mais em revisão.")
    errors = validate_ready(doc)
    if any(w.get('confirm') for w in doc.warnings) and not confirm_recipient:
        errors.append("Confirme que esta nota pertence a esta empresa (caixa de confirmação).")
    if errors:
        raise NfeError("\n".join(errors))
    cfg = NfeSettings.for_tenant(tenant)
    items = list(doc.items.select_related('variant__product', 'new_product_category'))

    to_create = [i for i in items if i.decision == 'CREATE']
    if to_create and tenant.plan and tenant.plan.max_products:
        if tenant.products_count + len(to_create) > tenant.plan.max_products:
            raise NfeError(f"A nota cria {len(to_create)} produto(s) e o plano permite mais "
                           f"{tenant.products_remaining}. Vincule itens a produtos existentes ou faça upgrade.")

    supplier = None
    if doc.supplier_cnpj:
        supplier = Supplier.objects.filter(tenant=tenant, cnpj=doc.supplier_cnpj).first()
        if supplier is None:
            try:
                supplier = Supplier(tenant=tenant, cnpj=doc.supplier_cnpj,
                                    company_name=doc.supplier_name or doc.supplier_cnpj,
                                    trade_name=doc.supplier_trade_name, state_registration=doc.supplier_ie,
                                    city=doc.supplier_city, state=doc.supplier_state)
                supplier.save()
            except Exception:
                supplier = None  # CNPJ inválido no XML: segue sem fornecedor
    location_id = cfg.default_location_id if cfg.default_location and cfg.default_location.is_active else None

    for item in items:
        if item.decision == 'IGNORE':
            continue
        if item.decision == 'CREATE':
            barcode = item.ean if item.ean and not ProductVariant.objects.filter(
                tenant=tenant, barcode=item.ean).exists() else None
            product = Product(
                tenant=tenant, name=item.new_product_name.strip()[:255], product_type=ProductType.SIMPLE,
                sku=_new_sku(tenant, cfg, item), barcode=barcode, category=item.new_product_category,
                default_supplier=supplier, default_location_id=location_id,
                uom=(item.unit if item.conversion_factor == 1 and item.unit else 'UN')[:10],
                tracks_expiry=bool(item.lots) and cfg.auto_tracks_expiry,
            )
            product.save()
            variant = product.variants.first()
            item.variant = variant
        variant = item.variant
        if item.lots and cfg.auto_tracks_expiry and not variant.product.tracks_expiry:
            Product.objects.filter(pk=variant.product_id).update(tracks_expiry=True)

        unit_cost = item.unit_cost(cfg)
        reason = f"NF-e {doc.number} item {item.item_number}"[:255]
        movements = []
        remaining = item.stock_quantity
        for lot in item.lots:
            qty = min(Decimal(lot['quantity']) * item.conversion_factor, remaining)
            if qty <= 0:
                continue
            movements.append(StockService.create_movement(
                tenant=tenant, user=user, movement_type='IN', quantity=qty, variant=variant,
                unit_cost=unit_cost, reason=reason, source='NFE', source_doc=doc.access_key,
                location_id=location_id, lot_number=lot.get('lot') or None,
                expiry_date=lot.get('expiry'), manufacture_date=lot.get('manufacture'),
            ))
            remaining -= qty
        if remaining > 0:
            movements.append(StockService.create_movement(
                tenant=tenant, user=user, movement_type='IN', quantity=remaining, variant=variant,
                unit_cost=unit_cost, reason=reason, source='NFE', source_doc=doc.access_key,
                location_id=location_id,
            ))
        item.movement_ids = [str(m.pk) for m in movements]
        item.save(update_fields=['variant', 'movement_ids'])

        # Aprende o vínculo código do fornecedor -> produto (próximas notas já vêm certas)
        if supplier and item.supplier_code:
            mapping, _ = SupplierProductMap.objects.get_or_create(
                tenant=tenant, supplier=supplier, supplier_sku=item.supplier_code,
                defaults={'product': variant.product, 'variant': variant},
            )
            mapping.product, mapping.variant = variant.product, variant
            mapping.supplier_ean = item.ean
            mapping.supplier_name = item.description[:120]
            mapping.conversion_factor = item.conversion_factor
            mapping.last_cost = unit_cost
            mapping.last_purchase = (doc.issued_at or timezone.now()).date()
            mapping.total_purchased += int(item.stock_quantity)
            mapping.is_active = True
            mapping.save()

    doc.status = 'IMPORTED'
    doc.supplier = supplier
    doc.imported_by = user
    doc.imported_at = timezone.now()
    doc.save()
    return doc


@transaction.atomic
def revert_document(doc, user):
    """Desfaz a entrada com saídas de estorno (nada é apagado). Exige saldo suficiente."""
    from apps.core.services import StockService
    from apps.inventory.models import NfeDocument, StockMovement

    doc = NfeDocument.objects.select_for_update().get(pk=doc.pk)
    if doc.status != 'IMPORTED':
        raise NfeError("Só é possível desfazer uma nota importada.")
    for item in doc.items.all():
        for mid in item.movement_ids:
            mov = StockMovement.objects.select_related('variant').get(pk=mid, tenant=doc.tenant)
            allocations = list(mov.lot_allocations.select_related('lot'))
            try:
                if allocations:
                    for alloc in allocations:
                        StockService.create_movement(
                            tenant=doc.tenant, user=user, movement_type='OUT', quantity=alloc.quantity,
                            variant=mov.variant, lot_id=alloc.lot_id, allow_expired_lot=True, source='NFE_REVERT',
                            source_doc=doc.access_key, reason=f"Estorno NF-e {doc.number} item {item.item_number}",
                        )
                else:
                    StockService.create_movement(
                        tenant=doc.tenant, user=user, movement_type='OUT', quantity=mov.quantity,
                        variant=mov.variant, source='NFE_REVERT', source_doc=doc.access_key,
                        reason=f"Estorno NF-e {doc.number} item {item.item_number}",
                    )
            except ValueError as exc:
                raise NfeError(f"Item {item.item_number} ({mov.variant.sku}): não dá para estornar — {exc}")
    doc.status = 'REVERTED'
    doc.reverted_at = timezone.now()
    doc.save(update_fields=['status', 'reverted_at'])
    return doc

