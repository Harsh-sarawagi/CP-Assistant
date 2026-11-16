"""Run with scripts/verify_http_test.py; all database/network access is forbidden."""
from unittest.mock import patch
from unittest import skipUnless
from django.conf import settings
from django.test import Client, SimpleTestCase
from core.urls import urlpatterns as original_patterns
from core.tests import profile


@skipUnless(settings.ROOT_URLCONF == 'config.http_test_urls', 'Requires the isolated HTTP settings')
class PublicHttpTests(SimpleTestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='130.210.110.62', enforce_csrf_checks=True)
        guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Network forbidden'))
        guard.start()
        self.addCleanup(guard.stop)

    def test_only_readonly_landing_and_liveness(self):
        for route in ['/', '/health/']:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.cookies)
            self.assertNotIn('Strict-Transport-Security', response)
            self.assertNotIn('Location', response)
        self.assertNotContains(self.client.get('/'), '<form')

    def test_public_apis_use_mocked_public_data_only(self):
        data = profile(handle='tourist')
        data['practice'] = {'problems': [], 'note': 'Mocked'}
        for section in ['analytics', 'weaknesses', 'practice']:
            with patch('core.profile_views.get_profile', return_value=data) as fetch:
                response = self.client.get('/api/profiles/tourist/' + section + '/')
                self.assertEqual(response.status_code, 200)
                fetch.assert_called_once_with('tourist')
                self.assertFalse(response.cookies)

    def test_every_original_nonpublic_endpoint_is_blocked(self):
        replacements = {'handle': 'tourist', 'note_id': '1', 'request_id': '11111111-1111-1111-1111-111111111111'}
        for pattern in original_patterns:
            route = str(pattern.pattern)
            for name, converter in pattern.pattern.converters.items():
                route = route.replace('<' + ('str:' if converter.__class__.__name__ == 'StringConverter' and '<str:' in route else 'int:' if converter.__class__.__name__ == 'IntConverter' else 'uuid:') + name + '>', replacements[name])
            if route.startswith('api/profiles/') or not route:
                continue
            self.assertNotIn('<', route)
            for method in ['get', 'head', 'post', 'put', 'patch', 'delete', 'options']:
                with self.subTest(route=route, method=method):
                    response = getattr(self.client, method)('/' + route)
                    self.assertEqual(response.status_code, 403)
                    self.assertFalse(response.cookies)

    def test_default_deny_covers_admin_aliases_encodings_and_future_routes(self):
        for path in ['/admin/', '/admin/login/', '/admin/logout/', '/admin/password_change/',
                     '/accounts/login/', '/accounts/password_reset/', '/password/reset/', '/login/',
                     '/future/private/', '/static/admin/js/core.js', '/logout',
                     '/%6cogout/', '/api/extension/auth/status/?next=/']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path, HTTP_X_FORWARDED_PROTO='https').status_code, 403)
        # Client.get treats //name/ as an authority URL, so supply the raw WSGI path.
        self.assertEqual(self.client.generic('GET', '/', PATH_INFO='//logout/').status_code, 403)

    def test_writes_auth_material_queries_and_method_override_never_reach_public_views(self):
        with patch('core.profile_views.get_profile') as fetch:
            for method in ['post', 'put', 'patch', 'delete', 'options', 'trace']:
                for path in ['/', '/health/', '/api/profiles/tourist/analytics/']:
                    self.assertEqual(getattr(self.client, method)(path).status_code, 403)
            for headers in [{'HTTP_AUTHORIZATION': 'Bearer fixture'}, {'HTTP_COOKIE': 'sessionid=fixture'},
                            {'HTTP_X_HTTP_METHOD_OVERRIDE': 'POST'}, {'CONTENT_LENGTH': '1'}]:
                self.assertEqual(self.client.get('/api/profiles/tourist/analytics/', **headers).status_code, 403)
            self.assertEqual(self.client.get('/api/profiles/tourist/analytics/?password=fixture').status_code, 403)
            fetch.assert_not_called()
