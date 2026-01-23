"""
Accounts App - TenantMembership and Invite System (V11)

Replaces UserProfile with a many-to-many relationship supporting:
- Multiple companies per user
- Role-based access (OWNER, ADMIN, OPERATOR)
- Invite system with expiration
"""
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import Tenant


class MembershipRole(models.TextChoices):
    OWNER = 'OWNER', 'Proprietário'
    ADMIN = 'ADMIN', 'Administrador'
    OPERATOR = 'OPERATOR', 'Operador'


class TenantMembership(models.Model):
    """
    Links a User to a Tenant with a specific role.
    A user can belong to multiple tenants.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='memberships'
    )
    role = models.CharField(
        max_length=20,
        choices=MembershipRole.choices,
        default=MembershipRole.OPERATOR,
        verbose_name="Papel"
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Membro da Empresa"
        verbose_name_plural = "Membros das Empresas"
        unique_together = ['user', 'tenant']
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.user.username} @ {self.tenant.name} ({self.get_role_display()})"

    @property
    def is_owner(self):
        return self.role == MembershipRole.OWNER

    @property
    def is_admin(self):
        return self.role in [MembershipRole.OWNER, MembershipRole.ADMIN]

    @property
    def can_manage_users(self):
        return self.role in [MembershipRole.OWNER, MembershipRole.ADMIN]

    @property
    def can_manage_billing(self):
        return self.role == MembershipRole.OWNER


class TenantInvite(models.Model):
    """
    Invite to join a tenant. Single-use, expires in 7 days.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='invites'
    )
    email = models.EmailField(verbose_name="E-mail do Convidado")
    role = models.CharField(
        max_length=20,
        choices=MembershipRole.choices,
        default=MembershipRole.OPERATOR
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='sent_invites'
    )
    token = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Convite"
        verbose_name_plural = "Convites"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = uuid.uuid4().hex
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Convite para {self.email} em {self.tenant.name}"

    @property
    def is_valid(self):
        """Check if invite is still valid (not expired, not used)"""
        if self.accepted_at:
            return False
        if timezone.now() > self.expires_at:
            return False
        return True

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at and not self.accepted_at

    def accept(self, user):
        """Accept invite and create membership"""
        if not self.is_valid:
            raise ValueError("Convite inválido ou expirado")

        # Check if already member
        if TenantMembership.objects.filter(user=user, tenant=self.tenant).exists():
            raise ValueError("Usuário já é membro desta empresa")

        # Create membership
        membership = TenantMembership.objects.create(
            user=user,
            tenant=self.tenant,
            role=self.role
        )

        # Mark invite as used
        self.accepted_at = timezone.now()
        self.save()

        return membership


# ============ LEGACY SUPPORT ============
# Keep UserProfile temporarily for backward compatibility during migration
# This will be removed after migration is complete

class UserProfile(models.Model):
    """
    DEPRECATED: Use TenantMembership instead.
    Kept temporarily for migration compatibility.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='users')

    class Meta:
        verbose_name = "Perfil de Usuário (DEPRECATED)"
        verbose_name_plural = "Perfis de Usuário (DEPRECATED)"

    def __str__(self):
        return f"{self.user.username} ({self.tenant.name})"
