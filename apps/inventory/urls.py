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
    path('imports/bulk-delete/', views.bulk_delete_imports, name='bulk_delete_imports'),
    path('imports/template/', views.download_csv_template, name='download_csv_template'),
    path('imports/<uuid:pk>/reprocess/', views.import_reprocess, name='import_reprocess'),

    # Locations (V2)
    path('locations/', views.location_list, name='location_list'),
    path('locations/add/', views.location_create, name='location_create'),
    path('locations/<int:pk>/edit/', views.location_edit, name='location_edit'),
]
