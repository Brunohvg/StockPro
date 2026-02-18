"""
Accounts App - Admin Configuration
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import TenantInvite, TenantMembership


# Inline de memberships dentro do User
class TenantMembershipInline(admin.TabularInline):
    model = TenantMembership
    extra = 0
    fields = ('tenant', 'role', 'is_active', 'joined_at')
    readonly_fields = ('joined_at',)
    can_delete = True


# Estende o UserAdmin padrão com inline de memberships
class UserAdmin(BaseUserAdmin):
    inlines = [TenantMembershipInline]
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_superuser', 'date_joined')
    list_filter = ('is_staff', 'is_superuser', 'is_active')


# Re-registra o User com o admin customizado
admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'tenant', 'role', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active', 'tenant')
    search_fields = ('user__username', 'user__email', 'tenant__name')
    list_editable = ('role', 'is_active')
    ordering = ('-joined_at',)
    raw_id_fields = ('user', 'tenant')


@admin.register(TenantInvite)
class TenantInviteAdmin(admin.ModelAdmin):
    list_display = ('email', 'tenant', 'role', 'invited_by', 'created_at', 'expires_at', 'accepted_at')
    list_filter = ('role', 'tenant')
    search_fields = ('email', 'tenant__name')
    readonly_fields = ('id', 'token', 'created_at', 'accepted_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # Convites criados apenas pela aplicação
