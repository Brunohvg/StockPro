from pathlib import Path
from decouple import Config, RepositoryEnv, Csv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Loading environment variables
env_path = os.path.join(BASE_DIR, '.env.local') if os.path.exists(os.path.join(BASE_DIR, '.env.local')) else os.path.join(BASE_DIR, '.env')
print(f"DEBUG: Carregando configurações de: {env_path}")
config = Config(RepositoryEnv(env_path))
print(f"DEBUG: DB_TYPE selecionado: {config('DB_TYPE', default='postgres')}")

SECRET_KEY = config('SECRET_KEY', default='django-insecure-secret-key-replace-me')

DEBUG = config('DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = ['*'] if DEBUG else config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/app/'
LOGOUT_REDIRECT_URL = '/'

AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Admin Configuration
ADMIN_URL = config('ADMIN_URL', default='admin/')
ADMIN_URL = ADMIN_URL.strip('/')
if ADMIN_URL:
    ADMIN_URL += '/'

CORS_ALLOW_ALL_ORIGINS = DEBUG

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Third party
    'rest_framework',
    'django_htmx',
    'corsheaders',

    # Local Apps
    'apps.tenants',
    'apps.accounts',
    'apps.products',
    'apps.inventory',
    'apps.partners',  # V2: Fornecedores e Mapeamento de Produtos
    'apps.reports',
    'apps.core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
    'apps.tenants.middleware.TenantMiddleware',
]

ROOT_URLCONF = 'stock_control.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.context_processors.global_settings',
            ],
        },
    },
]

WSGI_APPLICATION = 'stock_control.wsgi.application'

# Database Configuration
DB_HOST = config('DB_HOST', default='')
DB_TYPE = config('DB_TYPE', default='postgres' if DB_HOST else 'sqlite')

if DB_TYPE == 'postgres' and DB_HOST:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME', default='stockpro_db'),
            'USER': config('DB_USER', default='stockpro_user'),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': DB_HOST,
            'PORT': config('DB_PORT', default='5432'),
            'CONN_MAX_AGE': 60,
            'OPTIONS': {
                'connect_timeout': 10,
            }
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv()) if not DEBUG else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# Brazilian Localization Standard
USE_L10N = True
USE_THOUSAND_SEPARATOR = True
THOUSAND_SEPARATOR = '.'
DECIMAL_SEPARATOR = ','
NUMBER_GROUPING = 3

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Celery
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security Settings for Production (Behind Proxy)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_REDIS_BACKEND_USE_SSL = False
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'socket_timeout': 30,
    'socket_connect_timeout': 30,
    'retry_policy': {
        'timeout': 5.0,
        'max_retries': 3,
        'interval_start': 0,
        'interval_step': 0.2,
        'interval_max': 0.5,
    }
}
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'cleanup-expired-trials-daily': {
        'task': 'apps.tenants.tasks.cleanup_expired_trials',
        'schedule': crontab(hour=3, minute=0),
    },
}

# AI Integration (Grok / X.AI)
XAI_API_KEY = config('XAI_API_KEY', default='')
XAI_MODEL = 'grok-2-latest'
