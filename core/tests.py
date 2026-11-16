"""Pure/stateless analytics tests; no database or live API calls."""
from unittest.mock import Mock, patch
import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from .services.analytics import analyze_profile, recommend_problems, rating_series, valid_handle
from .services.codeforces import get_profile, get_api, CodeforcesError, public_profile
from .services.safe_markdown import safe_markdown


def sub(contest=1, index='A', verdict='OK', tags=None, rating=1000, **extra):
    problem = {'contestId': contest, 'index': index, 'name': 'Same name', 'tags': tags or ['math']}
    if rating is not None:
        problem['rating'] = rating
    return {'problem': problem, 'verdict': verdict, **extra}


def profile(rows=None, rating=1200, handle='example'):
    return analyze_profile({'handle': handle, 'rating': rating, 'maxRating': rating, 'rank': 'pupil'}, [], rows or [])


class ProfileAnalyticsTests(SimpleTestCase):
    def test_empty_unrated_history(self):
        p = profile(rating=None)
        self.assertIsNone(p['summary']['rating'])
        self.assertEqual(p['summary']['unique_solved'], 0)
        self.assertIsNone(p['summary']['acceptance_rate'])
        self.assertEqual(p['rating']['estimate'], [])
        self.assertFalse(any(t['evidence_sufficient'] for t in p['focus_topics']))

    def test_short_and_normal_regression_history(self):
        for ratings in [[], [1000], [1000, 1100], [1000, 1100, 1200]]:
            series = rating_series([{'newRating': n} for n in ratings])
            self.assertEqual(series['actual'], ratings)
            self.assertEqual(series['estimate'], [1300, 1400] if len(ratings) == 3 else [])

    def test_stable_ids_not_names_and_multiple_acceptances(self):
        p = profile([sub(1), sub(1), sub(2)])
        self.assertEqual(p['summary']['unique_solved'], 2)
        self.assertEqual(p['summary']['total_submissions'], 3)
        self.assertEqual(p['solved_by_rating'], [{'rating': 1000, 'count': 2}])

    def test_multiple_tags_unrated_and_numeric_buckets(self):
        p = profile([sub(1, tags=['math', 'dp'], rating=1200), sub(2, rating=None), sub(3, rating=800)])
        self.assertEqual([r['rating'] for r in p['solved_by_rating']], [800, 1200])
        self.assertEqual(p['unrated_solved'], 1)
        self.assertEqual(sum(t['solved'] for t in p['topics']), 4)

    def test_pending_not_failure_and_distinct_topic_solve_rate(self):
        p = profile([sub(1, verdict=None), sub(2, verdict='TESTING'), sub(3, verdict='WRONG_ANSWER'), sub(3)])
        self.assertEqual(p['summary']['pending_submissions'], 2)
        self.assertEqual(p['summary']['acceptance_rate'], 50)
        topic = p['topics'][0]
        self.assertEqual(topic['attempted'], 1)
        self.assertEqual(topic['solved'], 1)
        self.assertEqual(topic['failed_submissions'], 1)
        self.assertEqual(topic['solve_rate'], 100)

    def test_low_sample_is_not_classified_weak(self):
        p = profile([sub(1, verdict='WRONG_ANSWER')] * 20 + [sub(2, verdict='RUNTIME_ERROR')])
        self.assertEqual(p['weak_topics'], [])
        self.assertFalse(p['topics'][0]['evidence_sufficient'])

    def test_retries_weakness_signals_and_no_inferred_bug(self):
        rows = [sub(i, verdict='WRONG_ANSWER', tags=['dp']) for i in range(1, 7) for _ in range(3)]
        rows += [sub(1, tags=['dp'])]
        p = profile(rows)
        topic = p['weak_topics'][0]
        self.assertEqual(topic['attempted'], 6)
        self.assertEqual(topic['solved'], 1)
        self.assertEqual(topic['average_attempts_per_solved'], 4)
        self.assertEqual(topic['repeated_unsuccessful'], 5)
        self.assertTrue(topic['evidence_sufficient'])
        self.assertTrue(p['patterns'])
        self.assertNotIn('off-by-one', ' '.join(p['patterns']))

    def test_verdict_categories_include_compile_memory_and_other(self):
        codes = ['OK', 'WRONG_ANSWER', 'TIME_LIMIT_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'RUNTIME_ERROR', 'COMPILATION_ERROR', 'SKIPPED']
        p = profile([sub(i, verdict=v) for i, v in enumerate(codes)])
        self.assertEqual({r['verdict'] for r in p['verdicts']}, set(codes))

    def test_incomplete_and_missing_ids_are_visible(self):
        p = analyze_profile({'handle': 'example'}, [], [sub(), {'verdict': 'OK', 'problem': {'name': 'unknown'}}], truncated=True)
        self.assertFalse(p['history']['complete'])
        self.assertTrue(p['history']['truncated'])
        self.assertEqual(p['history']['missing_problem_ids'], 1)
        self.assertEqual(p['summary']['unique_solved'], 1)
        self.assertNotIn('_solved_keys', public_profile(p))

    def test_handle_validation(self):
        for value in ['tourist', 'a-b.c_1']:
            self.assertTrue(valid_handle(value))
        for value in ['../secret', '', 'a' * 25, 'a&handles=b', None]:
            self.assertFalse(valid_handle(value))

    def test_strong_topics_are_not_mislabeled_insufficient(self):
        rows = [sub(i) for i in range(6)] + [sub(1), sub(2)]
        p = profile(rows)
        self.assertTrue(p['strong_topics'])
        self.assertTrue(p['focus_topics'][0]['evidence_sufficient'])
        self.assertIn('Consolidate', p['focus_topics'][0]['reason'])

    def test_review_url_validation_rejects_off_domain_and_preserves_cf_routes(self):
        from .services.urls import problem_url
        self.assertIsNone(problem_url('http://127.0.0.1/?codeforces.com'))
        self.assertIsNone(problem_url('https://codeforces.com.evil.invalid/problemset/problem/1/A'))
        self.assertIsNone(problem_url('https://codeforces.com@evil.invalid/problemset/problem/1/A'))
        self.assertEqual(problem_url('https://codeforces.com/contest/1/problem/A/'), 'https://codeforces.com/contest/1/problem/A')

    def test_html_sanitizer_preserves_safe_formatting(self):
        text = safe_markdown('**Good** <img src=x onerror=alert(1)> [bad](javascript:alert) <script>alert(1)</script>')
        self.assertIn('<strong>Good</strong>', text)
        self.assertNotIn('<img', text)
        self.assertNotIn('<script', text)
        self.assertNotIn('href="javascript:', text)


class PracticeTests(SimpleTestCase):
    def pool(self):
        return [{'contestId': i, 'index': 'A', 'name': 'Example', 'rating': rating, 'tags': [tag]} for i, rating, tag in [(1, 1200, 'dp'), (2, 1200, 'math'), (3, 1200, 'dp'), (4, 2500, 'dp'), (5, 800, 'dp')]]

    def test_solved_exclusion_unseen_preference_and_hard_boundaries(self):
        p = profile([sub(1), sub(2, verdict='WRONG_ANSWER')])
        result = recommend_problems(p, self.pool())
        ids = [x['contest_id'] for x in result['problems']]
        self.assertNotIn(1, ids)
        self.assertNotIn(4, ids)
        self.assertNotIn(5, ids)
        self.assertEqual(ids, [3, 2])
        self.assertTrue(all(x['url'].startswith('https://codeforces.com/problemset/problem/') for x in result['problems']))

    def test_weak_topic_priority(self):
        p = profile([sub(i, verdict='WRONG_ANSWER', tags=['dp']) for i in range(10, 16) for _ in range(2)])
        result = recommend_problems(p, self.pool())
        self.assertEqual(result['problems'][0]['tags'], ['dp'])

    def test_unrated_fallback_and_malformed_urls(self):
        result = recommend_problems(profile(rating=None), self.pool() + [{'contestId': 'bad/url', 'index': 'A', 'rating': 900, 'tags': []}])
        self.assertTrue(result['fallback'])
        self.assertTrue(all(800 <= x['rating'] <= 1000 for x in result['problems']))

    def test_incomplete_history_withholds_unverifiable_recommendations(self):
        p = profile(); p['history']['complete'] = False
        result = recommend_problems(p, self.pool())
        self.assertEqual(result['problems'], [])
        self.assertTrue(result['blocked_incomplete'])


class CodeforcesServiceTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_cached_bundle_fetches_history_once_and_never_ai(self):
        responses = [[{'handle': 'example', 'rating': 1200}], [], [sub()], {'problems': []}]
        with patch('core.services.codeforces.get_api', side_effect=responses) as api, patch('core.services.codeforces.time.sleep'), patch('core.views.call_ai_engine') as ai:
            first = get_profile('example')
            self.assertEqual(get_profile('EXAMPLE'), first)
            self.assertEqual(api.call_count, 4)
            self.assertEqual(sum(call.args[0] == 'user.status' for call in api.call_args_list), 1)
            ai.assert_not_called()

    def test_truncated_history_flag(self):
        with patch('core.services.codeforces.HISTORY_LIMIT', 2), patch('core.services.codeforces.get_api', side_effect=[[{'handle': 'example'}], [], [sub(1), sub(2), sub(3)], {'problems': []}]), patch('core.services.codeforces.time.sleep'):
            self.assertTrue(get_profile('example')['history']['truncated'])

    def test_network_rate_limit_bad_json_and_failed_api(self):
        for response in [Mock(status_code=429), Mock(status_code=502), Mock(status_code=200, json=lambda: {'status': 'FAILED'}), Mock(status_code=200, json=Mock(side_effect=ValueError()))]:
            with patch('core.services.codeforces.requests.get', return_value=response), self.assertRaises(CodeforcesError):
                get_api('user.info')
        with patch('core.services.codeforces.requests.get', side_effect=requests.Timeout()), self.assertRaises(CodeforcesError):
            get_api('user.info')
