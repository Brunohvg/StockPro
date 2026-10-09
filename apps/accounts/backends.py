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

    A senha é SEMPRE verificada. Se o identificador casar com mais de um
    usuário (ex.: username de um igual ao e-mail de outro, ou e-mails
    duplicados com caixa diferente), cada candidato é testado com a senha.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None

        candidates = UserModel.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=username)
        ).order_by('id')

        if not candidates:
            # Mitiga timing attack de enumeração de usuários
            UserModel().set_password(password)
            return None

        for user in candidates:
            if user.check_password(password) and self.user_can_authenticate(user):
                return user
        return None
