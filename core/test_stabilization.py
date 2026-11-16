"""Regression tests; external HTTP is mocked throughout this module."""
import json
import secrets
from datetime import timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from . import views


@override_settings(AI_API_KEY='mock-only-key')
class AiContractTests(SimpleTestCase):
    def test_completion_format_and_model(self):
        response = Mock(status_code=200, json=lambda: {'choices': [{'message': {'content': 'Review complete'}}]})
        with patch('core.views.requests.post', return_value=response) as post:
            self.assertEqual(views.call_ai_engine('test prompt'), ('Review complete', ''))
        self.assertEqual(post.call_args.kwargs['json']['model'], settings.AI_MODEL_NAME)

    def test_invalid_completion_shapes_are_handled(self):
        for body in [{}, {'choices': []}, {'choices': None}, {'choices': [{'message': {'content': None}}]}]:
            with self.subTest(body=body), patch('core.views.requests.post', return_value=Mock(status_code=200, json=lambda: body)):
                self.assertIn('invalid response', views.call_ai_engine('test')[0])

    def test_rate_limit_network_and_non_json_errors(self):
        for response in [Mock(status_code=429), Mock(status_code=502)]:
            with patch('core.views.requests.post', return_value=response):
                self.assertTrue(views.call_ai_engine('test')[0])
        with patch('core.views.requests.post', side_effect=requests.Timeout()):
            self.assertIn('network', views.call_ai_engine('test')[0])
        with patch('core.views.requests.post', return_value=Mock(status_code=200, json=Mock(side_effect=ValueError()))):
            self.assertIn('invalid response', views.call_ai_engine('test')[0])

    @override_settings(AI_API_KEY='')
    def test_missing_key_never_calls_provider(self):
        with patch('core.views.requests.post') as post:
            self.assertIn('Configuration missing', views.call_ai_engine('test')[0])
        post.assert_not_called()

    def test_structured_review_validation_and_line_numbers(self):
        from copy import deepcopy
        from .services.code_review import parse_review, source_lines, review_prompt
        source = 'int main() {\n  return 0;\n}'
        valid = {'summary': 'No correctness defect identified', 'language': 'C++', 'complexity': 'O(1)',
                 'issues': [{'line_start': 2, 'line_end': 2, 'severity': 'suggestion', 'title': 'Style',
                             'explanation': 'A suggestion', 'suggested_fix': 'Keep readable names.'}],
                 'topics': ['code style'], 'corrected_code': source}
        result = parse_review('```json\n' + json.dumps(valid) + '\n```', source)
        self.assertEqual(result['issues'][0]['excerpt'], '  return 0;')
        self.assertEqual([line['number'] for line in source_lines(source)], [1, 2, 3])
        self.assertEqual([line['highlight'] for line in source_lines(source, result['issues'])], [False, True, False])
        for change in [{'line_start': 0}, {'line_end': 4}, {'line_start': True}, {'line_start': 3, 'line_end': 2}, {'severity': 'accepted'}]:
            bad = deepcopy(valid); bad['issues'][0].update(change)
            self.assertIsNone(parse_review(json.dumps(bad), source))
        for key, value in [('issues', {}), ('topics', 'dp'), ('corrected_code', ''), ('summary', None)]:
            bad = deepcopy(valid); bad[key] = value
            self.assertIsNone(parse_review(json.dumps(bad), source))
        for content in ['', 'incomplete {', '[]', None]:
            self.assertIsNone(parse_review(content, source))
        self.assertIn('not a Codeforces verdict', review_prompt('url', 'statement', 'tutorial', source, 'C++'))

    def test_completion_token_budget_is_opt_in(self):
        response = Mock(status_code=200, json=lambda: {'choices': [{'message': {'content': '{}'}}]})
        with patch('core.views.requests.post', return_value=response) as post:
            views.call_ai_engine('test', max_tokens=8192)
            self.assertEqual(post.call_args.kwargs['json']['max_tokens'], 8192)
            views.call_ai_engine('test')
            self.assertNotIn('max_tokens', post.call_args.kwargs['json'])


@override_settings(ALLOWED_HOSTS=['testserver', 'localhost'])
class AuthenticationIntegrationTests(TestCase):
    """All created users/sessions are rolled back by Django TestCase."""
    def setUp(self):
        self.http_guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected outbound HTTP'))
        self.http_guard.start()
        self.addCleanup(self.http_guard.stop)
        self.username = 'verify_' + uuid4().hex
        self.password = secrets.token_urlsafe(24)
        self.user = get_user_model().objects.create_user(username=self.username, password=self.password, codeforces_handle='cf_' + uuid4().hex)

    def test_registration_hash_and_session_persistence(self):
        name = 'register_' + uuid4().hex
        response = self.client.post('/register/', {'username': name, 'email': 'verify@example.invalid', 'password1': self.password, 'password2': self.password})
        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        user = get_user_model().objects.get(username=name)
        self.assertNotEqual(user.password, self.password)
        self.assertTrue(user.check_password(self.password))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertEqual(self.client.get('/dashboard/').status_code, 200)

    def test_valid_invalid_login_and_logout_invalidation(self):
        self.client.post('/', {'username': self.username, 'password': 'incorrect'})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.client.post('/', {'username': self.username, 'password': self.password})
        self.assertEqual(self.client.get('/dashboard/').status_code, 200)
        key = self.client.session.session_key
        self.assertTrue(Session.objects.filter(session_key=key).exists())
        self.client.get('/logout/')
        self.assertFalse(Session.objects.filter(session_key=key).exists())
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)

    def test_protected_routes_and_profile_persistence(self):
        for path in ['/dashboard/', '/profile/', '/profile/update/', '/ai-review/', '/weak-spot/']:
            self.assertEqual(self.client.get(path).status_code, 302)
        self.client.login(username=self.username, password=self.password)
        handle = 'updated_' + uuid4().hex
        response = self.client.post('/profile/update/', {'email': 'updated@example.invalid', 'codeforces_handle': handle})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.codeforces_handle, handle)
        self.assertEqual(self.user.email, 'updated@example.invalid')

    def test_expired_sessions_and_unauthorized_requests_never_invoke_ai(self):
        self.client.login(username=self.username, password=self.password)
        Session.objects.filter(session_key=self.client.session.session_key).update(expire_date=timezone.now() - timedelta(seconds=1))
        with patch('core.views.call_ai_engine') as ai:
            self.assertEqual(self.client.get('/dashboard/').status_code, 302)
            ai.assert_not_called()

    def test_csrf_required_for_login_and_profile_but_not_readonly_api(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/', {'username': self.username, 'password': self.password}).status_code, 403)
        client.login(username=self.username, password=self.password)
        self.assertEqual(client.post('/profile/update/', {'email': 'test@example.invalid'}).status_code, 403)

    def test_valid_csrf_login_and_profile_update(self):
        client = Client(enforce_csrf_checks=True)
        with patch('core.views.requests.get', return_value=Mock(status_code=200, json=lambda: {'data': {}})):
            self.assertEqual(client.get('/').status_code, 200)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post('/', {'username': self.username, 'password': self.password, 'csrfmiddlewaretoken': token})
        self.assertRedirects(response, '/dashboard/', fetch_redirect_response=False)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post('/profile/update/', {'email': 'csrf@example.invalid', 'codeforces_handle': self.user.codeforces_handle, 'csrfmiddlewaretoken': token})
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'csrf@example.invalid')

    def test_review_with_mocked_ai(self):
        self.client.force_login(self.user)
        review = {'summary': 'Review verified', 'language': 'C++', 'complexity': 'O(1) time and space',
                  'issues': [{'line_start': 1, 'line_end': 1, 'severity': 'suggestion', 'title': 'Clearer entry point',
                              'explanation': 'Use a readable style.', 'suggested_fix': 'Return zero explicitly.'}],
                  'topics': ['code style'], 'corrected_code': 'int main() { return 0; }'}
        with patch('core.views.scrape_codeforces_data', return_value={'problem': 'Statement', 'tutorial': 'Tutorial'}), patch('core.views.call_ai_engine', return_value=(json.dumps(review), '')) as ai:
            response = self.client.post('/ai-review/', {'problem_link': 'https://codeforces.com/problemset/problem/1/A', 'code': 'int main() {}'})
            self.assertContains(response, 'Review verified')
            self.assertContains(response, 'code-line-issue')
            self.assertContains(response, 'int main() { return 0; }')
            self.assertEqual(response.context['review']['issues'][0]['excerpt'], 'int main() {}')
            self.assertEqual(response.context['form'].cleaned_data['language'], '')
            self.assertEqual(ai.call_args.kwargs['max_tokens'], 8192)
            ai.assert_called_once()

    def test_retired_weak_spot_redirects_without_ai(self):
        self.client.force_login(self.user)
        with patch('core.views.call_ai_engine') as ai:
            for method in [self.client.get, self.client.post]:
                self.assertRedirects(method('/weak-spot/'), '/profile/', fetch_redirect_response=False)
            ai.assert_not_called()

    def test_dashboard_shows_current_tools_and_owner_counts(self):
        from .models import PersonalNote
        self.client.force_login(self.user)
        PersonalNote.objects.create(owner=self.user, title='A lesson', content='Keep it')
        response = self.client.get('/dashboard/')
        self.assertEqual(response.context['note_count'], 1)
        self.assertEqual(response.context['connection_count'], 0)
        self.assertContains(response, 'Personal notebook')
        self.assertContains(response, 'Profile companion')
        self.assertContains(response, 'AI code review')
        self.assertNotContains(response, '/weak-spot/')
        self.assertNotContains(response, 'Generate Roadmap')

    def test_review_failures_preserve_source_and_do_not_retry_ai(self):
        self.client.force_login(self.user)
        fields = {'problem_link': 'https://codeforces.com/problemset/problem/1/A', 'code': 'print(1)'}
        with patch('core.views.scrape_codeforces_data', return_value={'problem': 'Could not fetch problem.'}), patch('core.views.call_ai_engine') as ai:
            response = self.client.post('/ai-review/', fields)
            self.assertContains(response, 'no AI request was made')
            self.assertContains(response, 'print(1)')
            ai.assert_not_called()
        with patch('core.views.scrape_codeforces_data', return_value={'problem': 'Statement'}), patch('core.views.call_ai_engine', return_value=('not JSON', '')) as ai:
            response = self.client.post('/ai-review/', fields)
            self.assertContains(response, 'Your source is preserved')
            self.assertContains(response, 'print(1)')
            ai.assert_called_once()

    def test_review_renders_untrusted_code_and_feedback_as_text(self):
        self.client.force_login(self.user)
        attack = '</script><img src=x onerror=alert(1)>'
        review = {'summary': attack, 'language': attack, 'complexity': attack, 'issues': [], 'topics': [attack], 'corrected_code': attack}
        with patch('core.views.scrape_codeforces_data', return_value={'problem': attack}), patch('core.views.call_ai_engine', return_value=(json.dumps(review), '')):
            response = self.client.post('/ai-review/', {'problem_link': 'https://codeforces.com/contest/1/problem/A', 'code': attack})
        self.assertContains(response, '&lt;img')
        self.assertNotContains(response, '<img src=x')
        self.assertNotContains(response, '</script><img')
        self.assertContains(response, 'copy-sources')

    def test_review_validation_and_csrf_do_not_invoke_provider(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.client.force_login(self.user)
        with patch('core.views.call_ai_engine') as ai, patch('core.views.scrape_codeforces_data') as scrape:
            self.assertEqual(client.post('/ai-review/', {'code': 'x'}).status_code, 403)
            for data in [{'problem_link': 'http://evil.test/1/A', 'code': 'x'},
                         {'problem_link': 'https://codeforces.com/problemset/problem/1/A', 'code': 'x' * 40001}]:
                self.assertEqual(self.client.post('/ai-review/', data).status_code, 200)
            ai.assert_not_called(); scrape.assert_not_called()
