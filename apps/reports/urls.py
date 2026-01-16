from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('analytics/', views.inventory_reports, name='inventory_reports'),
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/<int:user_id>/', views.employee_detail, name='employee_detail'),
]
