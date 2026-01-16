from django.urls import path
from . import views

app_name = 'products'

urlpatterns = [
    path('', views.product_list, name='product_list'),
    path('add/', views.product_create, name='product_create'),
    path('<int:pk>/', views.product_detail, name='product_detail'),
    path('<int:pk>/edit/', views.product_edit, name='product_edit'),
    path('<int:pk>/delete/', views.product_delete, name='product_delete'),
    path('categories/', views.category_brand_list, name='category_brand_list'),
    path('categories/add/', views.category_create, name='category_create'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('brands/add/', views.brand_create, name='brand_create'),
    path('brands/<int:pk>/delete/', views.brand_delete, name='brand_delete'),
]
