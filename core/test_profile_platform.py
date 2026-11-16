import importlib
import json
import secrets
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from .models import ExtensionGrant, ExtensionLinkRequest, AIPlanQuota, MistakeNote, PersonalNote
from .services.extension_auth import challenge, digest
from .services import improvement
from .tests import profile

CLIENT_ID = 'a' * 32
ORIGIN = 'chrome-extension://' + CLIENT_ID
PLAN = {'major_areas': ['Build judged history'], 'topics_to_learn': ['math'], 'learning_order': ['Review basics', 'Practise'],
        'practice_strategy': 'Try two suitable problems with breaks.', 'supported_patterns': [], 'short_term_plan': [{'day': 'Day 1', 'task': 'Solve an 800-rated problem.'}]}


@override_settings(ALLOWED_HOSTS=['localhost', 'testserver', 'example.test'], EXTENSION_ALLOWED_IDS={CLIENT_ID})
class PlatformTestCase(TestCase):
    def setUp(self):
        cache.clear()
        guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Live HTTP forbidden in tests'))
        guard.start(); self.addCleanup(guard.stop)
        self.user = get_user_model().objects.create_user(username='platform_' + uuid4().hex)
        self.client = Client(HTTP_HOST='localhost', enforce_csrf_checks=True)

    def post(self, path, data, client=None, method='post', headers=None):
        return getattr(client or self.client, method)(path, data=json.dumps(data), content_type='application/json', **{'HTTP_ORIGIN': ORIGIN, **(headers or {})})

    def connect(self, user=None):
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        start = self.post('/api/extension/auth/start/', {'client_id': CLIENT_ID, 'state': state, 'code_challenge': challenge(verifier), 'code_challenge_method': 'S256', 'redirect_uri': f'https://{CLIENT_ID}.chromiumapp.org/callback'})
        self.assertEqual(start.status_code, 201)
        flow = start.json()
        website = Client(HTTP_HOST='localhost', enforce_csrf_checks=True)
        website.force_login(user or self.user)
        page = website.get(flow['authorization_url'])
        self.assertEqual(page.status_code, 200)
        token = website.cookies[settings.CSRF_COOKIE_NAME].value
        approved = website.post(flow['authorization_url'], {'state': state, 'decision': 'approve', 'csrfmiddlewaretoken': token})
        self.assertEqual(approved.status_code, 302)
        query = parse_qs(urlsplit(approved['Location']).query)
        proof = {'client_id': CLIENT_ID, 'state': state, 'request_id': flow['request_id'], 'code': query['code'][0], 'code_verifier': verifier}
        exchanged = self.post('/api/extension/auth/exchange/', proof)
        self.assertEqual(exchanged.status_code, 200)
        return exchanged.json(), proof, website

    def bearer(self, token):
        return {'HTTP_AUTHORIZATION': 'Bearer ' + token, 'HTTP_ORIGIN': ORIGIN}


class ExtensionAuthorizationTests(PlatformTestCase):
    def test_linked_handle_metadata_is_authenticated_and_refreshes(self):
        self.user.codeforces_handle = 'LinkedHandle'
        self.user.save(update_fields=['codeforces_handle'])
        tokens, _, _ = self.connect()
        self.assertEqual(tokens['account']['codeforces_handle'], 'LinkedHandle')
        anonymous = self.client.get('/api/extension/auth/status/', HTTP_ORIGIN=ORIGIN).json()
        self.assertNotIn('account', anonymous)
        self.user.codeforces_handle = 'UpdatedHandle'
        self.user.save(update_fields=['codeforces_handle'])
        response = self.client.get('/api/extension/auth/status/', **self.bearer(tokens['access_token']))
        self.assertEqual(response.json()['account']['codeforces_handle'], 'UpdatedHandle')
        refreshed = self.post('/api/extension/auth/refresh/', {'client_id': CLIENT_ID, 'refresh_token': tokens['refresh_token']})
        self.assertEqual(refreshed.json()['account']['codeforces_handle'], 'UpdatedHandle')

    def test_connection_requires_approval_and_code_replay_is_rejected(self):
        tokens, proof, _ = self.connect()
        self.assertTrue(bool(tokens['access_token']))
        self.assertNotEqual(digest(tokens['refresh_token']), tokens['refresh_token'])
        self.assertEqual(self.post('/api/extension/auth/exchange/', proof).status_code, 400)
        grant = ExtensionGrant.objects.get(user=self.user)
        self.assertTrue(grant.access_hash == digest(tokens['access_token']))

    def test_refresh_rotation_reuse_revokes_family(self):
        tokens, _, _ = self.connect()
        request = {'client_id': CLIENT_ID, 'refresh_token': tokens['refresh_token']}
        rotated = self.post('/api/extension/auth/refresh/', request)
        self.assertEqual(rotated.status_code, 200)
        newer = rotated.json()
        self.assertTrue(newer['refresh_token'] != tokens['refresh_token'])
        self.assertEqual(self.post('/api/extension/auth/refresh/', request).status_code, 401)
        self.assertIsNotNone(ExtensionGrant.objects.get(user=self.user).revoked_at)
        self.assertEqual(self.client.get('/api/extension/auth/status/', **self.bearer(newer['access_token'])).status_code, 401)

    def test_expired_access_can_refresh_but_expired_authorization_cannot(self):
        tokens, _, _ = self.connect()
        ExtensionGrant.objects.filter(user=self.user).update(access_expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.client.get('/api/extension/auth/status/', **self.bearer(tokens['access_token'])).status_code, 401)
        rotated = self.post('/api/extension/auth/refresh/', {'client_id': CLIENT_ID, 'refresh_token': tokens['refresh_token']})
        self.assertEqual(rotated.status_code, 200)
        ExtensionGrant.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.post('/api/extension/auth/refresh/', {'client_id': CLIENT_ID, 'refresh_token': rotated.json()['refresh_token']}).status_code, 401)

    def test_revocation_and_scopes(self):
        tokens, _, _ = self.connect()
        headers = self.bearer(tokens['access_token'])
        ExtensionGrant.objects.filter(user=self.user).update(scopes='notes:read')
        self.assertEqual(self.post('/api/extension/notes/', {'title': 'x', 'content': 'x'}, headers=headers).status_code, 403)
        self.assertEqual(self.post('/api/extension/improvement-plan/', {'handle': 'example'}, headers=headers).status_code, 403)
        self.assertEqual(self.post('/api/extension/auth/revoke/', {}, headers=headers).status_code, 200)
        self.assertEqual(self.client.get('/api/extension/notes/', **headers).status_code, 401)

    def test_state_pkce_expiry_and_redirect_validation(self):
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        data = {'client_id': CLIENT_ID, 'state': state, 'code_challenge': challenge(verifier), 'code_challenge_method': 'S256', 'redirect_uri': 'https://evil.invalid/callback'}
        self.assertEqual(self.post('/api/extension/auth/start/', data).status_code, 403)
        data['redirect_uri'] = f'https://{CLIENT_ID}.chromiumapp.org/callback'
        started = self.post('/api/extension/auth/start/', data).json()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(started['authorization_url'].replace(state, 'wrong-state')).status_code, 400)
        flow = ExtensionLinkRequest.objects.get(pk=started['request_id'])
        code = secrets.token_urlsafe(32)
        flow.user = self.user; flow.code_hash = digest(code); flow.code_expires_at = timezone.now() + timedelta(seconds=60); flow.save()
        payload = {'client_id': CLIENT_ID, 'state': state, 'request_id': str(flow.pk), 'code': code, 'code_verifier': secrets.token_urlsafe(64)}
        self.assertEqual(self.post('/api/extension/auth/exchange/', payload).status_code, 400)
        payload['code_verifier'] = verifier
        flow.code_expires_at = timezone.now() - timedelta(seconds=1); flow.save()
        self.assertEqual(self.post('/api/extension/auth/exchange/', payload).status_code, 400)

    def test_cookie_session_does_not_substitute_extension_authorization(self):
        self.client.force_login(self.user)
        status = self.client.get('/api/extension/auth/status/').json()
        self.assertTrue(status['website_session_active'])
        self.assertFalse(status['authenticated'])
        self.assertEqual(self.client.get('/api/extension/notes/').status_code, 401)

    def test_origin_allowlist_preflight_and_production_https(self):
        good = self.client.options('/api/extension/auth/start/', HTTP_ORIGIN=ORIGIN)
        self.assertEqual(good.status_code, 204)
        self.assertEqual(good['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(self.client.options('/api/extension/notes/', HTTP_ORIGIN='https://evil.invalid').status_code, 403)
        self.assertEqual(self.post('/api/extension/auth/start/', {}, headers={'HTTP_HOST': 'example.test'}).status_code, 403)

    def test_authorization_approval_is_csrf_protected(self):
        state = secrets.token_urlsafe(32)
        flow = ExtensionLinkRequest.objects.create(extension_id=CLIENT_ID, state_hash=digest(state), challenge=challenge(secrets.token_urlsafe(64)), expires_at=timezone.now() + timedelta(minutes=5))
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(f'/extension/authorize/{flow.pk}/', {'state': state, 'decision': 'approve'}).status_code, 403)

    def test_existing_login_and_new_registration_resume_connection(self):
        state = secrets.token_urlsafe(32)
        flow = ExtensionLinkRequest.objects.create(extension_id=CLIENT_ID, state_hash=digest(state), challenge=challenge(secrets.token_urlsafe(64)), expires_at=timezone.now() + timedelta(minutes=5))
        target = f'/extension/authorize/{flow.pk}/?state={state}'
        password = secrets.token_urlsafe(24)
        client = Client(HTTP_HOST='localhost')
        response = client.post('/register/?next=' + target, {'username': 'new_' + uuid4().hex, 'password1': password, 'password2': password, 'next': target})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'] == target)
        self.assertContains(client.get(target), 'Approve connection')

    def test_denial_and_unknown_extension_never_issue_grant(self):
        state = secrets.token_urlsafe(32)
        begin = self.post('/api/extension/auth/start/', {'client_id': 'b' * 32, 'state': state})
        self.assertEqual(begin.status_code, 403)
        flow = ExtensionLinkRequest.objects.create(extension_id=CLIENT_ID, state_hash=digest(state), challenge=challenge(secrets.token_urlsafe(64)), expires_at=timezone.now() + timedelta(minutes=5))
        self.client.force_login(self.user)
        self.client.get(f'/extension/authorize/{flow.pk}/?state={state}')
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        denied = self.client.post(f'/extension/authorize/{flow.pk}/', {'state': state, 'decision': 'deny', 'csrfmiddlewaretoken': token})
        self.assertEqual(denied.status_code, 302)
        self.assertTrue('access_denied' in denied['Location'])
        self.assertFalse(ExtensionGrant.objects.filter(user=self.user).exists())

    def test_website_revoke_invalidates_tokens_and_checks_ownership(self):
        tokens, _, website = self.connect()
        page = website.get('/extension/connections/')
        self.assertContains(page, 'Revoke this connection')
        csrf = website.cookies[settings.CSRF_COOKIE_NAME].value
        grant = ExtensionGrant.objects.get(user=self.user)
        self.assertEqual(website.post('/extension/connections/', {'grant_id': str(grant.pk), 'csrfmiddlewaretoken': csrf}).status_code, 302)
        self.assertEqual(self.client.get('/api/extension/notes/', **self.bearer(tokens['access_token'])).status_code, 401)


class NotebookAndPublicTests(PlatformTestCase):
    def test_public_analytics_anonymous_and_no_account_enumeration(self):
        with patch('core.profile_views.get_profile', return_value=profile(handle='viewedB')), patch('core.views.call_ai_engine') as ai:
            result = self.client.get('/api/profiles/viewedB/analytics/')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['summary']['handle'], 'viewedB')
            self.assertNotIn('registered', result.json())
            self.assertNotIn('user', result.json())
            self.assertNotIn('_attempted_keys', result.json())
            ai.assert_not_called()
        self.assertEqual(self.client.get('/api/extension/context/').status_code, 404)

    def test_owner_not_viewed_handle_controls_private_notebook(self):
        tokens, _, _ = self.connect(); headers = self.bearer(tokens['access_token'])
        other = get_user_model().objects.create_user(username='other_' + uuid4().hex, codeforces_handle='viewedB')
        private = PersonalNote.objects.create(owner=other, title='Private', content='Never expose')
        created = self.post('/api/extension/notes/', {'title': 'My note', 'content': 'My lesson', 'topic': 'dp', 'owner': other.pk}, headers=headers)
        self.assertEqual(created.status_code, 201)
        identifier = created.json()['id']
        self.assertEqual(PersonalNote.objects.get(pk=identifier).owner_id, self.user.pk)
        self.assertEqual(self.client.get(f'/api/extension/notes/{private.pk}/', **headers).status_code, 404)
        self.assertEqual(self.post(f'/api/extension/notes/{private.pk}/', {'updated_at': private.updated_at.isoformat()}, method='delete', headers=headers).status_code, 404)
        self.assertEqual(self.client.get('/api/extension/notes/', **headers).json()['count'], 1)

    def test_crud_search_filter_sort_and_stale_update(self):
        tokens, _, _ = self.connect(); headers = self.bearer(tokens['access_token'])
        created = self.post('/api/extension/notes/', {'title': 'DP', 'content': 'Memoization', 'topic': 'dp'}, headers=headers).json()
        path = f"/api/extension/notes/{created['id']}/"
        self.assertEqual(self.client.get('/api/extension/notes/?q=Memo&topic=dp', **headers).json()['count'], 1)
        updated = self.post(path, {**created, 'content': 'Tabulation'}, method='put', headers=headers)
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(self.post(path, created, method='put', headers=headers).status_code, 409)
        self.assertEqual(self.post(path, {'updated_at': updated.json()['updated_at']}, method='delete', headers=headers).status_code, 200)
        self.assertFalse(PersonalNote.objects.filter(pk=created['id']).exists())

    def test_website_and_extension_share_notes_and_escape_xss(self):
        tokens, _, website = self.connect(); headers = self.bearer(tokens['access_token'])
        created = self.post('/api/extension/notes/', {'title': '<img src=x onerror=alert(1)>', 'content': '<script>alert(1)</script>'}, headers=headers)
        self.assertEqual(created.status_code, 201)
        page = website.get('/notes/')
        self.assertContains(page, '&lt;script&gt;')
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertEqual(website.post('/api/notes/', data=json.dumps({'title': 'x', 'content': 'x'}), content_type='application/json').status_code, 403)
        self.assertEqual(self.post('/api/extension/notes/', {'title': '', 'content': 'x'}, headers=headers).status_code, 400)

    def test_legacy_copy_preserves_original_and_is_idempotent(self):
        old = MistakeNote.objects.create(user=self.user, contest_id=123, problem_index='A', mistake='Overflow', lesson='Use int64')
        migration = importlib.import_module('core.migrations.0003_profile_assistant')
        migration.preserve_legacy_notes(apps, type('Editor', (), {'connection': connection})())
        copied = PersonalNote.objects.get(legacy_note=old)
        self.assertIn('Use int64', copied.content)
        self.assertTrue(MistakeNote.objects.filter(pk=old.pk).exists())
        copied.content = 'My edited note'; copied.save()
        migration.preserve_legacy_notes(apps, type('Editor', (), {'connection': connection})())
        copied.refresh_from_db(); self.assertEqual(copied.content, 'My edited note')

    def test_website_profile_shares_analytics_and_preserves_graphs(self):
        self.user.codeforces_handle = 'example'; self.user.save()
        self.client.force_login(self.user)
        bundle = profile(handle='example')
        bundle['practice'] = {'problems': [], 'note': 'No eligible candidates.'}
        with patch('core.services.codeforces.get_profile', return_value=bundle), patch('core.views.call_ai_engine') as ai:
            page = self.client.get('/profile/')
            self.assertContains(page, 'Topic-wise performance')
            self.assertContains(page, 'Submission verdicts')
            self.assertContains(page, 'Generate AI Improvement Plan')
            self.assertContains(page, 'ratingHistChart')
            self.assertContains(page, 'mlChart')
            ai.assert_not_called()

    def test_website_notes_create_edit_delete_with_csrf(self):
        self.client.force_login(self.user)
        self.client.get('/notes/')
        csrf = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(self.client.post('/notes/', {'title': 'Lesson', 'content': 'First', 'topic': 'dp', 'csrfmiddlewaretoken': csrf}).status_code, 302)
        note = PersonalNote.objects.get(owner=self.user)
        self.assertContains(self.client.get(f'/notes/?edit={note.pk}'), 'Edit note')
        self.assertEqual(self.client.post('/notes/', {'note_id': note.pk, 'updated_at': note.updated_at.isoformat(), 'title': 'Updated', 'content': 'Second', 'topic': 'dp', 'csrfmiddlewaretoken': csrf}).status_code, 302)
        note.refresh_from_db(); self.assertEqual(note.content, 'Second')
        self.assertEqual(self.client.post('/notes/', {'note_id': note.pk, 'updated_at': note.updated_at.isoformat(), 'action': 'delete', 'csrfmiddlewaretoken': csrf}).status_code, 302)
        self.assertFalse(PersonalNote.objects.filter(pk=note.pk).exists())


@override_settings(AI_API_KEY='mock-only')
class ImprovementPlanTests(PlatformTestCase):
    def test_on_demand_only_cached_and_no_raw_history_sent(self):
        tokens, _, _ = self.connect(); headers = self.bearer(tokens['access_token'])
        with patch('core.services.improvement.get_profile', return_value=profile(handle='viewedB')), patch('core.views.call_ai_engine', return_value=(json.dumps(PLAN), '')) as ai:
            result = self.post('/api/extension/improvement-plan/', {'handle': 'viewedB'}, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(self.post('/api/extension/improvement-plan/', {'handle': 'viewedB'}, headers=headers).json()['cached'])
            ai.assert_called_once()
            self.assertNotIn('_attempted_keys', ai.call_args.args[0])
            self.assertEqual(AIPlanQuota.objects.get(user=self.user).attempts, 1)

    def test_backend_hourly_and_simultaneous_limits(self):
        tokens, _, _ = self.connect(); headers = self.bearer(tokens['access_token'])
        with patch('core.services.improvement.get_profile', return_value=profile()), patch('core.views.call_ai_engine', return_value=('invalid', '')) as ai:
            for _ in range(3):
                self.assertEqual(self.post('/api/extension/improvement-plan/', {'handle': 'example'}, headers=headers).status_code, 502)
            self.assertEqual(self.post('/api/extension/improvement-plan/', {'handle': 'example'}, headers=headers).status_code, 429)
            self.assertEqual(ai.call_count, 3)
            quota = AIPlanQuota.objects.get(user=self.user); quota.window_start -= timedelta(hours=2); quota.attempts = 0; quota.in_flight_until = timezone.now() + timedelta(seconds=30); quota.save()
            self.assertEqual(self.post('/api/extension/improvement-plan/', {'handle': 'example'}, headers=headers).status_code, 429)

    def test_website_plan_requires_login_csrf_and_valid_json(self):
        self.assertEqual(self.client.post('/api/improvement-plan/', data='{}', content_type='application/json').status_code, 403)
        self.assertEqual(self.post('/api/extension/improvement-plan/', {'handle': 'example'}).status_code, 401)
        self.assertIsNone(improvement.parse_plan('[]'))
        self.assertIsNone(improvement.parse_plan('{}'))
