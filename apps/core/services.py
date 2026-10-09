from decimal import Decimal, InvalidOperation
from typing import Optional

import requests
import os
from django.db import transaction
from django.db.models import F, Sum

from apps.inventory.models import ExternalOrder, StockMovement
from apps.products.models import Product, ProductType, ProductVariant

from .models import VisualAuditLog


def parse_date_br(value):
    """Aceita date/datetime, 'dd/mm/aaaa', 'dd/mm/aa', 'aaaa-mm-dd' ou vazio. Retorna date ou None."""
    import datetime as _dt
    if value in (None, ''):
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'nat', 'none'):
        return None
    text = text.split(' ')[0]  # '2026-03-01 00:00:00' vindo do Excel
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y', '%d-%m-%Y', '%d.%m.%Y'):
        try:
            return _dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Data inválida: '{value}'. Use dd/mm/aaaa.")


class AIUnavailable(Exception):
    """IA não liberada para a empresa (plano, assinatura ou limite diário)."""

    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


class AIService:
    """Serviço unificado de IA com suporte a múltiplos provedores (V2+)"""

    @staticmethod
    def check_tenant_access(tenant):
        """Levanta AIUnavailable se a empresa não pode usar IA agora."""
        if tenant is None:
            raise AIUnavailable("Empresa não identificada.")
        if tenant.subscription_status in ('SUSPENDED', 'CANCELLED') or tenant.is_trial_expired:
            raise AIUnavailable("Recurso de IA indisponível: assinatura inativa ou período de teste encerrado.")
        plan = tenant.plan
        if not plan or not plan.has_ai_matching:
            raise AIUnavailable("Recurso de IA não disponível no seu plano.")

    @classmethod
    def tenant_has_ai(cls, tenant):
        try:
            cls.check_tenant_access(tenant)
            return True
        except AIUnavailable:
            return False

    @classmethod
    def call_for_tenant(cls, tenant, prompt: str, schema: str = "json", max_tokens: int = None) -> Optional[str]:
        """
        Porta de entrada única para IA paga: confere plano/assinatura e o limite
        diário por empresa (AI_DAILY_LIMIT_PER_TENANT, 0 = sem limite).
        """
        from django.core.cache import cache
        from django.utils import timezone

        cls.check_tenant_access(tenant)
        limit = int(os.environ.get('AI_DAILY_LIMIT_PER_TENANT', '50') or 0)
        if limit > 0:
            key = f"ai-quota:{tenant.pk}:{timezone.localdate():%Y%m%d}"
            cache.add(key, 0, timeout=60 * 60 * 26)
            try:
                used = cache.incr(key)
            except ValueError:  # chave expirou entre o add e o incr
                cache.set(key, 1, timeout=60 * 60 * 26)
                used = 1
            if used > limit:
                raise AIUnavailable(
                    f"Limite diário de {limit} usos de IA atingido. Volta a funcionar amanhã.", status=429)
        return cls.call_ai(prompt, schema=schema, max_tokens=max_tokens)

    @staticmethod
    def get_providers():
        return {
            'groq': os.environ.get('GROQ_API_KEY', ''),
            'gemini': os.environ.get('GEMINI_API_KEY', ''),
            'openai': os.environ.get('OPENAI_API_KEY', ''),
            'xai': os.environ.get('XAI_API_KEY', ''),
        }

    @classmethod
    def call_ai(cls, prompt: str, schema: str = "json", max_tokens: int = None) -> Optional[str]:
        """Tenta chamar provedores de IA em ordem de prioridade com FAILOVER real"""
        keys = cls.get_providers()
        import logging
        logger = logging.getLogger(__name__)

        # Lista de tentativas na ordem de prioridade
        attempts = [
            ('groq', keys['groq'], cls._call_groq),
            ('gemini', keys['gemini'], cls._call_gemini),
            ('openai', keys['openai'], cls._call_openai),
            ('xai', keys['xai'], cls._call_xai),
        ]

        for name, key, func in attempts:
            if not key or 'chave' in key: # Pula se vazio ou se for o placeholder "sua_chave..."
                continue

            try:
                logger.info(f"Tentando IA: {name}")
                result = func(key, prompt, schema, max_tokens)
                if result:
                    return result
                logger.warning(f"Provedor {name} retornou vazio. Tentando próximo...")
            except Exception as e:
                logger.error(f"Erro no provedor {name}: {str(e)}")

        return None

    @staticmethod
    def _call_groq(api_key, prompt, schema, max_tokens=None):
        model = os.environ.get('GROQ_MODEL', 'llama-3.1-8b-instant')
        tk = max_tokens or int(os.environ.get('AI_MAX_TOKENS', '500'))
        response = requests.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": tk,
                "response_format": {"type": "json_object"} if schema == "json" else None
            }, timeout=7)
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content']

        import logging
        logging.getLogger(__name__).error(f"Groq Error {response.status_code}: {response.text}")
        return None

    @staticmethod
    def _call_gemini(api_key, prompt, schema, max_tokens=None):
        model = os.environ.get('GEMINI_MODEL', 'gemini-1.5-flash')
        tk = max_tokens or int(os.environ.get('AI_MAX_TOKENS', '500'))
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        response = requests.post(url, json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "max_output_tokens": tk,
                "response_mime_type": "application/json" if schema == "json" else "text/plain"
            }
        }, timeout=10)
        if response.status_code == 200:
            return response.json()['candidates'][0]['content']['parts'][0]['text']

        import logging
        logging.getLogger(__name__).error(f"Gemini Error {response.status_code}: {response.text}")
        return None

    @staticmethod
    def _call_openai(api_key, prompt, schema, max_tokens=None):
        model = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')
        tk = max_tokens or int(os.environ.get('AI_MAX_TOKENS', '500'))
        response = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": tk,
                "response_format": {"type": "json_object"} if schema == "json" else None
            }, timeout=10)
        return response.json()['choices'][0]['message']['content'] if response.status_code == 200 else None

    @staticmethod
    def _call_xai(api_key, prompt, schema, max_tokens=None):
        model = os.environ.get('XAI_MODEL', 'grok-2-latest')
        tk = max_tokens or int(os.environ.get('AI_MAX_TOKENS', '500'))
        response = requests.post("https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": tk
            }, timeout=10)
        return response.json()['choices'][0]['message']['content'] if response.status_code == 200 else None


class StockService:
    @staticmethod
    @transaction.atomic
    def create_movement(
        tenant,
        user,
        movement_type,
        quantity,
        product=None,
        variant=None,
        product_sku=None,
        reason='',
        source='MANUAL',
        unit_cost=None,
        source_doc=None,
        location_id=None,
        external_order=None, # ExternalOrder instance
        external_order_id=None, # String for resolving/creating
        lot_number=None,        # Lote (entrada/ajuste)
        expiry_date=None,       # Validade: date ou 'dd/mm/aaaa' / 'aaaa-mm-dd'
        manufacture_date=None,  # Fabricação
        lot_id=None,            # Saída de um lote específico (senão FEFO)
        allow_expired_lot=False, # Exclusivamente para estornos internos auditados
    ):
        """
        Create a stock movement and update stock.
        """
        if tenant is None:
            raise ValueError("Movimentação exige uma empresa (tenant) definida.")
        if movement_type not in ('IN', 'OUT', 'ADJ'):
            raise ValueError(f"Tipo de movimento inválido: {movement_type}")
        try:
            quantity = Decimal(str(quantity))
            if unit_cost is not None:
                unit_cost = Decimal(str(unit_cost))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Quantidade ou custo inválido.")
        if not quantity.is_finite():
            raise ValueError("Quantidade inválida.")
        if movement_type == 'ADJ':
            if quantity < 0:
                raise ValueError("Ajuste absoluto não pode ser negativo.")
        elif quantity <= 0:
            raise ValueError("Quantidade deve ser maior que zero.")
        if unit_cost is not None and (not unit_cost.is_finite() or unit_cost < 0):
            raise ValueError("Custo unitário não pode ser negativo.")
        expiry_date = parse_date_br(expiry_date)
        manufacture_date = parse_date_br(manufacture_date)
        lot_number = (str(lot_number).strip()[:60] if lot_number else '')
        if expiry_date and manufacture_date and manufacture_date > expiry_date:
            raise ValueError("Data de fabricação posterior à validade.")
        # Resolve by SKU if no direct reference
        if product_sku and not product and not variant:
            # Try variant first (more specific)
            variant = ProductVariant.objects.filter(tenant=tenant, sku=product_sku).first()
            if not variant:
                product = Product.objects.filter(tenant=tenant, sku=product_sku).first()

            if not product and not variant:
                raise ValueError(f"Produto/variação com SKU '{product_sku}' não encontrado.")

        if product is not None and product.tenant_id != tenant.pk:
            raise ValueError("Produto não pertence a esta empresa.")

        # Determine target - ALWAYS resolve to variant
        if not variant and product:
            # If product is SIMPLE, it must have at least one variant (auto-created by save)
            variant = product.variants.first()
            if not variant:
                # Fallback for unexpected state where variant missing
                if product.is_simple:
                    variant = ProductVariant.objects.create(
                        product=product, tenant=tenant, sku=product.sku, name="Padrão"
                    )
                else:
                    raise ValueError(f"O produto '{product.sku}' é variável e exige a especificação de uma variação.")

        if not variant:
            raise ValueError("Deve especificar uma variante válida ou um produto simples com SKU.")

        # Lock variant for update (sempre dentro da empresa informada)
        target = ProductVariant.objects.select_for_update().filter(pk=variant.pk, tenant=tenant).first()
        if target is None:
            raise ValueError("Variação não pertence a esta empresa.")
        if not target.is_active or not target.product.is_active:
            raise ValueError(
                f"O produto '{target.sku}' está arquivado. Reative-o antes de movimentar o estoque.")

        # Location precisa pertencer à mesma empresa
        if location_id:
            from apps.inventory.models import Location
            if not Location.objects.filter(pk=location_id, tenant=tenant).exists():
                raise ValueError("Local de estoque inválido para esta empresa.")

        # Fallback for location_id
        if not location_id:
            from apps.inventory.models import Location
            if target.product.default_location_id:
                location_id = target.product.default_location_id
            else:
                default_loc = Location.get_default_for_tenant(tenant)
                if default_loc:
                    location_id = default_loc.id

        # E-commerce Order Resolution
        if external_order_id and not external_order:
            external_order, _ = ExternalOrder.objects.get_or_create(
                tenant=tenant,
                platform=source if source != 'MANUAL' else 'API',
                external_order_id=external_order_id
            )

        # Snapshot for Visual Audit (Before)
        before_state = {
            'current_stock': float(target.current_stock),
            'avg_unit_cost': float(target.avg_unit_cost) if target.avg_unit_cost else None
        }

        old_stock = target.current_stock

        # Calculate new stock
        if movement_type == 'IN':
            new_stock = target.current_stock + quantity
            if unit_cost:
                # Weighted average cost update
                total_current_value = (target.current_stock or 0) * (target.avg_unit_cost or 0)
                total_new_value = quantity * unit_cost
                if new_stock > 0:
                    target.avg_unit_cost = (total_current_value + total_new_value) / new_stock
        elif movement_type == 'OUT':
            new_stock = target.current_stock - quantity
            if new_stock < 0:
                raise ValueError(f"Estoque insuficiente para {target.sku}. Disponível: {target.current_stock}")
        elif movement_type == 'ADJ':
            new_stock = quantity  # Absolute adjustment
        else:
            raise ValueError(f"Tipo de movimento inválido: {movement_type}")

        target.current_stock = new_stock
        target._allow_stock_change = True  # Unlock ledger for this authorized movement
        target.save()

        # Create immutable movement record
        movement = StockMovement.objects.create(
            tenant=tenant,
            user=user,
            variant=target,
            product=target.product,
            type=movement_type,
            quantity=quantity,
            balance_after=new_stock,
            reason=reason,
            source=source,
            unit_cost=unit_cost,
            source_doc=source_doc,
            location_id=location_id,
            external_order=external_order,
        )

        # Lotes / validade (FEFO)
        allocations = StockService._apply_lots(
            tenant, target, movement_type, quantity, new_stock,
            lot_number, expiry_date, manufacture_date, lot_id, allow_expired_lot,
        )
        if allocations:
            from apps.inventory.models import MovementLot
            MovementLot.objects.bulk_create([
                MovementLot(movement=movement, lot=lot, quantity=qty) for lot, qty in allocations
            ])

        # Visual Audit (After & Diff)
        after_state = {
            'current_stock': float(target.current_stock),
            'avg_unit_cost': float(target.avg_unit_cost) if target.avg_unit_cost else None,
            'movement_id': str(movement.id)
        }

        diff = {
            'stock_change': float(quantity) if movement_type != 'OUT' else -float(quantity)
        }

        VisualAuditLog.objects.create(
            tenant=tenant,
            user=user,
            entity_type='STOCK',
            entity_id=str(target.pk),
            action='UPDATE',
            source=source,
            before_state=before_state,
            after_state=after_state,
            diff=diff,
            external_ref=external_order_id or (external_order.external_order_id if external_order else None)
        )

        return movement

    @staticmethod
    def _apply_lots(tenant, target, movement_type, quantity, new_stock,
                    lot_number, expiry_date, manufacture_date, lot_id, allow_expired_lot=False):
        """
        Atualiza os lotes da variação. Retorna [(lote, quantidade)] para auditoria.

        - IN: soma no lote informado (cria se preciso). Sem dados de lote, vira saldo "sem lote".
        - OUT: lote informado ou FEFO (vence antes, sai antes); o que faltar sai do saldo sem lote.
        - ADJ: com dados de lote, o lote passa a ter todo o saldo (contagem de inventário);
          sem dados, se o novo saldo ficar abaixo da soma dos lotes, reduz pelos que vencem antes.
        """
        from apps.inventory.models import StockLot

        product = target.product
        has_lot_info = bool(lot_number or expiry_date or lot_id)
        if has_lot_info and not product.tracks_expiry:
            Product.objects.filter(pk=product.pk).update(tracks_expiry=True)
            product.tracks_expiry = True
        if not product.tracks_expiry:
            return []

        lots = StockLot.objects.select_for_update().filter(variant=target)

        def get_lot():
            if lot_id:
                lot = lots.filter(pk=lot_id).first()
                if lot is None:
                    raise ValueError("Lote não encontrado para esta variação.")
                return lot
            if not (lot_number or expiry_date):
                return None
            lot, _ = StockLot.objects.get_or_create(
                tenant=tenant, variant=target, lot_number=lot_number, expiry_date=expiry_date,
                defaults={'manufacture_date': manufacture_date},
            )
            if manufacture_date and not lot.manufacture_date:
                lot.manufacture_date = manufacture_date
            return lot

        def consume_fefo(amount, include_expired=True):
            from django.utils import timezone
            from django.db.models import Q
            taken = []
            eligible = lots.filter(quantity__gt=0)
            if not include_expired:
                eligible = eligible.filter(Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate()))
            for lot in eligible.order_by(
                F('expiry_date').asc(nulls_last=True), 'created_at'
            ):
                if amount <= 0:
                    break
                q = min(lot.quantity, amount)
                lot.quantity -= q
                lot.save(update_fields=['quantity', 'updated_at'])
                taken.append((lot, q))
                amount -= q
            return taken

        if movement_type == 'IN':
            lot = get_lot()
            if lot is None:
                return []
            lot.quantity += quantity
            lot.save()
            return [(lot, quantity)]

        if movement_type == 'OUT':
            from django.utils import timezone
            from django.db.models import Q
            if lot_id:
                lot = get_lot()
                if not allow_expired_lot and lot.expiry_date is not None and lot.expiry_date < timezone.localdate():
                    raise ValueError('Não é permitido consumir lote vencido. Registre descarte ou ajuste.')
                if lot.quantity < quantity:
                    raise ValueError(f"Lote {lot.lot_number or lot.pk} tem só {lot.quantity} disponível.")
                lot.quantity -= quantity
                lot.save(update_fields=['quantity', 'updated_at'])
                return [(lot, quantity)]
            total_lots = lots.aggregate(t=Sum('quantity'))['t'] or Decimal('0')
            untracked = max(Decimal('0'), new_stock + quantity - total_lots)
            eligible_qty = lots.filter(quantity__gt=0).filter(
                Q(expiry_date__isnull=True) | Q(expiry_date__gte=timezone.localdate())
            ).aggregate(t=Sum('quantity'))['t'] or Decimal('0')
            if quantity > untracked + eligible_qty:
                raise ValueError('Saldo disponível insuficiente: existem lotes vencidos bloqueados para saída.')
            return consume_fefo(quantity, include_expired=False)

        # ADJ
        lot = get_lot()
        if lot is not None:
            changes = []
            for other in lots.exclude(pk=lot.pk).filter(quantity__gt=0):
                changes.append((other, -other.quantity))
                other.quantity = 0
                other.save(update_fields=['quantity', 'updated_at'])
            delta = new_stock - lot.quantity
            lot.quantity = new_stock
            lot.save()
            if delta:
                changes.append((lot, delta))
            return changes
        total = lots.aggregate(t=Sum('quantity'))['t'] or Decimal('0')
        if new_stock < total:
            return [(lot, -q) for lot, q in consume_fefo(total - new_stock)]
        return []

    @staticmethod
    def get_stock_for_product(product):
        """Retorna estoque total para um produto (agregado de todas as variantes)"""
        return sum(v.current_stock for v in product.variants.all())

    @staticmethod
    def get_low_stock_items(tenant, threshold=None):
        """Retorna variantes com estoque baixo"""
        low_stock = []
        for v in ProductVariant.objects.filter(tenant=tenant, is_active=True):
            if v.current_stock <= v.minimum_stock:
                low_stock.append({'type': 'variant', 'item': v})
        return low_stock
