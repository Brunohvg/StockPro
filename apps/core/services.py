from typing import Optional
from decimal import Decimal
from django.db import transaction
from django.conf import settings
import requests
import json
import re
from decouple import config
from apps.products.models import Product, ProductVariant, ProductType
from apps.inventory.models import StockMovement


class AIService:
    """Serviço unificado de IA com suporte a múltiplos provedores (V2+)"""

    @staticmethod
    def get_providers():
        return {
            'groq': config('GROQ_API_KEY', default=''),
            'gemini': config('GEMINI_API_KEY', default=''),
            'openai': config('OPENAI_API_KEY', default=''),
            'xai': config('XAI_API_KEY', default=''),
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
        model = config('GROQ_MODEL', default='llama-3.1-8b-instant')
        tk = max_tokens or int(config('AI_MAX_TOKENS', default=500))
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
        model = config('GEMINI_MODEL', default='gemini-1.5-flash')
        tk = max_tokens or int(config('AI_MAX_TOKENS', default=500))
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
        model = config('OPENAI_MODEL', default='gpt-4o-mini')
        tk = max_tokens or int(config('AI_MAX_TOKENS', default=500))
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
        model = config('XAI_MODEL', default='grok-2-latest')
        tk = max_tokens or int(config('AI_MAX_TOKENS', default=500))
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
        location_id=None
    ):
        """
        Create a stock movement and update stock.
        """
        from decimal import Decimal
        quantity = Decimal(str(quantity))
        if unit_cost is not None:
            unit_cost = Decimal(str(unit_cost))
        # Resolve by SKU if no direct reference
        if product_sku and not product and not variant:
            # Try variant first (more specific)
            variant = ProductVariant.objects.filter(tenant=tenant, sku=product_sku).first()
            if not variant:
                product = Product.objects.filter(tenant=tenant, sku=product_sku).first()

            if not product and not variant:
                raise ValueError(f"Produto/variação com SKU '{product_sku}' não encontrado.")

        # Determine target
        if variant:
            target = variant
            target_type = 'variant'
        elif product:
            if product.is_variable:
                raise ValueError(f"O produto '{product.sku}' ({product.name}) é variável e exige a especificação de uma variação (tamanho, cor, etc.) para movimentar estoque.")
            target = product
            target_type = 'product'
        else:
            raise ValueError("Deve especificar product, variant ou product_sku.")

        # Lock for update
        if target_type == 'product':
            target = Product.objects.select_for_update().get(pk=target.pk)
        else:
            target = ProductVariant.objects.select_for_update().get(pk=target.pk)

        # Fallback for location_id
        if not location_id:
            from apps.inventory.models import Location
            if target_type == 'product' and target.default_location_id:
                location_id = target.default_location_id
            elif target_type == 'variant' and target.product.default_location_id:
                location_id = target.product.default_location_id
            else:
                default_loc = Location.get_default_for_tenant(tenant)
                if default_loc:
                    location_id = default_loc.id

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
        movement_data = {
            'tenant': tenant,
            'user': user,
            'type': movement_type,
            'quantity': quantity,
            'balance_after': new_stock,
            'reason': reason,
            'source': source,
            'unit_cost': unit_cost,
            'source_doc': source_doc,
            'location_id': location_id,
        }

        if target_type == 'variant':
            movement_data['variant'] = target
        else:
            movement_data['product'] = target

        movement = StockMovement.objects.create(**movement_data)
        return movement

    @staticmethod
    def get_stock_for_product(product):
        """Retorna estoque total para um produto (agregado se variável)"""
        if product.is_simple:
            return product.current_stock
        return sum(v.current_stock for v in product.variants.filter(is_active=True))

    @staticmethod
    def get_low_stock_items(tenant, threshold=None):
        """Retorna itens com estoque baixo"""
        low_stock = []

        # Simple products
        for p in Product.objects.filter(tenant=tenant, product_type=ProductType.SIMPLE, is_active=True):
            if p.current_stock <= p.minimum_stock:
                low_stock.append({'type': 'product', 'item': p})

        # Variants
        for v in ProductVariant.objects.filter(tenant=tenant, is_active=True):
            if v.current_stock <= v.minimum_stock:
                low_stock.append({'type': 'variant', 'item': v})

        return low_stock
