from types import SimpleNamespace
from unittest.mock import patch
import json

from django.test import RequestFactory, SimpleTestCase
from django.core.cache import cache

from . import views


class ExtensionProblemApiTests(SimpleTestCase):
	def setUp(self):
		self.factory = RequestFactory()

	def test_rejects_missing_or_contest_style_problem_identifier(self):
		request = self.factory.get('/api/extension/context/?url=https://codeforces.com/contest/123/problem/A')
		response = views.extension_context_api(request)

		self.assertEqual(response.status_code, 400)

	@patch('core.views.get_weak_tags', return_value=([], None))
	@patch('core.views.get_profile_analytics', return_value=({'current_rating': 1400}, None))
	@patch('core.views.get_user_submissions', return_value=([], None))
	@patch('core.views.get_user_problem_history')
	@patch('core.views.get_codeforces_problem')
	@patch('core.views.get_recommendation', return_value=(None, None))
	def test_returns_problem_and_exact_history(
		self,
		get_recommendation,
		get_problem,
		get_history,
		get_submissions,
		get_profile,
		get_weak_tags
	):
		get_problem.return_value = ({
			'name': 'Example Problem',
			'rating': 1200,
			'tags': ['math'],
			'url': 'https://codeforces.com/problemset/problem/123/A'
		}, None)
		get_history.return_value = ({
			'attempted': True,
			'solved': True,
			'attempts': 2,
			'verdict_history': ['WRONG_ANSWER', 'OK']
		}, None)
		request = self.factory.get('/api/extension/context/?contest_id=123&index=A')
		request.user = SimpleNamespace(
			is_authenticated=True,
			username='tester',
			codeforces_handle='tourist'
		)

		response = views.extension_context_api(request)
		payload = json.loads(response.content)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(payload['problem']['rating'], 1200)
		self.assertEqual(payload['problem_history']['attempts'], 2)
		self.assertIn('problem_analysis', payload)
		get_problem.assert_called_once_with('123', 'A')
		get_history.assert_called_once_with('tourist', '123', 'A')


class ProblemAnalysisTests(SimpleTestCase):
	def test_no_history_returns_zero_tag_attempts(self):
		analysis = views.build_problem_analysis(
			{'rating': 1400, 'tags': ['math', 'graphs']},
			{'current_rating': 1400},
			[]
		)

		self.assertEqual(analysis['fit']['classification'], 'good_practice')
		self.assertEqual(analysis['tag_performance']['math']['attempted'], 0)
		self.assertEqual(analysis['tag_performance']['math']['success_rate'], 0)
		self.assertEqual(analysis['tag_performance']['graphs']['failed'], 0)

	def test_solved_problem_history(self):
		submissions = [
			{'problem': {'contestId': 123, 'index': 'A'}, 'verdict': 'WRONG_ANSWER'},
			{'problem': {'contestId': 123, 'index': 'A'}, 'verdict': 'OK'}
		]

		with patch('core.views.get_user_submissions', return_value=(submissions, None)):
			history, error = views.get_user_problem_history('tourist', '123', 'A')

		self.assertIsNone(error)
		self.assertEqual(history['attempts'], 2)
		self.assertTrue(history['solved'])
		self.assertEqual(history['verdict_history'], ['WRONG_ANSWER', 'OK'])

	def test_failed_attempts_are_counted_as_failed(self):
		submissions = [
			{'problem': {'tags': ['math']}, 'verdict': 'WRONG_ANSWER'},
			{'problem': {'tags': ['math']}, 'verdict': 'TIME_LIMIT_EXCEEDED'},
		]
		analysis = views.build_problem_analysis(
			{'rating': 1400, 'tags': ['math']},
			{'current_rating': 1400},
			submissions
		)

		self.assertEqual(analysis['tag_performance']['math']['failed'], 2)
		self.assertEqual(analysis['tag_performance']['math']['success_rate'], 0)
		self.assertIn('math', analysis['fit']['explanation'])

	def test_multiple_tags_have_independent_performance(self):
		submissions = [
			{'problem': {'tags': ['math', 'dp']}, 'verdict': 'OK'},
			{'problem': {'tags': ['math']}, 'verdict': 'WRONG_ANSWER'},
			{'problem': {'tags': ['dp']}, 'verdict': 'OK'},
		]
		analysis = views.build_problem_analysis(
			{'rating': 1400, 'tags': ['math', 'dp', 'graphs']},
			{'current_rating': 1400},
			submissions
		)

		self.assertEqual(analysis['tag_performance']['math']['success_rate'], 50.0)
		self.assertEqual(analysis['tag_performance']['dp']['success_rate'], 100.0)
		self.assertEqual(analysis['tag_performance']['graphs']['attempted'], 0)

	def test_rating_situations_are_classified_deterministically(self):
		self.assertEqual(views.get_problem_fit(1000, 1400, [])[0], 'too_easy')
		self.assertEqual(views.get_problem_fit(1500, 1400, [])[0], 'good_practice')
		self.assertEqual(views.get_problem_fit(1600, 1400, [])[0], 'stretch')
		self.assertEqual(views.get_problem_fit(1800, 1400, [])[0], 'too_hard')


class RecommendationTests(SimpleTestCase):
	def setUp(self):
		cache.clear()
		self.current_problem = {
			'name': 'Current',
			'rating': 1400,
			'tags': ['dp', 'graphs'],
			'url': 'https://codeforces.com/problemset/problem/1/A'
		}
		self.analysis = {
			'tag_performance': {
				'dp': {'attempted': 4, 'solved': 1, 'failed': 3, 'success_rate': 25.0},
				'graphs': {'attempted': 2, 'solved': 2, 'failed': 0, 'success_rate': 100.0}
			}
		}

	def test_excludes_current_attempted_and_solved_problems(self):
		pool = [
			{'contest_id': 1, 'index': 'A', 'name': 'Current', 'rating': 1400, 'tags': ['dp'], 'url': 'current'},
			{'contest_id': 2, 'index': 'A', 'name': 'Attempted', 'rating': 1400, 'tags': ['dp'], 'url': 'attempted'},
			{'contest_id': 3, 'index': 'A', 'name': 'Fresh', 'rating': 1400, 'tags': ['dp'], 'url': 'fresh'}
		]
		submissions = [
			{'problem': {'contestId': 2, 'index': 'A'}, 'verdict': 'WRONG_ANSWER'},
			{'problem': {'contestId': 4, 'index': 'A'}, 'verdict': 'OK'}
		]
		with patch('core.views.get_codeforces_problem_pool', return_value=(pool, None)):
			candidates, error = views.rank_recommendation_candidates(
				self.current_problem, '1', 'A', self.analysis, submissions, 1400
			)

		self.assertIsNone(error)
		self.assertEqual([(item['contest_id'], item['index']) for item in candidates], [(3, 'A')])

	def test_tag_overlap_affects_deterministic_ranking(self):
		pool = [
			{'contest_id': 2, 'index': 'A', 'name': 'No overlap', 'rating': 1400, 'tags': ['math'], 'url': 'no'},
			{'contest_id': 3, 'index': 'A', 'name': 'Tag overlap', 'rating': 1400, 'tags': ['graphs'], 'url': 'yes'}
		]
		with patch('core.views.get_codeforces_problem_pool', return_value=(pool, None)):
			candidates, _ = views.rank_recommendation_candidates(
				self.current_problem, '1', 'A', self.analysis, [], 1400
			)

		self.assertEqual(candidates[0]['name'], 'Tag overlap')

	def test_weak_tag_overlap_affects_ranking(self):
		pool = [
			{'contest_id': 2, 'index': 'A', 'name': 'Strong tag', 'rating': 1400, 'tags': ['graphs'], 'url': 'strong'},
			{'contest_id': 3, 'index': 'A', 'name': 'Weak tag', 'rating': 1400, 'tags': ['dp'], 'url': 'weak'}
		]
		with patch('core.views.get_codeforces_problem_pool', return_value=(pool, None)):
			candidates, _ = views.rank_recommendation_candidates(
				self.current_problem, '1', 'A', self.analysis, [], 1400
			)

		self.assertEqual(candidates[0]['name'], 'Weak tag')

	def test_rating_proximity_affects_ranking(self):
		pool = [
			{'contest_id': 2, 'index': 'A', 'name': 'Far', 'rating': 1800, 'tags': ['math'], 'url': 'far'},
			{'contest_id': 3, 'index': 'A', 'name': 'Close', 'rating': 1450, 'tags': ['math'], 'url': 'close'}
		]
		with patch('core.views.get_codeforces_problem_pool', return_value=(pool, None)):
			candidates, _ = views.rank_recommendation_candidates(
				self.current_problem, '1', 'A', {'tag_performance': {}}, [], 1400
			)

		self.assertEqual(candidates[0]['name'], 'Close')

	@patch('core.views.call_ai_engine', return_value=(
		'{"contest_id": 999, "index": "Z", "reason": "invented"}', ''
	))
	@patch('core.views.rank_recommendation_candidates')
	def test_invalid_groq_selection_falls_back_to_top_candidate(self, rank_candidates, call_ai):
		candidate = {
			'contest_id': 2, 'index': 'A', 'name': 'Top', 'rating': 1400,
			'tags': ['dp'], 'url': 'top'
		}
		rank_candidates.return_value = ([candidate], None)

		recommendation, error = views.get_recommendation(
			self.current_problem, '1', 'A', self.analysis, [], 1400, 'fallback-user'
		)

		self.assertIsNone(error)
		self.assertEqual(recommendation['problem'], candidate)
		self.assertIn('deterministic', recommendation['reason'])
		call_ai.assert_called_once()

	@patch('core.views.call_ai_engine', return_value=(
		'{"contest_id": 2, "index": "A", "reason": "Use this next."}', ''
	))
	@patch('core.views.rank_recommendation_candidates')
	def test_groq_selection_is_restricted_to_supplied_candidates(self, rank_candidates, call_ai):
		candidate = {
			'contest_id': 2, 'index': 'A', 'name': 'Allowed', 'rating': 1400,
			'tags': ['dp'], 'url': 'allowed'
		}
		rank_candidates.return_value = ([candidate], None)

		recommendation, _ = views.get_recommendation(
			self.current_problem, '1', 'A', self.analysis, [], 1400, 'restricted-user'
		)

		self.assertEqual(recommendation['problem']['contest_id'], 2)
		self.assertEqual(recommendation['reason'], 'Use this next.')

	@patch('core.views.call_ai_engine')
	@patch('core.views.rank_recommendation_candidates', return_value=([], None))
	def test_no_candidates_returns_none_without_groq(self, rank_candidates, call_ai):
		recommendation, error = views.get_recommendation(
			self.current_problem, '1', 'A', self.analysis, [], 1400, 'empty-user'
		)

		self.assertIsNone(error)
		self.assertIsNone(recommendation)
		call_ai.assert_not_called()

	@patch('core.views.call_ai_engine', return_value=(
		'{"contest_id": 2, "index": "A", "reason": "Cached choice."}', ''
	))
	@patch('core.views.rank_recommendation_candidates')
	def test_recommendation_cache_prevents_repeated_groq_calls(self, rank_candidates, call_ai):
		candidate = {
			'contest_id': 2, 'index': 'A', 'name': 'Cached', 'rating': 1400,
			'tags': ['dp'], 'url': 'cached'
		}
		rank_candidates.return_value = ([candidate], None)

		first, _ = views.get_recommendation(
			self.current_problem, '1', 'A', self.analysis, [], 1400, 'cached-user'
		)
		second, _ = views.get_recommendation(
			self.current_problem, '1', 'A', self.analysis, [], 1400, 'cached-user'
		)

		self.assertEqual(first, second)
		call_ai.assert_called_once()

# Create your tests here.
