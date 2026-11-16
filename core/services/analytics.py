"""Deterministic analytics shared by the website and profile extension."""
from collections import Counter, defaultdict
from statistics import median
import re

import numpy as np
from sklearn.linear_model import LinearRegression

HANDLE = re.compile(r'^[A-Za-z0-9_.-]{1,24}$')
PENDING = {None, '', 'TESTING', 'PENDING', 'QUEUED', 'RUNNING'}
MIN_PROBLEMS, MIN_SUBMISSIONS = 5, 8


def valid_handle(handle):
    return isinstance(handle, str) and handle not in {'.', '..'} and HANDLE.fullmatch(handle) is not None


def problem_key(problem):
    index = str(problem.get('index') or '').upper()
    if not index:
        return None
    if problem.get('contestId') is not None:
        return f"{problem['contestId']}:{index}"
    if problem.get('problemsetName'):
        return f"set:{problem['problemsetName']}:{index}"
    return None


def rating_series(contests):
    actual = [int(c['newRating']) for c in contests if isinstance(c.get('newRating'), (int, float))]
    labels = [f'C{i + 1}' for i in range(len(actual))]
    trend, future = [], []
    if len(actual) >= 3:
        x = np.arange(1, len(actual) + 1).reshape(-1, 1)
        y = np.array(actual)
        trend = LinearRegression().fit(x, y).predict(x).astype(int).tolist()
        recent = min(len(actual), 15)
        future = LinearRegression().fit(x[-recent:], y[-recent:]).predict(np.array([len(actual) + 1, len(actual) + 2]).reshape(-1, 1)).astype(int).tolist()
    return {'labels': labels + (['E1', 'E2'] if future else []), 'actual': actual, 'trend': trend,
            'estimate': future, 'recent_change': actual[-1] - actual[max(0, len(actual) - 6)] if actual else 0,
            'recent_contests': min(5, max(0, len(actual) - 1))}


def analyze_profile(info, contests, submissions, *, truncated=False, limit=10000):
    grouped, verdicts = {}, Counter()
    missing_ids, pending, accepted = 0, 0, 0
    for sub in submissions:
        verdict = sub.get('verdict')
        if verdict in PENDING:
            pending += 1
        else:
            verdicts[verdict] += 1
            accepted += verdict == 'OK'
        problem = sub.get('problem') or {}
        key = problem_key(problem)
        if key is None:
            missing_ids += 1
            continue
        item = grouped.setdefault(key, {'problem': problem, 'final': [], 'solved': False})
        # Metadata may differ between repeated submissions; prefer richer/latest metadata.
        if len(problem) > len(item['problem']):
            item['problem'] = problem
        if verdict not in PENDING:
            item['final'].append(verdict)
            item['solved'] |= verdict == 'OK'
    solved = [p for p in grouped.values() if p['solved']]
    rating_counts = Counter(p['problem']['rating'] for p in solved if isinstance(p['problem'].get('rating'), int))
    unrated = sum(not isinstance(p['problem'].get('rating'), int) for p in solved)
    topics = defaultdict(lambda: {'attempted': 0, 'solved': 0, 'submissions': 0, 'failed_submissions': 0, 'repeated_unsuccessful': 0, 'solved_attempts': 0, 'ratings': []})
    bands = defaultdict(lambda: {'attempted': 0, 'solved': 0})
    for item in grouped.values():
        final, problem = item['final'], item['problem']
        if not final:
            continue
        rating = problem.get('rating')
        if isinstance(rating, int):
            band = bands[(rating // 400) * 400]
            band['attempted'] += 1
            band['solved'] += int(item['solved'])
        for tag in set(problem.get('tags') or []):
            t = topics[tag]
            t['attempted'] += 1
            t['solved'] += int(item['solved'])
            t['submissions'] += len(final)
            t['failed_submissions'] += sum(v != 'OK' for v in final)
            t['repeated_unsuccessful'] += int(not item['solved'] and len(final) >= 3)
            if item['solved']:
                t['solved_attempts'] += len(final)
            if isinstance(rating, int):
                t['ratings'].append(rating)
    topic_rows = []
    for tag, t in topics.items():
        rate = t['solved'] / t['attempted']
        enough = t['attempted'] >= MIN_PROBLEMS and t['submissions'] >= MIN_SUBMISSIONS
        score = round(100 * (.65 * (1 - rate) + .20 * t['failed_submissions'] / t['submissions'] + .15 * min(1, 3 * t['repeated_unsuccessful'] / t['attempted'])), 1) if enough else None
        topic_rows.append({'tag': tag, **{k: t[k] for k in ['attempted', 'solved', 'submissions', 'failed_submissions', 'repeated_unsuccessful']},
                           'solve_rate': round(rate * 100, 1), 'average_attempts_per_solved': round(t['solved_attempts'] / t['solved'], 2) if t['solved'] else None,
                           'typical_rating': int(median(t['ratings'])) if t['ratings'] else None, 'evidence_sufficient': enough, 'weakness_score': score,
                           'evidence': f"{t['solved']}/{t['attempted']} distinct judged problems solved; {t['failed_submissions']} unsuccessful submissions; {t['repeated_unsuccessful']} unsolved problems with 3+ attempts."})
    topic_rows.sort(key=lambda row: (-row['attempted'], row['tag']))
    eligible = [t for t in topic_rows if t['evidence_sufficient']]
    weak = sorted([t for t in eligible if t['weakness_score'] >= 25], key=lambda t: (-t['weakness_score'], t['tag']))[:5]
    strong = sorted([t for t in eligible if t['solve_rate'] >= 70], key=lambda t: (-t['solve_rate'], -t['solved'], t['tag']))[:5]
    base = info.get('rating') or (contests[-1].get('newRating') if contests else None)
    base = int(base) if isinstance(base, (int, float)) else None
    low, high = difficulty_range(base, topic_rows)
    focus = [{'tag': t['tag'], 'reason': t['evidence'], 'difficulty_min': low, 'difficulty_max': high, 'evidence_sufficient': True} for t in weak]
    selected_tags = {t['tag'] for t in focus}
    for t in topic_rows:
        if len(focus) >= 3:
            break
        if t['tag'] not in selected_tags:
            focus.append({'tag': t['tag'], 'reason': ('Consolidate an established topic; current results do not flag a weakness. ' + t['evidence']) if t['evidence_sufficient'] else 'Build more distinct-problem evidence; this is not a weak-topic classification.', 'difficulty_min': low, 'difficulty_max': high, 'evidence_sufficient': t['evidence_sufficient']})
            selected_tags.add(t['tag'])
    for tag in ['implementation', 'math', 'greedy', 'sortings', 'binary search']:
        if len(focus) >= 3:
            break
        if tag not in selected_tags:
            focus.append({'tag': tag, 'reason': 'Suggested foundation/breadth practice; not a measured weakness classification.', 'difficulty_min': low, 'difficulty_max': high, 'evidence_sufficient': False})
            selected_tags.add(tag)
    judged = sum(verdicts.values())
    patterns = []
    repeated_wa = sum(item['final'].count('WRONG_ANSWER') >= 3 for item in grouped.values())
    many_attempts = sum(len(item['final']) >= 5 for item in grouped.values())
    if repeated_wa:
        patterns.append(f'{repeated_wa} problem(s) had at least three Wrong Answer submissions. Verdicts alone do not identify the coding cause.')
    if many_attempts:
        patterns.append(f'{many_attempts} problem(s) needed five or more judged submissions.')
    for code, label in [('TIME_LIMIT_EXCEEDED', 'Time Limit Exceeded'), ('RUNTIME_ERROR', 'Runtime Error')]:
        if verdicts[code] >= 3 and judged and verdicts[code] / judged >= .15:
            patterns.append(f'{verdicts[code]} {label} verdicts ({verdicts[code] / judged:.0%} of judged submissions). Review these submissions; no root cause is inferred.')
    difficulties = [{'min': band, 'max': band + 399, **values, 'solve_rate': round(100 * values['solved'] / values['attempted'], 1)} for band, values in sorted(bands.items())]
    for band in difficulties:
        if band['attempted'] >= 5 and band['solve_rate'] < 50:
            patterns.append(f"In rating range {band['min']}–{band['max']}, {band['solved']}/{band['attempted']} distinct judged problems were solved.")
    series = rating_series(contests)
    summary = {'handle': info.get('handle', ''), 'rating': base, 'max_rating': info.get('maxRating') or (max(series['actual']) if series['actual'] else None),
               'rank': info.get('rank') or 'unrated', 'max_rank': info.get('maxRank') or 'unrated', 'rated_contests': len(contests), 'unique_solved': len(solved),
               'total_submissions': len(submissions), 'judged_submissions': judged, 'pending_submissions': pending,
               'acceptance_rate': round(100 * accepted / judged, 1) if judged else None}
    return {'summary': summary, 'history': {'complete': not truncated and missing_ids == 0, 'truncated': truncated, 'limit': limit, 'observed': len(submissions), 'missing_problem_ids': missing_ids,
            'note': 'History is capped; statistics describe the observed subset.' if truncated else 'Submissions without stable problem IDs are excluded from distinct-problem statistics.' if missing_ids else 'Complete returned history. Pending submissions are excluded from verdict percentages and topic solve rates.'},
            'solved_by_rating': [{'rating': rating, 'count': count} for rating, count in sorted(rating_counts.items())], 'unrated_solved': unrated,
            'topics': topic_rows, 'strong_topics': strong, 'weak_topics': weak, 'focus_topics': focus, 'verdicts': [{'verdict': code, 'count': count, 'percentage': round(100 * count / judged, 1)} for code, count in sorted(verdicts.items())],
            'patterns': patterns, 'difficulty_performance': difficulties, 'rating': series,
            'methodology': {'minimum_distinct_problems': MIN_PROBLEMS, 'minimum_judged_submissions': MIN_SUBMISSIONS, 'weakness_score': '65% unsolved-problem rate + 20% unsuccessful-submission rate + 15% repeated-unsuccessful-problem signal. Minimum 5 distinct problems and 8 judged submissions.'},
            # Kept server-side in service cache, stripped before public response.
            '_attempted_keys': list(grouped), '_solved_keys': [k for k, item in grouped.items() if item['solved']]}


def difficulty_range(rating, topics):
    if rating:
        return max(800, rating - 200), max(1000, rating + 200)
    known = [t['typical_rating'] for t in topics if t.get('typical_rating')]
    base = int(median(known)) if known else 900
    return max(800, min(base - 100, 1200)), max(1000, min(base + 100, 1400))


def recommend_problems(analytics, pool, count=8):
    if not analytics['history']['complete']:
        return {'problems': [], 'blocked_incomplete': True,
                'note': 'Recommendations are withheld because the observed history is incomplete. Older or unidentifiable solved problems cannot be safely excluded.'}
    low, high = difficulty_range(analytics['summary']['rating'], analytics['topics'])
    base = analytics['summary']['rating'] or (low + high) // 2
    solved, attempted = set(analytics['_solved_keys']), set(analytics['_attempted_keys'])
    weak_tags = {item['tag'] for item in analytics['weak_topics']}
    priorities = {item['tag']: len(analytics['focus_topics']) - i + (5 if item['tag'] in weak_tags else 0) for i, item in enumerate(analytics['focus_topics'])}
    ranked = []
    for p in pool:
        key = problem_key(p)
        rating, contest, index = p.get('rating'), p.get('contestId'), str(p.get('index', '')).upper()
        if not key or key in solved or not isinstance(rating, int) or not low <= rating <= high:
            continue
        if not str(contest).isdigit() or not re.fullmatch(r'[A-Z][A-Z0-9]*', index):
            continue
        tags = [tag for tag in (p.get('tags') or []) if isinstance(tag, str)]
        overlap = sum(priorities.get(tag, 0) for tag in tags)
        score = overlap * 1000 - abs(rating - base) - (5000 if key in attempted else 0)
        ranked.append((score, key, {**p, 'tags': tags}))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected, tag_counts, seen = [], Counter(), set()
    # First pass adds topic variety; second fills remaining slots. Attempted unsolved
    # problems are considered only after every unseen candidate.
    for revisits in [False, True]:
        for diverse in [True, False]:
            for _, key, p in ranked:
                if key in seen or (key in attempted) != revisits or len(selected) >= count:
                    continue
                tags = p.get('tags') or []
                focus = next((t for t in tags if t in priorities), None)
                if diverse and focus and tag_counts[focus] >= 2:
                    continue
                seen.add(key)
                if focus:
                    tag_counts[focus] += 1
                selected.append({'contest_id': int(p['contestId']), 'index': str(p['index']).upper(), 'name': p.get('name') or key, 'rating': p['rating'], 'tags': tags,
                                 'url': f"https://codeforces.com/problemset/problem/{p['contestId']}/{str(p['index']).upper()}", 'previously_attempted': key in attempted,
                                 'reason': f"{'Revisit an unsolved problem' if key in attempted else 'Unseen practice'}; {'targets ' + focus if focus else 'within your practice range'}; rating {p['rating']} in {low}–{high}."})
    return {'problems': selected, 'difficulty_min': low, 'difficulty_max': high, 'fallback': not bool(analytics['summary']['rating']),
            'note': 'Unrated fallback uses observed typical difficulty, capped at 800–1400; empty histories use 800–1000.' if not analytics['summary']['rating'] else 'Hard rating bounds are current rating ±200, with an 800 minimum. Unseen problems are preferred.'}
