"""
Accounts App URLs - Authentication and Multi-Tenant Access
"""
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    # Smart login (replaces default)
    path('login/', views.SmartLoginView.as_view(), name='login'),

    # Company selection
    path('select-company/', views.select_company, name='select_company'),
    path('switch-company/<int:tenant_id>/', views.switch_company, name='switch_company'),
    path('no-company/', views.no_company, name='no_company'),
    path('create-company/', views.create_company, name='create_company'),

    # Invite system
    path('invite/', views.invite_user, name='invite_user'),
    path('accept-invite/<str:token>/', views.accept_invite, name='accept_invite'),
]
