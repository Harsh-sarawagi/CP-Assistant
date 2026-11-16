"""Temporary, public read-only HTTP mode. Never enable account functionality here."""
from .production import *  # noqa: F403

DEBUG = False
ALLOWED_HOSTS = ['130.210.110.62']
ROOT_URLCONF = 'config.http_test_urls'
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_PROXY_SSL_HEADER = None
CSRF_TRUSTED_ORIGINS = []
# Keep secure-cookie flags from production, even though this mode issues no cookies.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != 'django.contrib.admin']
MIDDLEWARE = [
    'config.http_test_guard.PublicReadOnly',
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
AUTHENTICATION_BACKENDS = []
DATABASES = {'default': {'ENGINE': 'django.db.backends.dummy'}}
AI_API_KEY = ''
EXTENSION_ALLOWED_IDS = set()
EXTENSION_ALLOWED_ORIGIN = ''
