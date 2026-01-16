"""
Employee views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages

from ..models import StockMovement
from ..forms import EmployeeForm


@login_required
def employee_list(request):
    employees = User.objects.filter(is_active=True).order_by('username')
    return render(request, 'core/employee_list.html', {'employees': employees})


@login_required
def employee_create(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data['password'])
            user.save()
            messages.success(request, f"Funcionário '{user.username}' criado!")
            return redirect('employee_list')
    else:
        form = EmployeeForm()
    return render(request, 'core/employee_form.html', {'form': form})


def employee_detail(request, user_id):
    employee = get_object_or_404(User, id=user_id)
    movements = StockMovement.objects.filter(tenant=request.tenant, user=employee).order_by('-created_at')[:50]
    return render(request, 'core/employee_detail.html', {'employee': employee, 'movements': movements})
