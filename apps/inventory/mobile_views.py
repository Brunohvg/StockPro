"""
Mobile Views — Interface otimizada para operadores em chão de loja/almoxarifado.
Acessível em /mobile/ — redireciona automaticamente OPERATOR após login.
"""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.core.services import StockService
from apps.inventory.models import StockMovement
from apps.products.models import ProductVariant


def _get_tenant(request):
    return getattr(request, 'tenant', None)


@login_required
def mobile_home(request):
    """Hub mobile — redireciona para tela de movimentação."""
    return redirect('mobile:move')


@login_required
@require_http_methods(["GET", "POST"])
def mobile_move(request):
    """
    Tela principal de movimentação mobile.
    GET  → exibe formulário
    POST → registra movimento e exibe confirmação
    """
    tenant = _get_tenant(request)
    context = {
        'success': None,
        'error': None,
        'last_movement': None,
        'user_name': request.user.get_full_name() or request.user.username,
        'now': timezone.localtime(timezone.now()),
    }

    if request.method == 'POST':
        movement_type = request.POST.get('type', 'OUT')
        sku = request.POST.get('sku', '').strip()
        quantity_raw = request.POST.get('quantity', '0').strip().replace(',', '.')
        reason = request.POST.get('reason', '').strip() or ('Saída via App' if movement_type == 'OUT' else 'Entrada via App')

        try:
            quantity = float(quantity_raw)
            if quantity <= 0:
                raise ValueError("Quantidade deve ser maior que zero.")

            movement = StockService.create_movement(
                tenant=tenant,
                user=request.user,
                movement_type=movement_type,
                quantity=quantity,
                product_sku=sku,
                reason=reason,
                source='MOBILE_APP',
            )

            # Buscar variante para mostrar nome
            variant = ProductVariant.objects.filter(
                tenant=tenant, sku=sku
            ).select_related('product').first()

            context['success'] = True
            context['last_movement'] = {
                'type': movement_type,
                'type_label': 'ENTRADA' if movement_type == 'IN' else 'SAÍDA',
                'type_color': 'emerald' if movement_type == 'IN' else 'rose',
                'product_name': variant.display_name if variant and hasattr(variant, 'display_name') else (variant.name if variant else sku),
                'sku': sku,
                'quantity': quantity,
                'balance_after': float(movement.balance_after),
                'movement_id': str(movement.id)[:8].upper(),
            }

        except ValueError as e:
            context['error'] = str(e)
        except Exception as e:
            context['error'] = f"Erro ao registrar: {str(e)}"

    # Últimas 5 movimentações do usuário hoje
    today = timezone.localtime(timezone.now()).date()
    context['recent'] = StockMovement.objects.filter(
        tenant=tenant,
        user=request.user,
        created_at__date=today,
    ).select_related('variant__product').order_by('-created_at')[:5]

    return render(request, 'mobile/move.html', context)


@login_required
def mobile_history(request):
    """Histórico de movimentos do usuário logado (últimas 24h)."""
    tenant = _get_tenant(request)
    since = timezone.now() - timezone.timedelta(hours=24)
    movements = StockMovement.objects.filter(
        tenant=tenant,
        user=request.user,
        created_at__gte=since,
    ).select_related('variant__product').order_by('-created_at')[:50]

    return render(request, 'mobile/history.html', {
        'movements': movements,
        'user_name': request.user.get_full_name() or request.user.username,
    })
