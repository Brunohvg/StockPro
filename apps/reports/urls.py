from django.urls import path

from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('analytics/', views.inventory_reports, name='inventory_reports'),
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/<int:user_id>/', views.employee_detail, name='employee_detail'),

    # Export endpoints
    path('export/', views.export_page, name='export_page'),
    path('export/products/csv/', views.export_products_csv, name='export_products_csv'),
    path('export/products/excel/', views.export_products_excel, name='export_products_excel'),
    path('export/products/json/', views.export_products_json, name='export_products_json'),
    path('export/movements/csv/', views.export_movements_csv, name='export_movements_csv'),
]

