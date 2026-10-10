"""
Corrige o nome das variações gravadas como "Produto -" (sem o atributo).

O formulário antigo de nova variação vinha preenchido com "Produto - " e o
nome era gravado antes dos atributos. Este comando troca esses nomes
provisórios pelo nome montado com os atributos ("Produto - Azul").
Nomes digitados pelo usuário não são alterados.

    python manage.py fix_variant_names            # mostra o que mudaria
    python manage.py fix_variant_names --apply    # grava
    python manage.py fix_variant_names --tenant bibelo --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.products.models import ProductType, ProductVariant


class Command(BaseCommand):
    help = 'Corrige nomes de variação gravados sem o atributo ("Produto -").'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Grava as mudanças (sem isso, só mostra).')
        parser.add_argument('--tenant', help='Slug ou id da empresa (padrão: todas).')

    def handle(self, *args, **opts):
        qs = ProductVariant.objects.filter(product__product_type=ProductType.VARIABLE) \
            .select_related('product', 'tenant').order_by('tenant_id', 'product__name', 'sku')
        if opts.get('tenant'):
            key = opts['tenant']
            qs = qs.filter(tenant__slug=key) if not str(key).isdigit() else qs.filter(tenant_id=int(key))

        changed = 0
        with transaction.atomic():
            for variant in qs.iterator():
                if not variant.has_placeholder_name():
                    continue
                new_name = variant.auto_name()
                if not new_name or new_name == variant.name:
                    continue
                changed += 1
                self.stdout.write(f"{variant.tenant} | {variant.sku}: '{variant.name}' -> '{new_name}'")
                if opts['apply']:
                    ProductVariant.objects.filter(pk=variant.pk).update(name=new_name)

        if opts['apply']:
            self.stdout.write(self.style.SUCCESS(f"{changed} variação(ões) renomeada(s)."))
        else:
            self.stdout.write(self.style.WARNING(
                f"{changed} variação(ões) seriam renomeadas. Rode com --apply para gravar."))
