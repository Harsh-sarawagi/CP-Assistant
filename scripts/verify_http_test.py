"""Verify the temporary HTTP mode without creating any database or volume.

Default: offline Django tests. --docker PATH additionally builds and runs web/Nginx locally.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def offline():
    os.environ.update(DJANGO_SETTINGS_MODULE='config.http_test', DOMAIN='130.210.110.62',
                      ALLOWED_HOSTS='130.210.110.62', CSRF_TRUSTED_ORIGINS='',
                      DJANGO_SECRET_KEY=secrets.token_urlsafe(64), DB_NAME='disabled',
                      DB_USER='disabled', DB_PASSWORD='disabled', DB_HOST='db')
    with patch('dotenv.load_dotenv', return_value=False):
        import django
        django.setup()
    import unittest
    from django.test.utils import setup_test_environment, teardown_test_environment
    from django.core.checks import run_checks
    setup_test_environment()
    try:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromName('core.test_http_test'))
        assert result.wasSuccessful()
        assert not run_checks(databases=[])
    finally:
        teardown_test_environment()


def containers(docker):
    from prepare_production import prepare
    from http.client import HTTPConnection
    project = 'cp-http-verify-' + secrets.token_hex(5)
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        folder = Path(directory).resolve()
        assert folder.is_relative_to(Path(tempfile.gettempdir()).resolve())
        envfile = folder / 'test.env'
        prepare(envfile, '130.210.110.62')
        with envfile.open('a', encoding='utf-8') as stream:
            stream.write('\nHTTP_TEST_BIND=127.0.0.1\nHTTP_TEST_PORT=18081\n')
        environment = os.environ.copy()
        for name in ['DOMAIN', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'DJANGO_SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD',
                     'POSTGRES_ADMIN_PASSWORD', 'HTTP_TEST_BIND', 'HTTP_TEST_PORT', 'COMPOSE_PROFILES']:
            environment.pop(name, None)
        command = [docker, 'compose', '--env-file', str(envfile), '--project-name', project,
                   '-f', str(ROOT / 'compose.yaml'), '-f', str(ROOT / 'compose.http-test.yaml')]

        def run(args):
            result = subprocess.run(args, cwd=ROOT, env=environment, encoding='utf-8', errors='replace', capture_output=True)
            if result.returncode:
                raise RuntimeError('HTTP test Docker operation failed; no secret-bearing output printed.')
            return result.stdout

        try:
            resolved = json.loads(run(command + ['config', '--format', 'json']))
            assert not resolved.get('volumes')
            assert not resolved['services']['web'].get('depends_on')
            assert not resolved['services']['web'].get('ports')
            assert len(resolved['services']['nginx']['ports']) == 1
            assert 'db' not in resolved['services'] or resolved['services']['db']['profiles']
            run(command + ['build', 'web'])
            run(command + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '120', 'web', 'nginx'])
            assert set(run(command + ['ps', '--services']).split()) == {'web', 'nginx'}
            assert not run([docker, 'volume', 'ls', '--filter', 'label=com.docker.compose.project=' + project, '--format', '{{.Name}}']).strip()
            for path, method, expected in [('/', 'GET', 200), ('/', 'POST', 403), ('/logout/', 'GET', 403),
                                           ('/register/', 'GET', 403), ('/admin/login/', 'POST', 403),
                                           ('/api/extension/auth/status/', 'GET', 403), ('/api/notes/', 'GET', 403),
                                           ('/api/improvement-plan/', 'POST', 403), ('/health/', 'GET', 404)]:
                connection = HTTPConnection('127.0.0.1', 18081, timeout=10)
                connection.request(method, path, headers={'Host': '130.210.110.62'})
                response = connection.getresponse()
                assert response.status == expected, (method, path, response.status)
                assert not response.getheader('Set-Cookie') and not response.getheader('Strict-Transport-Security')
                response.read()
                connection.close()
            run(command + ['exec', '-T', 'web', 'python', '-B', 'scripts/verify_http_test.py'])
            print('Docker HTTP checks passed: web/Nginx only, no database/volumes, sensitive routes blocked.')
        finally:
            # No --volumes: this mode must not create or delete any database volume.
            subprocess.run(command + ['down', '--remove-orphans'], cwd=ROOT, env=environment,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', help='Docker executable; enables local container verification')
    arguments = parser.parse_args()
    offline()
    if arguments.docker:
        containers(arguments.docker)
