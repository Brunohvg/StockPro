"""
Tenants App - Multi-tenancy and Plan Management
"""
from django.db import models
from django.utils.text import slugify


class Plan(models.Model):
    """Subscription plans with limits"""
    PLAN_TYPES = [
        ('GRATUITO', 'Gratuito'),
        ('INICIAL', 'Inicial'),
        ('PROFISSIONAL', 'Profissional'),
        ('CORPORATIVO', 'Corporativo'),
    ]
    name = models.CharField(max_length=50, choices=PLAN_TYPES, unique=True)
    display_name = models.CharField(max_length=100, default="Plano")
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    max_products = models.PositiveIntegerField(default=50, help_text="Limite de produtos cadastrados")
    max_users = models.PositiveIntegerField(default=3, help_text="Limite de usuários na empresa")

    # AI Features
    has_ai_matching = models.BooleanField(default=False, help_text="Habilita match inteligente de produtos via IA")
    has_ai_reconciliation = models.BooleanField(default=False, help_text="Habilita conciliação automática via IA")

    features = models.TextField(blank=True, help_text="Lista de features separadas por vírgula")

    class Meta:
        verbose_name = "Plano"
        verbose_name_plural = "Planos"

    def __str__(self):
        return self.display_name


class Tenant(models.Model):
    """Company/Organization entity for multi-tenancy"""
    SUBSCRIPTION_STATUS = [
        ('TRIAL', 'Em Teste'),
        ('ACTIVE', 'Ativo'),
        ('SUSPENDED', 'Suspenso'),
        ('CANCELLED', 'Cancelado'),
    ]

    name = models.CharField(max_length=100, verbose_name="Nome da Empresa/Unidade")
    cnpj = models.CharField(max_length=18, unique=True, blank=True, null=True, verbose_name="CNPJ", help_text="XX.XXX.XXX/XXXX-XX")
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    subdomain = models.CharField(max_length=50, unique=True, blank=True, null=True)
    plan = models.ForeignKey(Plan, on_delete=models.SET_NULL, null=True, blank=True, related_name='tenants')
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS, default='TRIAL', verbose_name="Status da Assinatura")
    trial_ends_at = models.DateTimeField(null=True, blank=True, verbose_name="Fim do Período de Teste")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tenant (Empresa)"
        verbose_name_plural = "Tenants (Empresas)"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.pk and not self.trial_ends_at:
            from django.utils import timezone
            self.trial_ends_at = timezone.now() + timezone.timedelta(days=14)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def is_trial_expired(self):
        from django.utils import timezone
        if self.subscription_status == 'TRIAL' and self.trial_ends_at:
            return timezone.now() > self.trial_ends_at
        return False

    @property
    def products_count(self):
        """Count products for this tenant"""
        from apps.products.models import Product
        return Product.objects.filter(tenant=self).count()

    @property
    def users_count(self):
        """Count active members for this tenant"""
        return self.memberships.filter(is_active=True).count()

    @property
    def products_limit_reached(self):
        if self.plan and self.plan.max_products:
            return self.products_count >= self.plan.max_products
        return False

    @property
    def users_limit_reached(self):
        if self.plan and self.plan.max_users:
            return self.users_count >= self.plan.max_users
        return False


class TenantMixin(models.Model):
    """Abstract base model for tenant-scoped entities"""
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, verbose_name="Tenant", null=True, blank=True)

    class Meta:
        abstract = True
