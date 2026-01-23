"""
Core App - Shared utilities and system-wide settings
"""
from django.conf import settings
from django.db import models

from apps.tenants.models import TenantMixin


class SystemSetting(TenantMixin):
    """Global tenant-specific configuration"""
    company_name = models.CharField(max_length=100, default="Minha Empresa")
    logo_url = models.URLField(blank=True, null=True)
    alert_email = models.EmailField(blank=True, null=True)
    low_stock_alert_threshold = models.PositiveIntegerField(default=10)
    enable_auto_cost_update = models.BooleanField(default=True)

    # AI Staging Settings (V20)
    ai_import_mode = models.CharField(
        max_length=10,
        choices=[('MANUAL', 'Manual'), ('HYBRID', 'Híbrido'), ('AUTO', 'Automático')],
        default='HYBRID'
    )
    ai_auto_approve_threshold = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.90,
        verbose_name="Limiar de Auto-Aprovação AI"
    )

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


class AIDecisionLog(TenantMixin):
    """Logs AI prompts, results and confidence for transparency (Hardening V17+)"""
    feature = models.CharField(max_length=50, db_index=True) # e.g., 'NFE_MAPPING'
    provider = models.CharField(max_length=50) # e.g., 'GROQ'
    model_name = models.CharField(max_length=50)

    prompt_text = models.TextField()
    response_json = models.JSONField()
    confidence_score = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)

    # Context
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Log de Decisão IA"
        verbose_name_plural = "Logs de Decisão IA"


class VisualAuditLog(TenantMixin):
    """
    Stores snapshots of state changes for visual auditing (Plan C).
    Tracks 'Before' and 'After' states for products, prices, and stock changes.
    """
    entity_type = models.CharField(max_length=50, db_index=True) # 'PRODUCT', 'STOCK', 'PRICE'
    entity_id = models.CharField(max_length=100)

    action = models.CharField(max_length=20) # 'CREATE', 'UPDATE', 'DELETE'
    source = models.CharField(max_length=50) # 'APP', 'API', 'NUVEMSHOP', 'TRAY'

    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    diff = models.JSONField(null=True, blank=True)

    external_ref = models.CharField(max_length=100, blank=True, null=True) # e.g., Order ID

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Auditoria Visual"
        verbose_name_plural = "Auditorias Visuais"

    def __str__(self):
        return f"{self.action} on {self.entity_type} ({self.entity_id}) at {self.created_at}"
