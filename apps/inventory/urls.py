from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('movements/', views.movement_list, name='movement_list'),
    path('movements/add/', views.create_movement, name='create_movement'),
    path('movements/mobile/', views.create_movement_mobile, name='create_movement_mobile'),
    path('imports/', views.import_list, name='import_list'),
    path('imports/new/', views.import_create, name='import_create'),
    path('imports/<uuid:pk>/', views.import_detail, name='import_detail'),
    path('imports/<uuid:pk>/delete/', views.delete_import, name='delete_import'),
]
