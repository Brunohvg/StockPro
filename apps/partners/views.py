from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.tenants.middleware import admin_required, trial_allows_read

from .forms import SupplierForm
from .models import Supplier


@login_required
@admin_required
def supplier_list(request):
    """List all suppliers for the tenant"""
    tenant = request.tenant
    suppliers = Supplier.objects.filter(tenant=tenant).order_by('trade_name', 'company_name')
    return render(request, 'partners/supplier_list.html', {'suppliers': suppliers})

@login_required
@admin_required
@trial_allows_read
def supplier_create(request):
    """Create a new supplier"""
    if request.method == 'POST':
        form = SupplierForm(request.POST, tenant=request.tenant)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.tenant = request.tenant
            supplier.save()
            messages.success(request, f"Fornecedor '{supplier.display_name}' cadastrado!")
            return redirect('partners:supplier_list')
    else:
        form = SupplierForm(tenant=request.tenant)
    return render(request, 'partners/supplier_form.html', {'form': form})

@login_required
@admin_required
@trial_allows_read
def supplier_edit(request, pk):
    """Edit an existing supplier"""
    supplier = get_object_or_404(Supplier, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier, tenant=request.tenant)
        if form.is_valid():
            form.save()
            messages.success(request, f"Fornecedor '{supplier.display_name}' atualizado!")
            return redirect('partners:supplier_list')
    else:
        form = SupplierForm(instance=supplier, tenant=request.tenant)
    return render(request, 'partners/supplier_form.html', {'form': form, 'supplier': supplier})


@login_required
@admin_required
def supplier_delete(request, pk):
    """Delete a supplier"""
    from django.db.models import ProtectedError
    supplier = get_object_or_404(Supplier, pk=pk, tenant=request.tenant)

    if request.method == 'POST':
        name = supplier.display_name
        try:
            supplier.delete()
            messages.success(request, f"Fornecedor '{name}' excluído com sucesso!")
        except ProtectedError:
            messages.error(request, f"Não é possível excluir '{name}' pois existem produtos ou mapeamentos vinculados. Desative o fornecedor ao invés de excluí-lo.")

    return redirect('partners:supplier_list')


from django.db.models import Q
from django.http import JsonResponse


@login_required
def supplier_search_api(request):
    """API para busca rápida de fornecedores (autocomplete)"""
    query = request.GET.get('q', '')
    tenant = request.tenant

    suppliers = Supplier.objects.filter(tenant=tenant).filter(
        Q(trade_name__icontains=query) |
        Q(company_name__icontains=query) |
        Q(cnpj__icontains=query)
    ).order_by('trade_name', 'company_name')[:15]

    results = []
    for s in suppliers:
        results.append({
            'id': s.id,
            'name': s.display_name,
            'cnpj': s.cnpj,
            'display': f"{s.display_name} ({s.cnpj})"
        })

    return JsonResponse({'results': results})


from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from apps.core.api.tenant import HasActiveTenant


class SupplierCNPJLookupView(APIView):
    permission_classes = [IsAuthenticated, HasActiveTenant]
    throttle_scope = 'cnpj'

    def get(self, request):
        if request.membership.role not in ('OWNER', 'ADMIN'):
            return Response({'error': 'Consulta restrita a administradores.'}, status=403)
        from .cnpj_lookup import CNPJLookupError, lookup_cnpj
        try:
            return Response(lookup_cnpj(request.query_params.get('cnpj', '')))
        except ValidationError:
            return Response({'error': 'CNPJ inválido. Confira os 14 dígitos.'}, status=400)
        except CNPJLookupError as exc:
            return Response({'error': str(exc)}, status=exc.status)
