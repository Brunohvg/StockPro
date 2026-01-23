"""
StockPro V3 - Enhanced Product Matcher with Smart Parsing
Parses product names to detect categories, brands, attributes, and more.
Works both with and without AI.
"""
import json
import logging
import re
from decimal import Decimal
from typing import Any, Dict, Optional

from django.db.models import Q

from apps.core.services import AIService
from apps.partners.models import SupplierProductMap
from apps.products.models import Brand, Category, Product, ProductVariant

logger = logging.getLogger(__name__)


# =============================================================================
# KNOWLEDGE BASE - Patterns for Brazilian product names
# =============================================================================

# Common brand patterns (Brazilian market)
KNOWN_BRANDS = [
    # Têxteis
    "SANTA FE", "SANTA FÉ", "CIRCULO", "CÍRCULO", "COATS", "PINGUIN", "LINHAS CORRENTE",
    # Ferramentas
    "BOSCH", "MAKITA", "DEWALT", "BLACK DECKER", "TRAMONTINA", "GEDORE",
    # Eletrônicos
    "SAMSUNG", "LG", "PHILIPS", "INTELBRAS", "MULTILASER", "ELGIN",
    # Papelaria
    "FABER CASTELL", "BIC", "PILOT", "TILIBRA", "STAEDTLER",
    # Limpeza
    "BOMBRIL", "YPÊ", "VEJA", "PINHO SOL",
    # Genéricos comuns em NF-e
    "GENERICO", "IMPORTADO", "NACIONAL",
]

# Category patterns by keywords
CATEGORY_PATTERNS = {
    "Tecidos": ["TECIDO", "FELTRO", "TNT", "MALHA", "OXFORD", "TRICOLINE", "CETIM", "JEANS", "BRIM", "LINHO"],
    "Linhas e Fios": ["LINHA", "FIO", "NOVELO", "MEADA", "BARBANTE", "CORDÃO", "LÃ"],
    "Aviamentos": ["ZIPER", "ZIPPER", "BOTÃO", "BOTAO", "FIVELA", "ILHÓS", "ELASTICO", "VELCRO", "RENDA", "FITA"],
    "Ferramentas": ["ALICATE", "CHAVE", "MARTELO", "FURADEIRA", "SERRA", "LIXA", "BROCA"],
    "Eletrônicos": ["CABO", "ADAPTADOR", "CARREGADOR", "FONTE", "LED", "LAMPADA", "PILHA", "BATERIA"],
    "Papelaria": ["CADERNO", "CANETA", "LAPIS", "BORRACHA", "TESOURA", "COLA", "PAPEL", "ENVELOPE"],
    "Embalagens": ["SACOLA", "CAIXA", "SACO", "BOBINA", "ROLO", "ETIQUETA"],
}

# Color patterns in Portuguese
COLOR_PATTERNS = {
    "Branco": ["BRANCO", "BCO", "WHITE"],
    "Preto": ["PRETO", "PTO", "BLACK", "NEGRO"],
    "Azul": ["AZUL", "BLUE", "MARINHO", "ROYAL", "TURQUESA", "CELESTE", "BABY BLUE"],
    "Vermelho": ["VERMELHO", "RED", "VINHO", "BORDÔ", "BORDO", "ESCARLATE"],
    "Verde": ["VERDE", "GREEN", "MUSGO", "OLIVA", "LIMÃO", "MILITAR"],
    "Amarelo": ["AMARELO", "YELLOW", "OURO", "DOURADO", "MOSTARDA"],
    "Rosa": ["ROSA", "PINK", "MAGENTA", "FUCHSIA", "SALMÃO", "SALMON"],
    "Laranja": ["LARANJA", "ORANGE"],
    "Roxo": ["ROXO", "PURPLE", "LILAS", "LILÁS", "VIOLETA", "UVA"],
    "Marrom": ["MARROM", "BROWN", "CAFÉ", "CARAMELO", "CHOCOLATE", "BEGE", "CREME", "CAQUI"],
    "Cinza": ["CINZA", "GRAY", "GREY", "CHUMBO", "PRATA", "SILVER", "GRAFITE"],
}

# Size patterns
SIZE_PATTERNS = {
    "PP": ["PP", "XS", "EXTRA PEQUENO"],
    "P": ["\\bP\\b", "PEQUENO", "SMALL", "\\bS\\b"],
    "M": ["\\bM\\b", "MEDIO", "MÉDIO", "MEDIUM"],
    "G": ["\\bG\\b", "GRANDE", "LARGE", "\\bL\\b"],
    "GG": ["GG", "XL", "EXTRA GRANDE"],
    "XGG": ["XGG", "XXL", "2XL"],
}

# Unit patterns for dimensions
DIMENSION_PATTERNS = [
    (r'(\d+(?:[.,]\d+)?)\s*(CM|M|MM|MT|MTS|METROS?)', 'Medida'),
    (r'(\d+(?:[.,]\d+)?)\s*(G|KG|GRAMAS?|QUILOS?)', 'Peso'),
    (r'(\d+)\s*(?:UN|UND|UNID|UNIDADES?|PÇS?|PECAS?)', 'Quantidade'),
    (r'(\d+)\s*(?:V|VOLTS?|W|WATTS?|VA)', 'Voltagem'),
]


class MatchResult:
    def __init__(self, confidence: Decimal, action: str, product=None, variant=None, logic="", suggestion_data=None):
        self.confidence = confidence
        self.action = action  # 'DIRECT', 'LEARNED', 'AI_SUGGESTION', 'NEW', 'PARSED'
        self.product = product
        self.variant = variant
        self.logic = logic
        self.suggestion_data = suggestion_data or {}

    @property
    def is_matched(self) -> bool:
        return self.product is not None or self.variant is not None


class ProductParser:
    """
    Local intelligence for parsing product names without external AI.
    Extracts brand, category, color, size, and other attributes.
    """

    @classmethod
    def parse(cls, description: str, tenant=None) -> Dict[str, Any]:
        """
        Parse a product description and extract structured data.

        Returns:
            {
                'suggested_name': str,
                'detected_brand': str or None,
                'detected_category': str or None,
                'detected_attributes': {attr: value},
                'confidence': float,
                'match_type': 'NEW' or 'VARIANT_OF'
            }
        """
        if not description:
            return {'suggested_name': '', 'confidence': 0}

        desc_upper = description.upper().strip()
        result = {
            'suggested_name': cls._clean_product_name(description),
            'detected_brand': None,
            'detected_category': None,
            'detected_attributes': {},
            'confidence': 0.3,
            'match_type': 'NEW',
        }

        # Detect brand
        brand = cls._detect_brand(desc_upper, tenant)
        if brand:
            result['detected_brand'] = brand
            result['confidence'] += 0.15

        # Detect category
        category = cls._detect_category(desc_upper, tenant)
        if category:
            result['detected_category'] = category
            result['confidence'] += 0.15

        # Detect color
        color = cls._detect_color(desc_upper)
        if color:
            result['detected_attributes']['Cor'] = color
            result['confidence'] += 0.1
            result['match_type'] = 'VARIANT_OF'  # Has color = likely a variant

        # Detect size
        size = cls._detect_size(desc_upper)
        if size:
            result['detected_attributes']['Tamanho'] = size
            result['confidence'] += 0.1
            result['match_type'] = 'VARIANT_OF'

        # Detect dimensions/measurements
        for pattern, attr_name in DIMENSION_PATTERNS:
            match = re.search(pattern, desc_upper)
            if match:
                value = f"{match.group(1)} {match.group(2)}"
                result['detected_attributes'][attr_name] = value
                result['confidence'] += 0.05

        # Cap confidence
        result['confidence'] = min(result['confidence'], 0.85)

        return result

    @staticmethod
    def _clean_product_name(description: str) -> str:
        """Create a clean, formatted product name."""
        # Remove extra whitespace
        name = ' '.join(description.split())

        # Title case but preserve known acronyms
        words = []
        for word in name.split():
            if word.upper() in ['TNT', 'LED', 'USB', 'PVC', 'MDF', 'PP', 'PE', 'EAN', 'SKU']:
                words.append(word.upper())
            elif len(word) <= 2:
                words.append(word.upper())
            else:
                words.append(word.capitalize())

        return ' '.join(words)

    @staticmethod
    def _detect_brand(desc_upper: str, tenant=None) -> Optional[str]:
        """Detect brand from description."""
        # First check known brands list
        for brand in KNOWN_BRANDS:
            if brand in desc_upper:
                return brand.title()

        # Check existing brands in database
        if tenant:
            existing_brands = Brand.objects.filter(tenant=tenant).values_list('name', flat=True)[:100]
            for brand in existing_brands:
                if brand.upper() in desc_upper:
                    return brand

        return None

    @staticmethod
    def _detect_category(desc_upper: str, tenant=None) -> Optional[str]:
        """Detect category from description."""
        # Check patterns
        for category, keywords in CATEGORY_PATTERNS.items():
            for keyword in keywords:
                if keyword in desc_upper:
                    return category

        # Check existing categories in database
        if tenant:
            existing_cats = Category.objects.filter(tenant=tenant).values_list('name', flat=True)[:100]
            for cat in existing_cats:
                if cat.upper() in desc_upper:
                    return cat

        return None

    @staticmethod
    def _detect_color(desc_upper: str) -> Optional[str]:
        """Detect color from description."""
        for color_name, patterns in COLOR_PATTERNS.items():
            for pattern in patterns:
                if re.search(rf'\b{pattern}\b', desc_upper):
                    return color_name
        return None

    @staticmethod
    def _detect_size(desc_upper: str) -> Optional[str]:
        """Detect size from description."""
        for size_name, patterns in SIZE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, desc_upper):
                    return size_name
        return None


class ProductMatcher:
    """
    The unified Intelligence Engine for StockPro V3.
    Serves as the single entry point for CSV, XML (NF-e) and Manual mapping.
    Now with enhanced local parsing that works without AI.
    """

    @staticmethod
    def normalize_uom(uom: str) -> str:
        """Normalize standard NF-e units to system standard."""
        if not uom: return 'UN'
        uom = uom.strip().upper()
        mapping = {
            'UNID': 'UN', 'UND': 'UN', 'UN': 'UN',
            'PÇ': 'PC', 'PÇA': 'PC', 'PEC': 'PC', 'PECA': 'PC',
            'CX': 'CX', 'CAIXA': 'CX',
            'KG': 'KG', 'KILOGRAMA': 'KG',
            'MT': 'M', 'METRO': 'M', 'MTS': 'M',
            'LT': 'L', 'LITRO': 'L'
        }
        return mapping.get(uom, uom)

    @classmethod
    def match(cls, item: Any, tenant, supplier=None) -> MatchResult:
        """
        Main entry point for matching. 'item' can be ImportItem or any object
        with 'description', 'ean', and 'supplier_sku'.
        """
        # Step 1: Direct Match by EAN (Highest Priority)
        direct = cls._direct_match(item, tenant, supplier)
        if direct.confidence >= Decimal('0.98'):
            return direct

        # Step 2: Existing Supplier Map
        mapping = cls._check_supplier_map(item, tenant, supplier)
        if mapping and mapping.confidence >= Decimal('0.95'):
            return mapping

        # Step 3: Check for existing AI suggestions (from Whole-Invoice Processing)
        existing_suggestion = getattr(item, 'ai_suggestion', None)
        if existing_suggestion and existing_suggestion.get('group_info'):
            return cls._match_from_group_info(item, tenant, supplier, existing_suggestion['group_info'])

        # Step 4: Local Smart Parsing (Works offline)
        parsed = cls._local_parsing(item, tenant)

        # Step 5: Try AI Enhancement (Optional - graceful degradation)
        ai_enhanced = cls._try_ai_enhancement(item, tenant, supplier, parsed)

        return ai_enhanced if ai_enhanced.confidence > parsed.confidence else parsed

    @classmethod
    def _match_from_group_info(cls, item, tenant, supplier, group_info) -> MatchResult:
        """Uses pre-calculated AI grouping info to match or suggest."""
        parent_name = group_info.get('parent_name')
        attr_value = group_info.get('attr_value')
        attribute = group_info.get('attribute', 'Cor')

        if not parent_name:
            return MatchResult(Decimal('0'), 'ERROR', logic="❌ Erro: Agrupamento IA sem nome do pai.")

        # Try to find parent by name (prefer exact, then contains)
        parent = Product.objects.filter(
            Q(name__iexact=parent_name) | Q(name__icontains=parent_name),
            tenant=tenant,
            is_active=True,
            product_type='VARIABLE'
        ).first()

        # If parent found, check if variant already exists with these attributes
        variant = None
        if parent:
            from apps.products.models import ProductVariant, VariantAttributeValue
            # Find variants of this parent that have an attribute value matching the AI suggestion
            variant_ids = VariantAttributeValue.objects.filter(
                variant__product=parent,
                attribute_type__name__iexact=attribute,
                value__iexact=attr_value
            ).values_list('variant_id', flat=True)

            if variant_ids:
                variant = ProductVariant.objects.filter(id__in=variant_ids, is_active=True).first()

        logic = f"🔗 Agrupamento IA: {parent_name} ({attribute}: {attr_value})"
        if variant:
            logic += " | ✓ Variante existente encontrada"
        elif parent:
            logic += " | ⚠ Produto pai encontrado, mas variação é nova"
        else:
            logic += " | ⚠ Necessário cadastrar Pain + Variação"

        return MatchResult(
            confidence=Decimal('0.95'),
            action='AI_GROUP_MATCH',
            product=parent,
            variant=variant,
            logic=logic,
            suggestion_data={
                'suggested_name': parent_name,
                'detected_attributes': {attribute: attr_value},
                'match_type': 'VARIANT_OF',
                'is_group_match': True
            }
        )

    @staticmethod
    def _direct_match(item: Any, tenant, supplier=None) -> MatchResult:
        """Checks barcodes globally across the tenant."""
        ean = getattr(item, 'ean', None) or getattr(item, 'supplier_ean', None)

        if ean and ean.strip() not in ['SEM GTIN', '0', '', 'SEM EAN', '0000000000000', 'null']:
            # Check Variants first
            v = ProductVariant.objects.filter(tenant=tenant, barcode=ean, is_active=True).first()
            if v:
                return MatchResult(
                    Decimal('1.0'), 'DIRECT',
                    product=v.product, variant=v,
                    logic=f"✓ Match exato por EAN: {ean}"
                )

            p = Product.objects.filter(tenant=tenant, barcode=ean, product_type='SIMPLE', is_active=True).first()
            if p:
                return MatchResult(
                    Decimal('1.0'), 'DIRECT',
                    product=p,
                    logic=f"✓ Match exato por EAN: {ean}"
                )

        return MatchResult(Decimal('0'), 'NONE')

    @staticmethod
    def _check_supplier_map(item: Any, tenant, supplier) -> Optional[MatchResult]:
        """Checks if this supplier SKU was previously mapped."""
        if not supplier:
            return None

        sku = getattr(item, 'supplier_sku', None)
        if not sku:
            return None

        mapping = SupplierProductMap.objects.filter(
            tenant=tenant,
            supplier=supplier,
            supplier_sku=sku
        ).select_related('product', 'variant').first()

        if mapping:
            target = mapping.variant.display_name if mapping.variant else mapping.product.name
            return MatchResult(
                Decimal('0.95'),
                'LEARNED',
                product=mapping.product,
                variant=mapping.variant,
                logic=f"📚 Mapeamento histórico: {sku} → {target}"
            )
        return None

    @classmethod
    def _local_parsing(cls, item: Any, tenant) -> MatchResult:
        """
        Use local intelligence to parse product description.
        Works without any external AI service.
        """
        desc = getattr(item, 'description', None) or getattr(item, 'supplier_name', '')

        parsed = ProductParser.parse(desc, tenant)

        # Build logic summary
        logic_parts = ["🔍 Análise local"]
        if parsed.get('detected_brand'):
            logic_parts.append(f"Marca: {parsed['detected_brand']}")
        if parsed.get('detected_category'):
            logic_parts.append(f"Categoria: {parsed['detected_category']}")
        if parsed.get('detected_attributes'):
            attrs = ', '.join([f"{k}: {v}" for k, v in parsed['detected_attributes'].items()])
            logic_parts.append(f"Atributos: {attrs}")

        return MatchResult(
            confidence=Decimal(str(parsed['confidence'])),
            action='PARSED',
            product=None,
            variant=None,
            logic=' | '.join(logic_parts),
            suggestion_data={
                **parsed,
                'uom': cls.normalize_uom(getattr(item, 'uom', 'UN'))
            }
        )

    @classmethod
    def _try_ai_enhancement(cls, item: Any, tenant, supplier, parsed_result: MatchResult) -> MatchResult:
        """
        Try to enhance parsing with AI. Falls back gracefully if AI is unavailable.
        """
        desc = getattr(item, 'description', None) or getattr(item, 'supplier_name', '')
        sku = getattr(item, 'supplier_sku', '')

        # Get existing products for context
        candidates = Product.objects.filter(tenant=tenant).only('id', 'name', 'sku')[:15]
        context = [{"id": str(p.id), "name": p.name} for p in candidates]

        # Simplified, focused prompt
        prompt = f"""Analise este produto de NF-e e extraia informações:

PRODUTO: {desc}
SKU: {sku}

PRODUTOS EXISTENTES NO CATÁLOGO:
{json.dumps(context, ensure_ascii=False)}

Retorne JSON:
{{
    "match_type": "NEW" | "VARIANT_OF" | "EXACT",
    "matched_id": "UUID do produto se for match, ou null",
    "parent_product_id": "UUID do pai se for variante, ou null",
    "suggested_name": "Nome limpo e formatado",
    "detected_brand": "Marca detectada ou null",
    "detected_category": "Categoria sugerida ou null",
    "detected_attributes": {{"Cor": "valor", "Tamanho": "valor"}},
    "confidence": 0.0 a 1.0,
    "logic": "Explicação curta"
}}"""

        try:
            response = AIService.call_ai(prompt, schema="json")
            if not response:
                # AI offline - return parsed result
                return parsed_result

            # Parse JSON
            start = response.find('{')
            end = response.rfind('}')
            if start == -1 or end == -1:
                return parsed_result

            data = json.loads(response[start:end+1])
            conf = Decimal(str(data.get('confidence', 0)))

            # Find matched product if any
            product = None
            match_id = data.get('matched_id') or data.get('parent_product_id')
            if match_id:
                product = Product.objects.filter(tenant=tenant, pk=match_id).first()

            return MatchResult(
                confidence=conf,
                action='AI_SUGGESTION',
                product=product,
                logic=f"🤖 {data.get('logic', 'Análise IA')}",
                suggestion_data=data
            )

        except Exception as e:
            logger.warning(f"AI enhancement failed, using local parsing: {e}")
            return parsed_result
