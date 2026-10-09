#!/bin/sh
set -e

wait_for_database() {
    echo "Aguardando banco de dados..."

    python <<'PY'
import os
import sys
import time

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stock_control.settings")

import django
django.setup()

from django.db import connections
from django.db.utils import OperationalError

deadline = time.time() + 45

while True:
    try:
        connection = connections["default"]
        connection.ensure_connection()
        connection.close()
        print("Banco de dados disponível.")
        sys.exit(0)
    except OperationalError as exc:
        if time.time() >= deadline:
            print(f"Timeout aguardando banco de dados: {exc}", file=sys.stderr)
            sys.exit(1)
        time.sleep(2)
PY
}

if [ "${SKIP_DJANGO_BOOTSTRAP:-False}" = "True" ]; then
    exec "$@"
fi

if [ -n "${DATABASE_URL:-}" ] || [ -n "${DB_HOST:-}" ]; then
    wait_for_database
fi

echo "Executando migrações..."
python manage.py migrate --noinput

echo "Coletando arquivos estáticos..."
python manage.py collectstatic --noinput

if [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "Garantindo usuário administrador..."
    python <<'PY'
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "stock_control.settings")

import django
django.setup()

from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ["DJANGO_SUPERUSER_EMAIL"].strip()
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "admin").strip() or "admin"

lookup = {"email": email} if hasattr(User, "email") else {"username": username}
user = User.objects.filter(**lookup).first()

if user is None:
    create_kwargs = {"username": username, "email": email}
    user = User.objects.create_superuser(password=password, **create_kwargs)
    print(f"Administrador criado: {email}")
else:
    changed = False
    if not user.is_staff:
        user.is_staff = True
        changed = True
    if not user.is_superuser:
        user.is_superuser = True
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if changed:
        user.save(update_fields=["is_staff", "is_superuser", "is_active"])
    print(f"Administrador já existe: {email}")
PY
fi

exec "$@"
