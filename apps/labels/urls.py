from django.urls import path

from . import views

app_name = 'labels'

urlpatterns = [
    path('', views.index, name='index'),
    path('buscar/', views.search, name='search'),
    path('nfe/<uuid:pk>/', views.nfe_items, name='nfe_items'),
    path('previa.svg', views.preview_svg, name='preview'),
    path('gerar/', views.generate, name='generate'),
    path('texto/<int:pk>/', views.save_text, name='save_text'),
    path('modelo/', views.settings_view, name='settings'),
]
