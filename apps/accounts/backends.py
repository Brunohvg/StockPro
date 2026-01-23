"""
Custom Authentication Backends for Multi-Tenant StockPro (V11)
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailBackend(ModelBackend):
    """
    Authenticates against settings.AUTH_USER_MODEL.
    Allows login using either username or email.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)

        try:
            # Try to fetch user by username OR email
            user = UserModel.objects.get(Q(username__iexact=username) | Q(email__iexact=username))
        except UserModel.DoesNotExist:
            return None
        except UserModel.MultipleObjectsReturned:
            # If multiple users have same email (shouldn't happen with unique email),
            # pick the first active one or just the first one
            return UserModel.objects.filter(email__iexact=username).order_by('id').first()
        else:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        return None
