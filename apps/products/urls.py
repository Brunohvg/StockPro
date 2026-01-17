from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    # Products
    path('', views.product_list, name='product_list'),
    path('add/', views.product_create, name='product_create'),
    path('<int:pk>/', views.product_detail, name='product_detail'),
    path('<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('bulk-delete/', views.bulk_delete, name='bulk_delete'),

    # Variants
    path('<int:product_pk>/variants/add/', views.variant_create, name='variant_create'),
    path('variants/<int:pk>/edit/', views.variant_edit, name='variant_edit'),
    path('variants/<int:pk>/delete/', views.variant_delete, name='variant_delete'),

    # Categories, Brands & Attributes
    path('settings/', views.category_brand_list, name='category_brand_list'),
    path('categories/add/', views.category_create, name='category_create'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('brands/add/', views.brand_create, name='brand_create'),
    path('brands/<int:pk>/delete/', views.brand_delete, name='brand_delete'),
    path('attributes/add/', views.attribute_type_create, name='attribute_type_create'),
    path('attributes/<int:pk>/delete/', views.attribute_type_delete, name='attribute_type_delete'),

    # API
    path('api/search/', views.product_search_api, name='product_search_api'),
    path('api/ai-enhance/', views.ai_enhance_product_api, name='ai_enhance_product_api'),

    # Consolidation
    path('consolidation/', views.consolidation_suggestions, name='consolidation_suggestions'),
    path('consolidation/execute/', views.consolidation_execute, name='consolidation_execute'),
]
