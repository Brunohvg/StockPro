"""
Accounts App - User Profile and Authentication
"""
from django.db import models
from django.conf import settings
from apps.tenants.models import Tenant


class UserProfile(models.Model):
    """Links Django User to a Tenant"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='users')

    class Meta:
        verbose_name = "Perfil de Usuário"
        verbose_name_plural = "Perfis de Usuário"

    def __str__(self):
        return f"{self.user.username} ({self.tenant.name})"
