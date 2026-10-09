import os
import sys
from datetime import timedelta
from pathlib import Path

import dj_database_url
from decouple import AutoConfig, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega variáveis de ambiente com fallback inteligente:
# 1. No Docker/Swarm: lê direto do os.environ (sem arquivo .env)
# 2. Em desenvolvimento: lê do .env.local ou .env se existirem
config = AutoConfig(search_path=BASE_DIR)

SECRET_KEY = config('SECRET_KEY', default='django-insecure-secret-key-replace-me')

DEBUG = config('DEBUG', default=False, cast=bool)

# Guard de segurança: bloqueia subida em produção com defaults inseguros
if not DEBUG and SECRET_KEY == 'django-insecure-secret-key-replace-me':
    print("ERRO FATAL: Configure SECRET_KEY no .env antes de rodar em produção!", file=sys.stderr)
    sys.exit(1)

DOMAIN = config('DOMAIN', default='').strip().strip('/')
SITE_URL = config('SITE_URL', default='').strip().rstrip('/')

if not SITE_URL and DOMAIN:
    SITE_URL = f'https://{DOMAIN}'

ALLOWED_HOSTS = (
    ['*']
    if DEBUG
    else config(
        'ALLOWED_HOSTS',
        default=DOMAIN or 'localhost,127.0.0.1',
        cast=Csv(),
    )
)

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/app/'
LOGOUT_REDIRECT_URL = '/'

AUTHENTICATION_BACKENDS = [
    'apps.accounts.backends.EmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Admin Configuration — lê DJANGO_ADMIN_PATH (padrão do .env)
ADMIN_URL = config('DJANGO_ADMIN_PATH', default='admin/')
ADMIN_URL = ADMIN_URL.strip('/')
if ADMIN_URL:
    ADMIN_URL += '/'

CORS_ALLOW_ALL_ORIGINS = DEBUG

INSTALLED_APPS = [
    'whitenoise.runserver_nostatic',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',

    # Third party
    'rest_framework',
    'rest_framework_simplejwt',
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
# Coolify: prefira DATABASE_URL. DB_* continua disponível como fallback.
DATABASE_URL = config('DATABASE_URL', default='')
DB_HOST = config('DB_HOST', default='')
DB_TYPE = config('DB_TYPE', default='postgres' if (DATABASE_URL or DB_HOST) else 'sqlite')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=60,
        )
    }
    DATABASES['default'].setdefault('OPTIONS', {})
    DATABASES['default']['OPTIONS'].setdefault('connect_timeout', 10)
elif DB_TYPE == 'postgres' and DB_HOST:
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

CSRF_TRUSTED_ORIGINS = (
    []
    if DEBUG
    else config(
        'CSRF_TRUSTED_ORIGINS',
        default=SITE_URL,
        cast=Csv(),
    )
)

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
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
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').is_dir() else []
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# Em produção, sirva apenas os arquivos coletados e versionados do STATIC_ROOT.
# URLs com hash evitam que browsers reutilizem CSS/JS de outra versão do deploy.
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_MANIFEST_STRICT = True

# Celery — padrão Flowlog: só configura se broker estiver definido
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='')

if CELERY_BROKER_URL:
    from celery.schedules import crontab

    CELERY_ACCEPT_CONTENT = ['json']
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_ENABLE_UTC = True
    CELERY_TIMEZONE = 'America/Sao_Paulo'
    CELERY_TASK_ACKS_LATE = True
    CELERY_TASK_DEFAULT_QUEUE = 'default'
    CELERY_WORKER_PREFETCH_MULTIPLIER = 1
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
    CELERY_BEAT_SCHEDULE = {
        'cleanup-expired-trials-daily': {
            'task': 'apps.tenants.tasks.cleanup_expired_trials',
            'schedule': crontab(hour=3, minute=0),
        },
        'daily-backup': {
            'task': 'apps.tenants.backup_task.daily_backup',
            'schedule': crontab(hour=3, minute=30),
        },
        'daily-expiry-alerts': {
            'task': 'apps.tenants.tasks.send_expiry_alerts',
            'schedule': crontab(hour=7, minute=0),
        },
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Security Settings for Production (Behind Proxy)
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    # Healthcheck interno do container é HTTP puro
    SECURE_REDIRECT_EXEMPT = [r'^healthcheck/$']
    # Comece baixo; suba para 31536000 depois de confirmar HTTPS estável
    SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=3600, cast=int)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = 'same-origin'

# Sem SMTP em produção, não registrar tokens de recuperação nos logs.
EMAIL_HOST = config('EMAIL_HOST', default='')
if EMAIL_HOST:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
    EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
    EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
    EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
else:
    EMAIL_BACKEND = ('django.core.mail.backends.console.EmailBackend' if DEBUG
                     else 'django.core.mail.backends.dummy.EmailBackend')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='StockPro <nao-responda@optarys.com.br>')

# Logging — garante que erros do Celery aparecem nos logs do Docker
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'celery': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'apps': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
    },
}

# Backup settings
BACKUP_DIR = config('BACKUP_DIR', default='/data/backups')
BACKUP_RETENTION_DAYS = config('BACKUP_RETENTION_DAYS', default=30, cast=int)

# WhatsApp de suporte (usado na página de planos/billing)
WHATSAPP_SUPPORT = config('WHATSAPP_SUPPORT', default='5511999999999')

# AI Integration (Grok / X.AI)
XAI_API_KEY = config('XAI_API_KEY', default='')
XAI_MODEL = 'grok-2-latest'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'NUM_PROXIES': config('API_NUM_PROXIES', default=1, cast=int),
    'DEFAULT_THROTTLE_CLASSES': (
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ),
    'DEFAULT_THROTTLE_RATES': {
        'user': config('API_THROTTLE_USER', default='1200/hour'),
        'anon': config('API_THROTTLE_ANON', default='300/hour'),
        'auth': config('API_THROTTLE_AUTH', default='20/minute'),
        'cnpj': config('API_THROTTLE_CNPJ', default='20/minute'),
    },
}

# Cache (usado pelo throttling da API). Em produção usa o Redis da stack (db 2);
# sem Redis, cai para memória local do processo.
_default_cache_url = ''
if CELERY_BROKER_URL.startswith('redis://'):
    import re as _re
    _default_cache_url = _re.sub(r'/\d+$', '', CELERY_BROKER_URL) + '/2'
CACHE_URL = config('CACHE_URL', default=_default_cache_url)
if CACHE_URL:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.redis.RedisCache', 'LOCATION': CACHE_URL}}
else:
    CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}
