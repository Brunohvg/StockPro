from django.urls import path

from . import views

app_name = 'partners'

urlpatterns = [
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/add/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),
    path('api/suppliers/search/', views.supplier_search_api, name='supplier_search_api'),
]
