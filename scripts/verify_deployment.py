"""Build and test a fresh isolated Compose database; never uses .env.production or .env.

Requires a running Docker engine. Uses loopback ports 18080/18443 and a temporary
self-signed certificate trusted only by this script. Only its own test volume is removed.
"""
import argparse
from http.client import HTTPConnection, HTTPSConnection
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import ssl
import subprocess
import tempfile
from urllib.parse import parse_qs, urlencode, urlsplit

from prepare_production import prepare

ROOT = Path(__file__).resolve().parent.parent
CLIENT = 'a' * 32
BASE = 'https://localhost:18443'

CERTIFICATE = '''
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta, timezone
from pathlib import Path
key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
now = datetime.now(timezone.utc)
cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
    .public_key(key.public_key()).serial_number(x509.random_serial_number())
    .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=2))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]),critical=False)
    .add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
    .sign(key,hashes.SHA256()))
Path('/certs/fullchain.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
Path('/certs/privkey.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
Path('/certs/privkey.pem').chmod(0o600)
'''

PROBE = '''
import os
assert os.environ['DB_HOST']=='db' and os.environ['DB_NAME'].startswith('cp_verify_')
os.environ['DJANGO_SETTINGS_MODULE']='config.production'
import django
django.setup()
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.contrib.auth import get_user_model
from core.models import PersonalNote
assert not settings.DEBUG and settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE
assert settings.SECURE_PROXY_SSL_HEADER == ('HTTP_X_FORWARDED_PROTO','https')
assert not settings.AI_API_KEY
assert Path('/app/staticfiles/staticfiles.json').is_file()
assert all(not Path('/app', p).exists() for p in ['.env','.env.production','.venv','db.sqlite3','db.sqlite3.backup'])
with connection.cursor() as c:
    c.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user')
    assert c.fetchone()[0] is False
if PHASE == 'persisted':
    user=get_user_model().objects.get(username='deployment_verify')
    assert PersonalNote.objects.filter(owner=user,title='Persistence probe',content='Temporary isolated test').exists()
if PHASE == 'mock_ai':
    from unittest.mock import patch
    from django.test import Client
    user=get_user_model().objects.get(username='deployment_verify')
    client=Client(HTTP_HOST='localhost')
    client.force_login(user)
    result={'summary':'Mock review verified','language':'Python','complexity':'O(1)', 'issues':[], 'topics':[], 'corrected_code':'print(1)'}
    import json
    with patch('requests.sessions.Session.request',side_effect=AssertionError('Live HTTP forbidden')), patch('core.views.scrape_codeforces_data',return_value={'problem':'Mock statement'}), patch('core.views.call_ai_engine',return_value=(json.dumps(result),'')) as ai:
        response=client.post('/ai-review/',{'problem_link':'https://codeforces.com/problemset/problem/1/A','code':'print(1)'},secure=True)
        assert response.status_code==200 and b'Mock review verified' in response.content
        ai.assert_called_once()
print('Container checks passed:',PHASE)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker', default=shutil.which('docker') or 'docker')
    parser.add_argument('--image', default='cp-assistant:verification')
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--skip-regressions', action='store_true', help='For focused reruns after the full application suite has passed')
    parser.add_argument('--platform', help='Optional native/available emulated target, e.g. linux/arm64')
    args = parser.parse_args()
    project = 'cp-assistant-verify-' + secrets.token_hex(5)
    assert re.fullmatch(r'cp-assistant-verify-[0-9a-f]{10}', project)
    environment = os.environ.copy()
    if args.platform:
        environment['DOCKER_DEFAULT_PLATFORM'] = args.platform
    with tempfile.TemporaryDirectory(prefix=project + '-') as directory:
        folder = Path(directory).resolve()
        assert folder.is_relative_to(Path(tempfile.gettempdir()).resolve())
        envfile = folder / 'test.env'
        prepare(envfile, 'localhost', CLIENT)
        with envfile.open('a', encoding='utf-8') as stream:
            stream.write(f'\nAPP_IMAGE={args.image}\nHTTP_BIND=127.0.0.1\nHTTPS_BIND=127.0.0.1\nHTTP_PORT=18080\nHTTPS_PORT=18443\nCSRF_TRUSTED_ORIGINS={BASE}\n')
            stream.write(f'DB_NAME=cp_verify_{secrets.token_hex(5)}\nLETSENCRYPT_DIR={(folder / "certificates").as_posix()}\nACME_WEBROOT={(folder / "acme").as_posix()}\n')
        # Shell exports take precedence over --env-file in Compose. Never inherit
        # production credentials, host mounts, public bindings or an AI key.
        for name in re.findall(r'^([A-Z_][A-Z_0-9]*)=', envfile.read_text(), re.M):
            environment.pop(name, None)
        environment.pop('NGINX_TEMPLATE', None)
        leaf = folder / 'certificates' / 'live' / 'localhost'
        leaf.mkdir(parents=True)
        (folder / 'acme').mkdir()
        docker = [args.docker]
        compose = docker + ['compose', '--env-file', str(envfile), '--project-name', project, '-f', str(ROOT / 'compose.yaml')]

        def run(command, source=None):
            result = subprocess.run(command, input=source, cwd=ROOT, env=environment, text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if result.returncode:
                diagnostic = result.stderr or result.stdout or 'No diagnostic returned.'
                for line in envfile.read_text().splitlines():
                    if '=' in line:
                        key, value = line.split('=', 1)
                        if value and any(word in key for word in ['PASSWORD', 'SECRET', 'API_KEY', 'TOKEN']):
                            diagnostic = diagnostic.replace(value, '[redacted]')
                raise RuntimeError('Docker operation failed for ' + project + ':\n' + diagnostic[-1800:])
            if command[-3:] == ['manage.py', 'check', '--deploy']:
                warnings = sorted(set(re.findall(r'security\.W[0-9]+', result.stderr)))
                print('Production checks passed; warnings: ' + (', '.join(warnings) or 'none'), flush=True)
            if 'scripts/verify_project.py' in command:
                count = re.search(r'Ran ([0-9]+) tests', result.stderr)
                if count:
                    print('Application tests passed: ' + count[1], flush=True)
            return result.stdout

        def probe(phase):
            run(compose + ['exec', '-T', 'web', 'python', '-B', '-'], 'PHASE=' + repr(phase) + '\n' + PROBE)

        cookies = {}
        context = None

        def request(path, data=None, method='GET', headers=None, session=True, json_body=False):
            outgoing = dict(headers or {})
            if session and cookies:
                outgoing['Cookie'] = '; '.join(k + '=' + v for k, v in cookies.items())
            if data is not None:
                outgoing['Content-Type'] = 'application/json' if json_body else 'application/x-www-form-urlencoded'
                outgoing['Referer'] = BASE + path
            connection = HTTPSConnection('localhost', 18443, context=context, timeout=30)
            connection.request(method, path, body=(json.dumps(data) if json_body else urlencode(data)) if data is not None else None, headers=outgoing)
            response = connection.getresponse()
            body, fields = response.read(), dict(response.getheaders())
            for name, value in response.getheaders():
                if name.lower() == 'set-cookie' and session:
                    parsed = SimpleCookie(value)
                    for key, morsel in parsed.items():
                        if morsel.value: cookies[key] = morsel.value
                        else: cookies.pop(key, None)
                        if key in ['sessionid', 'csrftoken'] and morsel.value:
                            assert morsel['secure'], 'Missing Secure cookie flag'
            status = response.status
            connection.close()
            return status, fields, body

        def csrf(body):
            return re.search(rb'name="csrfmiddlewaretoken" value="([^"]+)"', body).group(1).decode()

        def api(path, data=None, method='GET', token=None):
            headers = {'Origin': 'chrome-extension://' + CLIENT}
            if token: headers['Authorization'] = 'Bearer ' + token
            status, fields, body = request(path, data, method, headers, session=False, json_body=True)
            return status, fields, json.loads(body)

        try:
            run(docker + ['version', '--format', '{{.Server.Version}}'])
            run(compose + ['config', '--quiet'])
            resolved = json.loads(run(compose + ['config', '--format', 'json']))
            assert set(resolved['services']) == {'web', 'db', 'nginx'}
            assert all(0 < float(service['cpus']) <= 1.0 for service in resolved['services'].values())
            assert not resolved['services']['web'].get('ports') and not resolved['services']['db'].get('ports')
            if not args.skip_build:
                print('Building image...', flush=True)
                run(compose + ['build', 'web'])
            architecture = run(docker + ['image', 'inspect', '--format', '{{.Architecture}}', args.image]).strip()
            if args.platform:
                assert architecture == args.platform.split('/')[-1], 'Image architecture does not match target'
            print('Image architecture verified: ' + architecture, flush=True)
            print('Pulling matching PostgreSQL/Nginx images...', flush=True)
            for service in ['db', 'nginx']:
                pull = docker + ['pull']
                if args.platform:
                    pull += ['--platform', args.platform]
                run(pull + [resolved['services'][service]['image']])
            run(docker + ['run', '--rm', '--network', 'none', '--user', '0', '-i', '--mount', f'type=bind,source={leaf},target=/certs', '--entrypoint', 'python', args.image, '-'], CERTIFICATE)
            context = ssl.create_default_context(cafile=str(leaf / 'fullchain.pem'))
            print('Starting isolated PostgreSQL and applying test migrations...', flush=True)
            run(compose + ['up', '-d', '--wait', '--wait-timeout', '120', 'db'])
            run(compose + ['run', '--rm', '--no-deps', '-T', 'web', 'python', 'manage.py', 'migrate', '--noinput'])
            run(compose + ['run', '--rm', '--no-deps', '-T', 'web', 'python', 'manage.py', 'check', '--deploy'])
            run(compose + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '120'])
            probe('settings')
            plain = HTTPConnection('localhost', 18080, timeout=10)
            plain.request('GET', '/register/', headers={'Host': 'localhost'})
            redirect = plain.getresponse()
            assert redirect.status == 301 and redirect.getheader('Location') == 'https://localhost/register/'
            redirect.read()
            plain.close()
            assert request('/health/')[0] == 404
            assert request('/dashboard/')[0] == 302
            status, _, body = request('/register/')
            assert status == 200
            password = secrets.token_urlsafe(24)
            assert request('/register/', {'username': 'deployment_verify', 'email': 'verify@example.invalid', 'codeforces_handle': 'VerifyHandle', 'password1': password, 'password2': password, 'csrfmiddlewaretoken': csrf(body)}, 'POST')[0] == 302
            assert request('/dashboard/')[0] == 200
            css = re.search(rb'href="([^"]*workspace\.[^\"]*\.css)"', request('/dashboard/')[2]).group(1).decode()
            assert request(css)[0] == 200
            status, _, review_form = request('/ai-review/')
            assert status == 200
            # Reject an invalid problem URL before any provider/network call while
            # verifying Nginx accepts the editor's existing Unicode size limit.
            assert request('/ai-review/', {'problem_link': 'https://invalid.example/problem', 'code': '\U0001f600' * 40000,
                                          'csrfmiddlewaretoken': csrf(review_form)}, 'POST')[0] == 200
            assert request('/logout/')[0] == 405
            assert request('/logout/', {'csrfmiddlewaretoken': csrf(review_form)}, 'POST')[0] == 302
            _, _, page = request('/register/')
            token = csrf(page)
            assert request('/', {'username': 'deployment_verify', 'password': 'invalid', 'csrfmiddlewaretoken': token}, 'POST')[0] == 302
            assert request('/dashboard/')[0] == 302
            assert request('/', {'username': 'deployment_verify', 'password': password, 'csrfmiddlewaretoken': token}, 'POST')[0] == 302
            assert request('/dashboard/')[0] == 200
            # Exercise the real HTTPS reverse proxy and PKCE flow without following chromiumapp redirects.
            import hashlib, base64
            verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            status, _, start = api('/api/extension/auth/start/', {'client_id': CLIENT, 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'redirect_uri': f'https://{CLIENT}.chromiumapp.org/callback'}, 'POST')
            assert status == 201 and start['authorization_url'].startswith(BASE + '/')
            authorize = urlsplit(start['authorization_url'])
            path = authorize.path + '?' + authorize.query
            status, _, page = request(path)
            assert status == 200
            status, fields, _ = request(path, {'state': state, 'decision': 'approve', 'csrfmiddlewaretoken': csrf(page)}, 'POST')
            assert status == 302
            query = parse_qs(urlsplit(fields['Location']).query)
            status, _, authorization = api('/api/extension/auth/exchange/', {'client_id': CLIENT, 'request_id': start['request_id'], 'state': state, 'code': query['code'][0], 'code_verifier': verifier}, 'POST')
            assert status == 200
            access = authorization['access_token']
            assert api('/api/extension/notes/')[0] == 401
            assert api('/api/extension/notes/', {'title': 'Persistence probe', 'content': 'Temporary isolated test'}, 'POST', access)[0] == 201
            assert api('/api/extension/notes/', token=access)[2]['count'] == 1
            preflight = request('/api/extension/notes/', method='OPTIONS', headers={'Origin': 'chrome-extension://' + CLIENT, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'Authorization,Content-Type'}, session=False)
            assert preflight[0] == 204 and preflight[1]['Access-Control-Allow-Origin'] == 'chrome-extension://' + CLIENT
            probe('mock_ai')
            if not args.skip_regressions:
                run(compose + ['exec', '-T', 'web', 'env', 'DJANGO_SETTINGS_MODULE=config.settings', 'python', '-B', 'scripts/verify_project.py', '--postgres'])
                print('Full application regression suite passed in isolated PostgreSQL.', flush=True)
            print('HTTPS, authentication, extension PKCE/CORS, static files and mocked review passed.', flush=True)
            # Remove only this project's containers, preserving its named database volume.
            run(compose + ['stop'])
            run(compose + ['rm', '-f'])
            run(compose + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '120'])
            probe('persisted')
            assert request('/dashboard/')[0] == 200
            # Long emulated test suites can outlive the ten-minute access lifetime.
            # The real worker renews automatically; verify that persisted renewal too.
            status, _, renewed = api('/api/extension/auth/refresh/', {'client_id': CLIENT, 'refresh_token': authorization['refresh_token']}, 'POST')
            assert status == 200, renewed.get('error', 'Refresh failed')
            status, _, saved = api('/api/extension/notes/', token=renewed['access_token'])
            assert status == 200, saved.get('error', 'Notebook read failed')
            assert saved['count'] == 1
            print('PostgreSQL user/note/session/grant persistence after container recreation passed.', flush=True)
        finally:
            # This randomly named project has no external volumes or host database connection.
            assert project.startswith('cp-assistant-verify-')
            subprocess.run(compose + ['down', '--volumes', '--remove-orphans'], cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print('Isolated deployment checks passed. Production/local databases were not used.')


if __name__ == '__main__':
    main()
