from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.system_settings, name='system_settings'),
    path('employees/add/', views.employee_create, name='employee_create'),
]
