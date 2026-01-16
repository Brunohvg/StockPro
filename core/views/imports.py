"""
Import views - CSV and XML import handling
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages

from ..models import ImportBatch
from ..forms import ImportBatchForm


@login_required
def import_list(request):
    tenant = request.tenant
    imports = ImportBatch.objects.filter(tenant=tenant).order_by('-created_at')

    # Calculate stats for the template
    completed_count = imports.filter(status='COMPLETED').count()
    error_count = imports.filter(status='ERROR').count()

    return render(request, 'core/import_list.html', {
        'imports': imports,
        'completed_count': completed_count,
        'error_count': error_count
    })


@login_required
def import_create(request):
    if request.method == 'POST':
        form = ImportBatchForm(request.POST, request.FILES)
        if form.is_valid():
            batch = form.save(commit=False)
            batch.user = request.user
            batch.tenant = request.tenant
            batch.save()

            from ..tasks import process_import_task
            process_import_task.delay(batch.id)
            messages.info(request, "Arquivo enviado! O processamento iniciará em segundo plano.")

            return redirect('import_list')
    else:
        form = ImportBatchForm()

    return render(request, 'core/import_form.html', {'form': form})


@login_required
def import_detail(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, tenant=request.tenant)
    return render(request, 'core/import_detail.html', {'batch': batch})


@login_required
def delete_import(request, pk):
    batch = get_object_or_404(ImportBatch, pk=pk, tenant=request.tenant)
    if request.method == 'POST':
        batch.delete()
        messages.success(request, "Importação removida.")
    return redirect('import_list')
