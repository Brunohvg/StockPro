from django.urls import path

from . import views

app_name = 'tenants'

urlpatterns = [
    path('', views.landing_page, name='landing'),
    path('signup/', views.signup_view, name='signup'),
    path('billing/', views.billing_view, name='billing'),
    path('billing/upgrade/<int:plan_id>/', views.billing_upgrade, name='billing_upgrade'),
    path('admin-panel/', views.admin_panel_view, name='admin_panel'),
    path('admin-panel/tenant/update/', views.admin_tenant_update, name='admin_tenant_update'),
    path('admin-panel/backups/', views.admin_backups_view, name='admin_backups'),
    path('admin-panel/backups/run/', views.admin_backup_run, name='admin_backup_run'),
    path('admin-panel/backups/verify/', views.admin_backup_verify, name='admin_backup_verify'),
]
