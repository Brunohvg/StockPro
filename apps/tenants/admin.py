from django.contrib import admin

from .models import BackupRun, Plan, Tenant, TenantEvent


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('display_name', 'name', 'price', 'max_products', 'max_users', 'has_ai_matching')
    search_fields = ('name', 'display_name')
    list_filter = ('has_ai_matching', 'has_ai_reconciliation')

class TenantEventInline(admin.TabularInline):
    model = TenantEvent
    fields = ('created_at', 'kind', 'message', 'actor', 'reason')
    readonly_fields = fields
    extra = 0
    can_delete = False
    ordering = ('-created_at',)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    # Plano, status e teste se mudam pela Central (/admin-panel/), que registra
    # o histórico. Aqui ficam só para consulta rápida, sem edição em massa.
    list_display = ('name', 'plan', 'subscription_status', 'is_active', 'trial_ends_at', 'next_due_date', 'created_at')
    list_filter = ('subscription_status', 'is_active', 'plan')
    search_fields = ('name', 'cnpj', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [TenantEventInline]


@admin.register(TenantEvent)
class TenantEventAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'tenant', 'kind', 'message', 'actor')
    list_filter = ('kind',)
    search_fields = ('tenant__name', 'message', 'reason')
    list_select_related = ('tenant', 'actor')
    readonly_fields = [f.name for f in TenantEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BackupRun)
class BackupRunAdmin(admin.ModelAdmin):
    list_display = ('started_at', 'status', 'trigger', 'db_size_bytes', 'media_size_bytes', 'encrypted')
    list_filter = ('status', 'trigger', 'encrypted')
    readonly_fields = [f.name for f in BackupRun._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
