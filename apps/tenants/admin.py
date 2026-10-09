from django.contrib import admin

from .models import BackupRun, Plan, Tenant


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'name', 'price', 'max_products', 'max_users', 'has_ai_matching')
    search_fields = ('name', 'display_name')
    list_filter = ('has_ai_matching', 'has_ai_reconciliation')

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('name', 'plan', 'subscription_status', 'is_active', 'trial_ends_at', 'created_at')
    list_filter = ('subscription_status', 'is_active', 'plan')
    search_fields = ('name', 'cnpj', 'slug')
    list_editable = ('is_active', 'subscription_status', 'plan')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(BackupRun)
class BackupRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'status', 'trigger', 'db_size_bytes', 'media_size_bytes', 'encrypted')
    list_filter = ('status', 'trigger', 'encrypted')
    readonly_fields = [f.name for f in BackupRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
