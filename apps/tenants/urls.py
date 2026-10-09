from django.urls import path

from . import views, views_platform

app_name = 'tenants'

urlpatterns = [
    path('', views.landing_page, name='landing'),
    path('signup/', views.signup_view, name='signup'),
    path('billing/', views.billing_view, name='billing'),
    path('billing/upgrade/<int:plan_id>/', views.billing_upgrade, name='billing_upgrade'),
    # Central da plataforma (só superusuário)
    path('admin-panel/', views_platform.platform_home, name='admin_panel'),
    path('admin-panel/empresas.csv', views_platform.tenants_csv, name='platform_tenants_csv'),
    path('admin-panel/empresas/<int:pk>/', views_platform.tenant_detail, name='platform_tenant'),
    path('admin-panel/empresas/<int:pk>/acao/', views_platform.tenant_action, name='platform_tenant_action'),
    path('admin-panel/planos/', views_platform.plan_list, name='platform_plans'),
    path('admin-panel/planos/novo/', views_platform.plan_edit, name='platform_plan_new'),
    path('admin-panel/planos/<int:pk>/', views_platform.plan_edit, name='platform_plan_edit'),
    path('admin-panel/seguranca/desbloquear/<int:attempt_id>/', views_platform.unlock_login,
         name='platform_unlock_login'),
    path('admin-panel/backups/', views.admin_backups_view, name='admin_backups'),
    path('admin-panel/backups/run/', views.admin_backup_run, name='admin_backup_run'),
    path('admin-panel/backups/verify/', views.admin_backup_verify, name='admin_backup_verify'),
]
