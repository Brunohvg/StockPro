from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api import ProductViewSet, StockMovementViewSet
from . import views

router = DefaultRouter()
router.register(r'products', ProductViewSet)
router.register(r'movements', StockMovementViewSet)

urlpatterns = [
    # API
    path('api/v1/', include(router.urls)),

    # Public Pages
    path('', views.landing_page, name='landing'),
    path('signup/', views.signup_view, name='signup'),

    # Dashboard (requires login)
    path('app/', views.dashboard, name='dashboard'),

    # Products
    path('products/', views.product_list, name='product_list'),
    path('products/add/', views.product_create, name='product_create'),
    path('products/<int:pk>/', views.product_detail, name='product_detail'),
    path('products/<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('products/<int:pk>/delete/', views.product_delete, name='product_delete'),

    # Operations
    path('movement/new/', views.create_movement, name='create_movement'),
    path('movement/new/mobile/', views.create_movement_mobile, name='create_movement_mobile'),
    path('movements/history/', views.movement_list, name='movement_list'),

    # Employees
    path('employees/', views.employee_list, name='employee_list'),
    path('employees/add/', views.employee_create, name='employee_create'),
    path('employees/<int:user_id>/', views.employee_detail, name='employee_detail'),

    # Import
    path('imports/', views.import_list, name='import_list'),
    path('imports/new/', views.import_create, name='import_create'),
    path('imports/<uuid:pk>/', views.import_detail, name='import_detail'),
    path('imports/<uuid:pk>/delete/', views.delete_import, name='delete_import'),
    # Categories & Brands
    path('setup/categories-brands/', views.category_brand_list, name='category_brand_list'),
    path('setup/categories/add/', views.category_create, name='category_create'),
    path('setup/brands/add/', views.brand_create, name='brand_create'),
    path('setup/categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('setup/brands/<int:pk>/delete/', views.brand_delete, name='brand_delete'),

    # BI & Business Intelligence
    path('reports/', views.inventory_reports, name='inventory_reports'),
    path('settings/', views.system_settings, name='system_settings'),
]
