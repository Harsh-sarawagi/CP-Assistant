"""Offline deployment regression checks; no database or external service writes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

from django.core.cache import cache
from django.db import OperationalError
from django.test import Client, RequestFactory, SimpleTestCase, override_settings

from config.health import health
from core.services.extension_auth import APIError, limit


class DeploymentTests(SimpleTestCase):
    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_home_login_survives_invalid_contest_feed(self):
        from unittest.mock import Mock
        response = Mock(status_code=200, json=Mock(side_effect=ValueError('Invalid JSON')))
        with patch('core.views.requests.get', return_value=response):
            page = Client().get('/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'csrfmiddlewaretoken')

    def test_readiness_is_readonly_and_failure_is_generic(self):
        request = RequestFactory().get('/health/')
        with patch('config.health.connection') as database:
            self.assertEqual(health(request).status_code, 200)
            database.cursor.return_value.__enter__.return_value.execute.assert_called_once_with('SELECT 1')
        with patch('config.health.connection') as database:
            database.cursor.side_effect = OperationalError('private database error')
            response = health(request)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(b'private database error', response.content)
        self.assertEqual(health(RequestFactory().post('/health/')).status_code, 405)

    @override_settings(TRUST_PROXY_IP=True)
    def test_proxy_clients_do_not_share_one_rate_limit(self):
        cache.clear()
        factory = RequestFactory()
        a = factory.get('/', REMOTE_ADDR='172.20.0.2', HTTP_X_REAL_IP='192.0.2.1')
        b = factory.get('/', REMOTE_ADDR='172.20.0.2', HTTP_X_REAL_IP='192.0.2.2')
        limit(a, 'deployment-check', maximum=1)
        limit(b, 'deployment-check', maximum=1)
        with self.assertRaises(APIError):
            limit(a, 'deployment-check', maximum=1)

    @override_settings(TRUST_PROXY_IP=False)
    def test_untrusted_forwarded_ip_cannot_bypass_local_limit(self):
        cache.clear()
        factory = RequestFactory()
        limit(factory.get('/', REMOTE_ADDR='192.0.2.1', HTTP_X_REAL_IP='192.0.2.2'), 'deployment-check', maximum=1)
        with self.assertRaises(APIError):
            limit(factory.get('/', REMOTE_ADDR='192.0.2.1', HTTP_X_REAL_IP='192.0.2.3'), 'deployment-check', maximum=1)

    def test_production_settings_require_secret_and_enforce_https(self):
        environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.production', 'DOMAIN': 'cp.example.com',
                       'DJANGO_SECRET_KEY': 'verification-only-' + 'x9B7mQ2z' * 9, 'DB_NAME': 'unused_test', 'DB_USER': 'unused_test',
                       'DB_PASSWORD': 'unused-test-password', 'DB_HOST': 'db', 'DB_ENGINE': 'sqlite', 'ALLOWED_HOSTS': '', 'CSRF_TRUSTED_ORIGINS': '', 'AI_API_KEY': ''}
        program = '''
from unittest.mock import patch
with patch('dotenv.load_dotenv',return_value=False):
    import django
    django.setup()
    from django.conf import settings
    assert not settings.DEBUG
    assert settings.ALLOWED_HOSTS==['cp.example.com']
    assert settings.CSRF_TRUSTED_ORIGINS==['https://cp.example.com']
    assert settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE and settings.SECURE_SSL_REDIRECT
    assert settings.DATABASES['default']['HOST']=='db'
    assert settings.DATABASES['default']['ENGINE']=='django.db.backends.postgresql'
'''
        result = subprocess.run([sys.executable, '-B', '-c', program], env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0)
        environment['DJANGO_SECRET_KEY'] = ''
        result = subprocess.run([sys.executable, '-B', '-c', program], env=environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_local_sqlite_selection_does_not_connect_or_change_data(self):
        environment = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'DB_ENGINE': 'sqlite'}
        program = "from django.conf import settings; assert settings.DATABASES['default']['ENGINE']=='django.db.backends.sqlite3'"
        result = subprocess.run([sys.executable, '-B', '-c', program], env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_secret_generation_does_not_overwrite_or_echo(self):
        script = Path(__file__).resolve().parent.parent / 'scripts' / 'prepare_production.py'
        with tempfile.TemporaryDirectory(prefix='cp-secret-test-') as temporary:
            destination = Path(temporary) / 'production.env'
            result = subprocess.run([sys.executable, '-B', str(script), '--domain', 'cp.example.com', '--output', str(destination)], capture_output=True)
            self.assertEqual(result.returncode, 0)
            contents = destination.read_text()
            values = dict(line.split('=', 1) for line in contents.splitlines() if '=' in line and not line.startswith('#'))
            for name in ['DJANGO_SECRET_KEY', 'DB_PASSWORD', 'POSTGRES_ADMIN_PASSWORD']:
                self.assertNotIn(values[name].encode(), result.stdout + result.stderr)
            self.assertGreaterEqual(len(values['DJANGO_SECRET_KEY']), 50)
            repeated = subprocess.run([sys.executable, '-B', str(script), '--output', str(destination)], capture_output=True)
            self.assertNotEqual(repeated.returncode, 0)
            self.assertEqual(destination.read_text(), contents)
