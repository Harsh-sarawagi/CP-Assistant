"""Production-only settings; local runserver continues to use config.settings."""
from django.core.exceptions import ImproperlyConfigured
from copy import deepcopy
from .settings import *  # noqa: F403

# Production never inherits a local SQLite engine/path, even if DB_ENGINE=sqlite.
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'PORT': os.getenv('DB_PORT', '5432')}}
STORAGES = deepcopy(STORAGES)


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ImproperlyConfigured(f'{name} is required for production.')
    return value


DEBUG = False
DOMAIN = required('DOMAIN')
if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', DOMAIN) or DOMAIN.endswith('.example'):
    raise ImproperlyConfigured('Set DOMAIN to your hostname, without a scheme, path or port.')
SECRET_KEY = required('DJANGO_SECRET_KEY')
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('Generate a new strong production Django secret.')
ALLOWED_HOSTS = [s.strip() for s in os.getenv('ALLOWED_HOSTS', '').split(',') if s.strip()] or [DOMAIN]
if DOMAIN not in ALLOWED_HOSTS or any('*' in host or '/' in host or ':' in host for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured('ALLOWED_HOSTS must contain DOMAIN and exact hostnames only.')
CSRF_TRUSTED_ORIGINS = [s.strip() for s in os.getenv('CSRF_TRUSTED_ORIGINS', '').split(',') if s.strip()] or ['https://' + DOMAIN]
if any(not origin.startswith('https://') or '*' in origin for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('Production CSRF origins must be explicit HTTPS origins.')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Container-only readiness check; Nginx blocks this route publicly.
SECURE_REDIRECT_EXEMPT = [r'^health/$']
TRUST_PROXY_IP = True
for field, variable in [('NAME', 'DB_NAME'), ('USER', 'DB_USER'), ('PASSWORD', 'DB_PASSWORD'), ('HOST', 'DB_HOST')]:
    DATABASES['default'][field] = required(variable)
DATABASES['default']['CONN_MAX_AGE'] = 60
DATABASES['default']['CONN_HEALTH_CHECKS'] = True
STORAGES['staticfiles']['BACKEND'] = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
