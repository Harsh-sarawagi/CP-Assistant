import hashlib
import time
import requests
from django.core.cache import cache

from .analytics import analyze_profile, recommend_problems, valid_handle

HISTORY_LIMIT = 10000


class CodeforcesError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def get_api(method, params=None):
    try:
        response = requests.get('https://codeforces.com/api/' + method, params=params, timeout=10)
        if response.status_code == 429:
            raise CodeforcesError('Codeforces rate limit reached. Please retry later.', 429)
        if response.status_code != 200:
            raise CodeforcesError('Codeforces is unavailable or the profile could not be loaded.')
        body = response.json()
        if not isinstance(body, dict) or body.get('status') != 'OK':
            raise CodeforcesError('Codeforces could not load this profile or is temporarily rate limited.')
        return body['result']
    except (requests.RequestException, ValueError, KeyError, TypeError):
        raise CodeforcesError('Could not reach Codeforces or read its response.') from None


def problem_pool():
    pool = cache.get('profile_problem_pool_v1')
    if pool is None:
        result = get_api('problemset.problems')
        if not isinstance(result, dict) or not isinstance(result.get('problems'), list) or not all(isinstance(p, dict) for p in result['problems']):
            raise CodeforcesError('Codeforces returned invalid problem data.')
        pool = result['problems']
        cache.set('profile_problem_pool_v1', pool, 21600)
    return pool


def get_profile(handle):
    if not valid_handle(handle):
        raise CodeforcesError('Invalid Codeforces handle.', 400)
    key = 'profile_analytics_v1_' + hashlib.sha256(handle.lower().encode()).hexdigest()
    existing = cache.get(key)
    if existing is not None:
        return existing
    if not cache.add(key + '_lock', True, timeout=50):
        raise CodeforcesError('This profile is already loading. Retry shortly.', 429)
    try:
        info = get_api('user.info', {'handles': handle})
        if not isinstance(info, list) or not info or not isinstance(info[0], dict):
            raise CodeforcesError('Codeforces profile not found.', 404)
        # Space upstream calls; no automatic retries or repeated tab fetches.
        time.sleep(2)
        contests = get_api('user.rating', {'handle': handle})
        time.sleep(2)
        submissions = get_api('user.status', {'handle': handle, 'from': 1, 'count': HISTORY_LIMIT + 1})
        if not isinstance(contests, list) or not isinstance(submissions, list) or not all(isinstance(c, dict) and isinstance(c.get('newRating'), (int, float)) for c in contests) or not all(isinstance(s, dict) and isinstance(s.get('problem', {}), dict) for s in submissions):
            raise CodeforcesError('Codeforces returned invalid history.')
        metadata = {**info[0], 'handle': info[0].get('handle') or handle}
        result = analyze_profile(metadata, contests, submissions[:HISTORY_LIMIT], truncated=len(submissions) >= HISTORY_LIMIT, limit=HISTORY_LIMIT)
        try:
            if result['history']['complete']:
                time.sleep(2) if cache.get('profile_problem_pool_v1') is None else None
                result['practice'] = recommend_problems(result, problem_pool())
            else:
                result['practice'] = recommend_problems(result, [])
        except CodeforcesError as error:
            result['practice'] = {'problems': [], 'error': str(error)}
        cache.set(key, result, 30 if result['practice'].get('error') else 300)
        return result
    finally:
        cache.delete(key + '_lock')


def public_profile(profile):
    return {k: v for k, v in profile.items() if not k.startswith('_')}


def website_profile(handle):
    result = public_profile(get_profile(handle))
    series = result['rating']
    return {**result, 'handle': result['summary']['handle'], 'ml_labels': series['labels'], 'ml_actual': series['actual'], 'ml_trend': series['trend'], 'ml_future': series['estimate'],
            'current_rating': result['summary']['rating'] or 0, 'next_predicted': series['estimate'][0] if series['estimate'] else None,
            'hist_labels': [str(x['rating']) for x in result['solved_by_rating']] + (['Unrated'] if result['unrated_solved'] else []),
            'hist_data': [x['count'] for x in result['solved_by_rating']] + ([result['unrated_solved']] if result['unrated_solved'] else []),
            'pie_labels': [x['tag'] for x in result['topics']], 'pie_data': [x['solved'] for x in result['topics']], 'total_solved': result['summary']['unique_solved']}
