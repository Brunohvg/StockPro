"""
Product Exporter - Multi-format export for products and movements
"""
import csv
import io
import json
from datetime import datetime
from decimal import Decimal

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from apps.products.models import Product, ProductType


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


class ProductExporter:
    """
    Exporta o catálogo no MESMO formato do modelo de importação (CATALOG_SPEC):
    uma linha por item vendável. Produto simples = 1 linha; produto com
    variação = 1 linha por variação, com sku_pai e atributos ("Cor:Azul").
    O arquivo exportado pode ser editado e importado de volta sem perder nada.
    """

    def __init__(self, tenant):
        self.tenant = tenant

    @staticmethod
    def columns():
        from apps.inventory.services.template_xlsx import CATALOG_SPEC
        return [c[0] for c in CATALOG_SPEC]

    def get_products(self, include_inactive=False):
        """Fetch all products with variants"""
        qs = Product.objects.filter(tenant=self.tenant).select_related(
            'category', 'brand', 'default_supplier', 'default_location',
        ).prefetch_related(
            'variants', 'variants__attribute_values', 'variants__attribute_values__attribute_type'
        )
        if not include_inactive:
            qs = qs.filter(is_active=True)
        return qs.order_by('name')

    @staticmethod
    def _variants(product, include_inactive=False):
        variants = [v for v in product.variants.all() if include_inactive or v.is_active]
        return sorted(variants, key=lambda v: (v.sku or '', v.pk))

    @staticmethod
    def _attributes(variant):
        values = sorted(variant.attribute_values.all(), key=lambda a: a.attribute_type.name.lower())
        return '; '.join(f"{a.attribute_type.name}:{a.value}" for a in values if a.value)

    def _row(self, product, variant):
        """Linha no formato do modelo de importação."""
        supplier = product.default_supplier
        is_variable = product.product_type == ProductType.VARIABLE
        sale_price = (variant.sale_price if variant and variant.sale_price is not None else product.sale_price)
        if is_variable:
            name = variant.display_name
        else:
            name = product.name
        barcode = ((variant.barcode if variant else None) or product.barcode or '') if not is_variable \
            else (variant.barcode or '')
        return {
            'nome': name,
            'sku': (variant.sku if variant else product.sku) or '',
            'categoria': product.category.name if product.category else '',
            'marca': product.brand.name if product.brand else '',
            'unidade': product.uom or '',
            'codigo_barras': barcode,
            'custo': variant.avg_unit_cost if variant else None,
            'preco_venda': sale_price,
            'estoque': variant.current_stock if variant else Decimal('0'),
            'estoque_minimo': variant.minimum_stock if variant else Decimal('0'),
            'validade': '',
            'lote': '',
            'fabricacao': '',
            'fornecedor': (supplier.trade_name or supplier.company_name) if supplier else '',
            'cnpj': supplier.cnpj if supplier else '',
            'local': product.default_location.name if product.default_location else '',
            'sku_pai': product.sku if is_variable else '',
            'atributos': self._attributes(variant) if is_variable and variant else '',
            'descricao_detalhada': product.description or '',
        }

    def rows(self, include_variants=True, include_inactive=False):
        for product in self.get_products(include_inactive):
            if product.product_type == ProductType.SIMPLE:
                variants = self._variants(product, include_inactive=True)
                yield self._row(product, variants[0] if variants else None)
            elif include_variants:
                for variant in self._variants(product, include_inactive):
                    yield self._row(product, variant)

    @staticmethod
    def _number_text(value):
        """Número para CSV no padrão brasileiro, sem casas desnecessárias (12,5 / 40)."""
        if value is None or value == '':
            return ''
        d = Decimal(value).normalize()
        text = format(d, 'f')
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return text.replace('.', ',')

    NUMERIC = ('custo', 'preco_venda', 'estoque', 'estoque_minimo')

    def export_csv(self, include_variants=True, include_inactive=False):
        """CSV com ';' e vírgula decimal (abre direto no Excel em português)."""
        columns = self.columns()
        output = io.StringIO()
        output.write('\ufeff')  # BOM: o Excel reconhece UTF-8 e mantém os acentos
        writer = csv.writer(output, delimiter=';', lineterminator='\r\n')
        writer.writerow(columns)
        for row in self.rows(include_variants, include_inactive):
            writer.writerow([
                self._number_text(row[c]) if c in self.NUMERIC else row[c]
                for c in columns
            ])
        return output.getvalue()

    def export_excel(self, include_variants=True, include_inactive=False):
        """Planilha .xlsx com aba "Produtos" igual à do modelo de importação."""
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl não instalado. Execute: pip install openpyxl")
        from openpyxl.styles import Alignment
        from openpyxl.utils import get_column_letter
        from apps.inventory.services.template_xlsx import (
            CATALOG_SPEC, HEADER_FILL, HEADER_FONT, OPTIONAL_LOT_FILL, REQUIRED_FILL,
        )

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Produtos"
        for col, (name, required, width, fmt, _help, _ex) in enumerate(CATALOG_SPEC, start=1):
            cell = ws.cell(row=1, column=col, value=name)
            cell.font = HEADER_FONT
            cell.fill = REQUIRED_FILL if required else (
                OPTIONAL_LOT_FILL if name in ('validade', 'lote', 'fabricacao') else HEADER_FILL)
            cell.alignment = Alignment(horizontal='center', vertical='center')
            ws.column_dimensions[get_column_letter(col)].width = width
        ws.freeze_panes = 'A2'

        formats = {c[0]: c[3] for c in CATALOG_SPEC}
        for r, row in enumerate(self.rows(include_variants, include_inactive), start=2):
            for c, name in enumerate(formats, start=1):
                value = row[name]
                if value is None or value == '':
                    continue
                if name in self.NUMERIC:
                    value = float(value)
                cell = ws.cell(row=r, column=c, value=value)
                if formats[name]:
                    cell.number_format = formats[name]

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output.getvalue()

    def export_json(self, include_variants=True, include_inactive=False):
        """JSON aninhado: o produto e, dentro dele, as variações."""
        result = []
        for product in self.get_products(include_inactive):
            supplier = product.default_supplier
            item = {
                'sku': product.sku,
                'name': product.name,
                'type': product.product_type,
                'category': product.category.name if product.category else None,
                'brand': product.brand.name if product.brand else None,
                'uom': product.uom,
                'description': product.description,
                'sale_price': product.sale_price,
                'supplier': {
                    'name': supplier.trade_name or supplier.company_name,
                    'cnpj': supplier.cnpj,
                } if supplier else None,
                'location': product.default_location.name if product.default_location else None,
                'is_active': product.is_active,
            }

            variants = self._variants(product, include_inactive=product.is_simple or include_inactive)
            if product.product_type == ProductType.SIMPLE:
                variant = variants[0] if variants else None
                item['barcode'] = ((variant.barcode if variant else None) or product.barcode) or ''
                item['stock'] = variant.current_stock if variant else 0
                item['minimum_stock'] = variant.minimum_stock if variant else 0
                item['cost'] = self._cost(product, variant)
            else:
                item['variants'] = []
                if include_variants:
                    for variant in variants:
                        item['variants'].append({
                            'sku': variant.sku,
                            'name': variant.display_name,
                            'barcode': variant.barcode,
                            'stock': variant.current_stock,
                            'minimum_stock': variant.minimum_stock,
                            'cost': self._cost(product, variant),
                            'sale_price': variant.sale_price if variant.sale_price is not None else product.sale_price,
                            'is_active': variant.is_active,
                            'attributes': {
                                a.attribute_type.name: a.value for a in variant.attribute_values.all()
                            },
                        })
            result.append(item)

        return json.dumps(result, indent=2, cls=DecimalEncoder, ensure_ascii=False)

    @staticmethod
    def _cost(product, variant):
        """Custo médio da variação; sem ele, o custo médio antigo do produto."""
        if variant is not None and variant.avg_unit_cost is not None:
            return variant.avg_unit_cost
        return product.avg_unit_cost

    def export_movements_csv(self, days=30):
        """Export stock movements to CSV"""
        from django.utils import timezone
        from apps.inventory.models import StockMovement

        start_date = timezone.now().date() - timezone.timedelta(days=days)

        movements = StockMovement.objects.filter(
            tenant=self.tenant,
            created_at__date__gte=start_date
        ).select_related('product', 'variant', 'variant__product', 'user').order_by('-created_at')

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Data', 'Hora', 'Tipo', 'SKU', 'Produto', 'Quantidade', 'Saldo', 'Custo Unit.', 'Operador', 'Motivo'])

        for mov in movements:
            if mov.variant:
                sku = mov.variant.sku
                name = mov.variant.display_name
            elif mov.product:
                sku = mov.product.sku
                name = mov.product.name
            else:
                sku = '-'
                name = '(Removido)'

            writer.writerow([
                mov.created_at.strftime('%Y-%m-%d'),
                mov.created_at.strftime('%H:%M:%S'),
                mov.get_type_display(),
                sku,
                name,
                mov.quantity,
                mov.balance_after,
                float(mov.unit_cost) if mov.unit_cost else '',
                mov.user.username if mov.user else 'Sistema',
                mov.reason or ''
            ])

        return output.getvalue()
