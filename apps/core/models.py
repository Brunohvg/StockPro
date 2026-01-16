"""
Core App - Shared utilities and system-wide settings
"""
from django.db import models
from apps.tenants.models import TenantMixin


class SystemSetting(TenantMixin):
    """Global tenant-specific configuration"""
    company_name = models.CharField(max_length=100, default="Minha Empresa")
    logo_url = models.URLField(blank=True, null=True)
    alert_email = models.EmailField(blank=True, null=True)
    low_stock_alert_threshold = models.PositiveIntegerField(default=10)
    enable_auto_cost_update = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Configuração Global"
        verbose_name_plural = "Configurações Globais"

    def __str__(self):
        return f"Configurações de {self.company_name}"

    @classmethod
    def get_settings(cls, tenant):
        if not tenant:
            return None
        obj, created = cls.objects.get_or_create(tenant=tenant)
        return obj
