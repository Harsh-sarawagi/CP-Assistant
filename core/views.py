# filepath: core/views.py
import requests
import time
import re
import json
import numpy as np
import markdown
from datetime import datetime, timezone
from sklearn.linear_model import LinearRegression
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_GET
from .forms import CustomRegistrationForm, ProfileUpdateForm, CodeReviewForm
from bs4 import BeautifulSoup
from django.core.cache import cache

CODEFORCES_PROBLEM_ID_PATTERN = re.compile(r'^[0-9]+$')
CODEFORCES_PROBLEM_INDEX_PATTERN = re.compile(r'^[A-Za-z][A-Za-z0-9]*$')


def validate_problem_identifier(contest_id, problem_index):
    if not contest_id or not problem_index:
        return False
    return (
        CODEFORCES_PROBLEM_ID_PATTERN.fullmatch(str(contest_id)) is not None
        and CODEFORCES_PROBLEM_INDEX_PATTERN.fullmatch(str(problem_index)) is not None
    )


def get_codeforces_problem(contest_id, problem_index):
    if not validate_problem_identifier(contest_id, problem_index):
        return None, "Invalid Codeforces problem identifier."

    cache_key = f"cf_problem_{contest_id}_{problem_index.upper()}"
    cached_problem = cache.get(cache_key)
    if cached_problem:
        return cached_problem, None

    try:
        response = requests.get(
            "https://codeforces.com/api/problemset.problems",
            timeout=8
        ).json()
        if response.get('status') != 'OK':
            return None, "Could not fetch Codeforces problem data."

        normalized_index = problem_index.upper()
        problem = next(
            (
                item for item in response.get('result', {}).get('problems', [])
                if str(item.get('contestId')) == str(contest_id)
                and str(item.get('index', '')).upper() == normalized_index
            ),
            None
        )
        if not problem:
            return None, "Codeforces problem not found."

        structured_problem = {
            'name': problem.get('name', ''),
            'rating': problem.get('rating'),
            'tags': problem.get('tags', []),
            'url': f"https://codeforces.com/problemset/problem/{contest_id}/{problem.get('index')}"
        }
        cache.set(cache_key, structured_problem, timeout=86400)
        return structured_problem, None
    except (requests.RequestException, ValueError):
        return None, "Could not fetch Codeforces problem data."


def get_codeforces_problem_pool():
    cache_key = 'cf_problem_pool'
    cached_pool = cache.get(cache_key)
    if cached_pool is not None:
        return cached_pool, None

    try:
        response = requests.get(
            "https://codeforces.com/api/problemset.problems",
            timeout=8
        ).json()
        if response.get('status') != 'OK':
            return [], "Could not fetch Codeforces problem data."

        problem_pool = []
        seen = set()
        for problem in response.get('result', {}).get('problems', []):
            contest_id = problem.get('contestId')
            problem_index = problem.get('index')
            name = problem.get('name')
            rating = problem.get('rating')
            tags = problem.get('tags')
            if not contest_id or not problem_index or not name or not isinstance(rating, int) or not isinstance(tags, list):
                continue

            problem_key = (str(contest_id), str(problem_index).upper())
            if problem_key in seen:
                continue
            seen.add(problem_key)
            problem_pool.append({
                'contest_id': contest_id,
                'index': problem_index,
                'name': name,
                'rating': rating,
                'tags': tags,
                'url': f"https://codeforces.com/problemset/problem/{contest_id}/{problem_index}"
            })

        cache.set(cache_key, problem_pool, timeout=21600)
        return problem_pool, None
    except (requests.RequestException, ValueError):
        return [], "Could not fetch Codeforces problem data."


def get_user_problem_history(handle, contest_id, problem_index):
    if not handle:
        return {
            'attempted': False,
            'solved': False,
            'attempts': 0,
            'verdict_history': []
        }, None

    if not validate_problem_identifier(contest_id, problem_index):
        return None, "Invalid Codeforces problem identifier."

    cache_key = f"cf_history_{handle}_{contest_id}_{problem_index.upper()}"
    cached_history = cache.get(cache_key)
    if cached_history:
        return cached_history, None

    submissions, submissions_error = get_user_submissions(handle)
    if submissions_error:
        return None, submissions_error

    try:
        normalized_index = problem_index.upper()
        matching_submissions = [
            submission for submission in submissions
            if str(submission.get('problem', {}).get('contestId')) == str(contest_id)
            and str(submission.get('problem', {}).get('index', '')).upper() == normalized_index
        ]
        matching_submissions.sort(key=lambda submission: submission.get('creationTimeSeconds', 0))
        history = {
            'attempted': bool(matching_submissions),
            'solved': any(submission.get('verdict') == 'OK' for submission in matching_submissions),
            'attempts': len(matching_submissions),
            'verdict_history': [submission.get('verdict') for submission in matching_submissions]
        }
        cache.set(cache_key, history, timeout=300)
        return history, None
    except (requests.RequestException, ValueError):
        return None, "Could not fetch Codeforces submission history."


def get_user_submissions(handle):
    if not handle:
        return [], None

    cache_key = f"cf_submissions_{handle}"
    cached_submissions = cache.get(cache_key)
    if cached_submissions is not None:
        return cached_submissions, None

    try:
        response = requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}",
            timeout=8
        ).json()
        if response.get('status') != 'OK':
            return [], "Could not fetch Codeforces submission history."

        submissions = response.get('result', [])
        cache.set(cache_key, submissions, timeout=300)
        return submissions, None
    except (requests.RequestException, ValueError):
        return [], "Could not fetch Codeforces submission history."

def scrape_codeforces_data(url):
    """
    Fetches the problem statement AND attempts to fetch the official contest tutorial.
    Returns a dictionary: {'problem': text, 'tutorial': text}
    """
    if "codeforces.com" not in url:
        return {"problem": "Not a Codeforces URL.", "tutorial": ""}
        
    cache_key = f"cf_data_{url}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    rate_limit_key = "cf_global_scrape_count"
    current_requests = cache.get(rate_limit_key, 0)
    
    if current_requests >= 15:
        return {"problem": "High traffic volume. Blind review active.", "tutorial": ""}

    # Increment request counter (we might make 2 requests, so add 2)
    cache.set(rate_limit_key, current_requests + 2, timeout=60)
        
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    scraped_data = {"problem": "Could not fetch problem.", "tutorial": "Tutorial not available."}
    
    try:
        # Step 1: Fetch the Problem Page
        response = requests.get(url, headers=headers, timeout=8)
        if response.status_code != 200:
            return scraped_data
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Get Problem Statement
        problem_div = soup.find('div', class_='problem-statement')
        if problem_div:
            scraped_data["problem"] = problem_div.get_text(separator='\n\n', strip=True)
            
        # Step 2: Find the Tutorial Link in the sidebar
        tutorial_url = None
        # Codeforces sidebar boxes have the class 'roundbox sidebox'
        sidebar_links = soup.select('.roundbox.sidebox a')
        for link in sidebar_links:
            text = link.get_text(strip=True).lower()
            if 'tutorial' in text or 'editorial' in text:
                href = link.get('href')
                if href and '/blog/entry/' in href:
                    tutorial_url = href
                    break
                    
        # Step 3: Fetch the Tutorial Blog
        if tutorial_url:
            if not tutorial_url.startswith('http'):
                tutorial_url = f"https://codeforces.com{tutorial_url}"
                
            tut_response = requests.get(tutorial_url, headers=headers, timeout=8)
            if tut_response.status_code == 200:
                tut_soup = BeautifulSoup(tut_response.text, 'html.parser')
                # Codeforces blog content is stored inside 'ttypography' divs
                blog_div = tut_soup.find('div', class_='ttypography')
                if blog_div:
                    # Truncate to ~15,000 characters to save AI tokens while keeping enough context
                    scraped_data["tutorial"] = blog_div.get_text(separator='\n\n', strip=True)[:15000]

        # Cache the successful scrape for 24 hours
        cache.set(cache_key, scraped_data, timeout=86400)
        return scraped_data

    except Exception as e:
        scraped_data["problem"] = f"Scraping failed: {str(e)}"
        return scraped_data
    

# ==========================================
# CENTRALIZED HIGH-THROUGHPUT AI HELPER    
# ==========================================
def call_ai_engine(prompt_text):
    """
    Dispatches prompts to the open-source provider endpoint using a 
    resilient connection pool via standard requests.
    """
    api_key = getattr(settings, 'AI_API_KEY', '')
    api_url = getattr(settings, 'AI_API_URL', 'https://api.groq.com/openai/v1/chat/completions')
    model_name = getattr(settings, 'AI_MODEL_NAME', 'llama-3.3-70b-versatile') # <-- Updated

    if not api_key:
        return "AI Configuration missing. Please check your system .env file.", ""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # FIX: DeepSeek-R1 on Groq explicitly rejects the "system" role. 
    # We must combine our coaching instructions directly into the "user" role.
    combined_prompt = (
        "You are an elite Competitive Programming Coach. Provide rigorous, "
        "precise, structural feedback without conversational filler.\n\n"
        f"{prompt_text}"
    )
    
    payload = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": combined_prompt
            }
        ],
        "temperature": 0.6 # 0.6 is the mathematically recommended temperature for DeepSeek-R1
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            raw_text = response.json()['choices'][0]['message']['content']
            
            # Extract DeepSeek Reasoning Chain if present
            think_match = re.search(r'<think>(.*?)</think>', raw_text, re.DOTALL)
            reasoning = think_match.group(1).strip() if think_match else ""
            
            # Clean original text of the think block for markdown rendering
            clean_content = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
            return clean_content, reasoning
            
        elif response.status_code == 429:
            return "The upstream engine is experiencing heavy traffic volume. Please wait 60 seconds.", ""
            
        else:
            # FIX: If it fails again, this will extract the EXACT reason from Groq and print it to your screen
            error_details = response.json().get('error', {}).get('message', response.text)
            return f"API Error (Status {response.status_code}): {error_details}", ""
            
    except requests.RequestException as e:
        return f"Core network communication failure: {str(e)}", ""


# ==========================================
# VIEWS & ROUTING ENGINE                    
# ==========================================
def home_view(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            messages.error(request, "Invalid credentials.")
            return redirect('home')

    api_url = "https://contest-hive.vercel.app/api/all" 
    upcoming_contests = []
    platforms = []
    
    try:
        response = requests.get(api_url, timeout=5)
        if response.status_code == 200:
            data = response.json().get('data', {})
            all_contests = []
            now = datetime.now(timezone.utc)
            
            for platform_contests in data.values():
                for contest in platform_contests:
                    sec = contest.get('duration', 0)
                    contest['duration_formatted'] = f"{sec // 3600}h {(sec % 3600) // 60}m"
                    
                    try:
                        start_time_str = contest.get('startTime', '').replace('Z', '+0000')
                        start_dt = datetime.strptime(start_time_str, "%Y-%m-%dT%H:%M:%S%z")
                        delta = start_dt - now
                        if delta.total_seconds() > 0:
                            days = delta.days
                            hours = delta.seconds // 3600
                            if days > 0:
                                contest['time_left'] = f"{days}d {hours}h"
                            else:
                                contest['time_left'] = f"{hours}h {(delta.seconds % 3600) // 60}m"
                        else:
                            contest['time_left'] = "Started"
                    except:
                        contest['time_left'] = "TBA"
                        
                all_contests.extend(platform_contests)
            
            all_contests.sort(key=lambda x: x.get('startTime', ''))
            # Fetch up to 50 contests to ensure the filters have enough data
            upcoming_contests = all_contests[:50] 
            
            # Extract dynamically available platforms for the dropdown
            platform_set = set()
            for c in upcoming_contests:
                if c.get('platform'):
                    platform_set.add(c.get('platform'))
            platforms = sorted(list(platform_set))
            
    except requests.RequestException:
        pass

    return render(request, 'core/home.html', {
        'contests': upcoming_contests, 
        'platforms': platforms
    })


@login_required(login_url='home')
def dashboard_view(request):
    return render(request, 'core/dashboard.html')


def get_profile_analytics(handle):
    if not handle:
        return None, None

    try:
        rating_resp = requests.get(f"https://codeforces.com/api/user.rating?handle={handle}", timeout=5).json()
        time.sleep(0.5)
        status_resp = requests.get(f"https://codeforces.com/api/user.status?handle={handle}", timeout=8).json()

        if rating_resp.get('status') != 'OK' or status_resp.get('status') != 'OK':
            return None, "Failed to fetch data from Codeforces."

        contests = rating_resp['result']
        submissions = status_resp['result']
        labels, y_list, trend_line, future_preds = [], [], [], []
        current_rating, next_predicted = 0, 0

        if len(contests) >= 3:
            X = np.array([i + 1 for i in range(len(contests))]).reshape(-1, 1)
            y = np.array([c['newRating'] for c in contests])
            labels = [f"C{i + 1}" for i in range(len(contests))]

            overall_model = LinearRegression().fit(X, y)
            trend_line = overall_model.predict(X).astype(int).tolist()

            recent_window = min(len(contests), 15)
            recent_model = LinearRegression().fit(X[-recent_window:], y[-recent_window:])
            future_X = np.array([len(contests) + 1, len(contests) + 2]).reshape(-1, 1)
            future_preds = recent_model.predict(future_X).astype(int).tolist()

            labels.extend(["P1", "P2"])
            y_list = y.tolist()
            current_rating = int(y[-1])
            next_predicted = int(future_preds[0])

        unique_solved = {s['problem']['name']: s['problem'] for s in submissions if s.get('verdict') == 'OK'}.values()
        rating_counts = {}
        tag_counts = {}

        for problem in unique_solved:
            if 'rating' in problem:
                rating = problem['rating']
                rating_counts[rating] = rating_counts.get(rating, 0) + 1
            for tag in problem.get('tags', []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        sorted_ratings = sorted(rating_counts.items())
        sorted_tags = sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)
        return {
            'handle': handle,
            'ml_labels': labels,
            'ml_actual': y_list,
            'ml_trend': trend_line,
            'ml_future': future_preds,
            'current_rating': current_rating,
            'next_predicted': next_predicted,
            'hist_labels': [str(rating[0]) for rating in sorted_ratings],
            'hist_data': [rating[1] for rating in sorted_ratings],
            'pie_labels': [tag[0] for tag in sorted_tags],
            'pie_data': [tag[1] for tag in sorted_tags],
            'total_solved': len(unique_solved)
        }, None
    except Exception:
        return None, "Could not load analytics. Please check your network or try again."


def get_weak_tags(handle):
    if not handle:
        return [], None

    try:
        response = requests.get(
            f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=100",
            timeout=8
        ).json()
        if response.get('status') != 'OK':
            return [], "Failed to fetch submission history from Codeforces."

        failed_verdicts = ['TIME_LIMIT_EXCEEDED', 'WRONG_ANSWER', 'MEMORY_LIMIT_EXCEEDED', 'RUNTIME_ERROR']
        weak_tags = {}
        for submission in response['result']:
            if submission.get('verdict') in failed_verdicts:
                for tag in submission['problem'].get('tags', []):
                    weak_tags[tag] = weak_tags.get(tag, 0) + 1

        return [
            {'tag': tag, 'failures': count}
            for tag, count in sorted(weak_tags.items(), key=lambda item: item[1], reverse=True)[:5]
        ], None
    except Exception:
        return [], "System Error connecting to Codeforces."


def get_problem_tag_performance(problem_tags, submissions):
    tag_performance = {}
    for tag in problem_tags:
        tag_submissions = [
            submission for submission in submissions
            if tag in submission.get('problem', {}).get('tags', [])
        ]
        attempted = len(tag_submissions)
        solved = sum(submission.get('verdict') == 'OK' for submission in tag_submissions)
        failed = attempted - solved
        tag_performance[tag] = {
            'attempted': attempted,
            'solved': solved,
            'failed': failed,
            'success_rate': round((solved / attempted) * 100, 2) if attempted else 0
        }
    return tag_performance


def get_problem_fit(problem_rating, current_rating, submissions):
    if not problem_rating or not current_rating:
        return 'good_practice', 'A rating comparison is unavailable, so this is a neutral practice target.'

    difficulty_submissions = [
        submission for submission in submissions
        if isinstance(submission.get('problem', {}).get('rating'), int)
        and abs(submission['problem']['rating'] - problem_rating) <= 100
    ]
    difficulty_attempts = len(difficulty_submissions)
    difficulty_solved = sum(
        submission.get('verdict') == 'OK' for submission in difficulty_submissions
    )
    difficulty_success_rate = (
        difficulty_solved / difficulty_attempts
        if difficulty_attempts else None
    )
    rating_gap = problem_rating - current_rating

    if rating_gap <= -300:
        classification = 'too_easy'
    elif rating_gap >= 300:
        classification = 'too_hard'
    elif difficulty_success_rate is not None and difficulty_attempts >= 2:
        if difficulty_success_rate >= 0.8 and rating_gap <= 100:
            classification = 'too_easy'
        elif difficulty_success_rate < 0.4 and rating_gap >= -100:
            classification = 'too_hard'
        elif difficulty_success_rate < 0.6 and rating_gap >= -100:
            classification = 'stretch'
        elif rating_gap > 100:
            classification = 'stretch'
        else:
            classification = 'good_practice'
    elif rating_gap > 100:
        classification = 'stretch'
    else:
        classification = 'good_practice'

    if difficulty_success_rate is None:
        explanation = f'Problem rating is {problem_rating}, {abs(rating_gap)} points {"above" if rating_gap >= 0 else "below"} your current rating.'
    else:
        explanation = (
            f'Problem rating is {problem_rating}, {abs(rating_gap)} points '
            f'{"above" if rating_gap >= 0 else "below"} your current rating; '
            f'your success rate in this rating band is {difficulty_success_rate * 100:.0f}%.'
        )
    return classification, explanation


def build_problem_analysis(problem, profile_data, submissions):
    problem_tags = problem.get('tags', [])
    tag_performance = get_problem_tag_performance(problem_tags, submissions)
    classification, explanation = get_problem_fit(
        problem.get('rating'),
        (profile_data or {}).get('current_rating'),
        submissions
    )
    weak_tags = [
        tag for tag, performance in tag_performance.items()
        if performance['attempted'] >= 2 and performance['success_rate'] < 50
    ]
    if weak_tags:
        explanation += f' Weak tag based on success rate: {", ".join(weak_tags)}.'

    return {
        'fit': {
            'classification': classification,
            'explanation': explanation
        },
        'tag_performance': tag_performance
    }


def get_attempted_problem_keys(submissions):
    return {
        (
            str(submission.get('problem', {}).get('contestId')),
            str(submission.get('problem', {}).get('index', '')).upper()
        )
        for submission in submissions
        if submission.get('problem', {}).get('contestId') is not None
        and submission.get('problem', {}).get('index')
    }


def rank_recommendation_candidates(current_problem, contest_id, problem_index, analysis, submissions, current_rating):
    problem_pool, pool_error = get_codeforces_problem_pool()
    if pool_error:
        return [], pool_error

    current_key = (str(contest_id), str(problem_index).upper())
    attempted_keys = get_attempted_problem_keys(submissions)
    current_tags = set(current_problem.get('tags', []))
    tag_performance = analysis.get('tag_performance', {})
    weak_tags = {
        tag for tag, performance in tag_performance.items()
        if performance.get('attempted', 0) >= 2 and performance.get('success_rate', 0) < 50
    }
    ranked_candidates = []

    for candidate in problem_pool:
        candidate_key = (str(candidate['contest_id']), str(candidate['index']).upper())
        if candidate_key == current_key or candidate_key in attempted_keys:
            continue

        candidate_tags = set(candidate['tags'])
        shared_tags = len(current_tags & candidate_tags)
        weak_tag_overlap = len(weak_tags & candidate_tags)
        rating_distance = abs(candidate['rating'] - current_rating) if current_rating else 0
        upward_progression = 1 if current_rating and 0 < candidate['rating'] - current_rating <= 200 else 0
        large_jump_penalty = 1 if current_rating and candidate['rating'] - current_rating > 300 else 0
        score = (
            shared_tags * 1000
            + weak_tag_overlap * 500
            + upward_progression * 100
            - rating_distance
            - large_jump_penalty * 300
        )
        ranked_candidates.append((score, candidate))

    ranked_candidates.sort(
        key=lambda item: (
            -item[0],
            abs(item[1]['rating'] - current_rating) if current_rating else 0,
            item[1]['contest_id'],
            item[1]['index']
        )
    )
    return [candidate for _, candidate in ranked_candidates[:5]], None


def parse_recommendation_response(content, candidates):
    if not content:
        return None

    cleaned_content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
    fenced_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned_content, re.DOTALL)
    json_text = fenced_match.group(1) if fenced_match else cleaned_content
    try:
        selected = json.loads(json_text)
    except (TypeError, ValueError):
        return None

    selected_key = (str(selected.get('contest_id')), str(selected.get('index', '')).upper())
    candidate_by_key = {
        (str(candidate['contest_id']), str(candidate['index']).upper()): candidate
        for candidate in candidates
    }
    candidate = candidate_by_key.get(selected_key)
    if not candidate:
        return None

    reason = str(selected.get('reason', '')).strip()
    if not reason:
        return None
    return candidate, reason[:300]


def get_recommendation(current_problem, contest_id, problem_index, analysis, submissions, current_rating, handle):
    cache_key = f"cf_recommendation_{handle}_{contest_id}_{problem_index.upper()}"
    cache_miss = object()
    cached_recommendation = cache.get(cache_key, cache_miss)
    if cached_recommendation is not cache_miss:
        return cached_recommendation, None

    candidates, candidate_error = rank_recommendation_candidates(
        current_problem,
        contest_id,
        problem_index,
        analysis,
        submissions,
        current_rating
    )
    if candidate_error:
        return None, candidate_error
    if not candidates:
        cache.set(cache_key, None, timeout=1200)
        return None, None

    candidate_context = [
        {
            'contest_id': candidate['contest_id'],
            'index': candidate['index'],
            'name': candidate['name'],
            'rating': candidate['rating'],
            'tags': candidate['tags']
        }
        for candidate in candidates
    ]
    prompt = (
        "Choose exactly one Codeforces problem from the supplied candidates. "
        "Do not invent or modify a candidate. Return JSON only with the keys "
        "contest_id, index, and reason. Keep reason under 200 characters.\n\n"
        f"Current problem: {json.dumps(current_problem)}\n"
        f"User current rating: {current_rating}\n"
        f"Relevant tag performance: {json.dumps(analysis.get('tag_performance', {}))}\n"
        f"Candidates: {json.dumps(candidate_context)}"
    )
    content, _ = call_ai_engine(prompt)
    selected = parse_recommendation_response(content, candidates)
    if selected:
        selected_candidate, reason = selected
    else:
        selected_candidate = candidates[0]
        reason = 'Best deterministic match for your current problem tags and rating.'

    recommendation = {
        'problem': selected_candidate,
        'reason': reason
    }
    cache.set(cache_key, recommendation, timeout=1200)
    return recommendation, None


def extension_api_response(request, data, status=200):
    response = JsonResponse(data, status=status)
    origin = request.headers.get('Origin', '')
    configured_origin = getattr(settings, 'EXTENSION_ALLOWED_ORIGIN', '')
    if configured_origin and origin == configured_origin:
        response['Access-Control-Allow-Origin'] = origin
        response['Access-Control-Allow-Credentials'] = 'true'
        response['Vary'] = 'Origin'
    return response


@require_GET
def extension_context_api(request):
    contest_id = request.GET.get('contest_id', '').strip()
    problem_index = request.GET.get('index', '').strip()
    if not validate_problem_identifier(contest_id, problem_index):
        return extension_api_response(request, {
            'error': 'contest_id and index must identify a Codeforces problemset problem.'
        }, status=400)

    if not request.user.is_authenticated:
        return extension_api_response(request, {'authenticated': False}, status=401)

    handle = request.user.codeforces_handle
    problem, problem_error = get_codeforces_problem(contest_id, problem_index)
    if problem_error:
        return extension_api_response(request, {'error': problem_error}, status=404)

    problem_history, problem_history_error = get_user_problem_history(handle, contest_id, problem_index)
    submissions, submissions_error = get_user_submissions(handle)
    profile_data, analytics_error = get_profile_analytics(handle)
    weak_tags, weak_tags_error = get_weak_tags(handle)
    problem_analysis = build_problem_analysis(problem, profile_data, submissions)
    recommendation, recommendation_error = get_recommendation(
        problem,
        contest_id,
        problem_index,
        problem_analysis,
        submissions,
        (profile_data or {}).get('current_rating'),
        handle
    )
    return extension_api_response(request, {
        'authenticated': True,
        'user': {
            'username': request.user.username,
            'codeforces_handle': handle
        },
        'problem': problem,
        'problem_history': problem_history,
        'problem_analysis': problem_analysis,
        'recommendation': recommendation,
        'analytics': profile_data,
        'weak_tags': weak_tags,
        'errors': [
            error for error in (
                analytics_error,
                weak_tags_error,
                problem_history_error,
                submissions_error,
                recommendation_error
            ) if error
        ]
    })


@login_required(login_url='home')
def profile_view(request):
    handle = request.user.codeforces_handle
    profile_data, error_message = get_profile_analytics(handle)

    return render(request, 'core/profile.html', {'profile_data': profile_data, 'error_message': error_message})


@login_required(login_url='home')
def ai_code_review_view(request):
    review_html = ""
    reasoning_html = ""
    form = CodeReviewForm()

    if request.method == 'POST':
        form = CodeReviewForm(request.POST)
        if form.is_valid():
            problem_link = form.cleaned_data['problem_link']
            user_code = form.cleaned_data['code']
            
            # 1. Scrape Problem AND Tutorial
            scraped_data = scrape_codeforces_data(problem_link)
            problem_text = scraped_data['problem']
            tutorial_text = scraped_data['tutorial']
            
            # 2. Inject into the highly-constrained prompt
            prompt = f"""
            You are a strict Codeforces Judging Server and Elite CP Coach. 
            Analyze this C++ submission for problem: {problem_link}
            
            --- EXACT PROBLEM STATEMENT ---
            {problem_text}
            -------------------------------
            
            --- OFFICIAL CONTEST TUTORIAL (Contains all problems) ---
            {tutorial_text}
            ---------------------------------------------------------
            
            --- USER CODE ---
            ```cpp
            {user_code}
            ```
            -----------------
            
            CRITICAL INSTRUCTIONS:
            1. Always first check the users code's logic througlly if it correct(Don't give false positive or false Negative)
            2. SCAN THE TUTORIAL: The provided tutorial covers the entire contest. You must scan the text, locate the specific explanation and optimal time complexity for the exact problem statement above, and use that as your "Ground Truth".
            3. COMPARE LOGIC: Compare the user's approach to the official tutorial approach. If  it followed some other method and matches valid approaches and getting correct answer then its correct,  If the user's logic deviates and fails to handle the constraints or edge cases mentioned in the tutorial, MARK IT AS WRONG. Do not give false positives.
            4. IGNORE standard competitive programming boilerplate (`#include <bits/stdc++.h>`, `using namespace std;`, fast I/O). Focus 100% on algorithmic correctness.
            5. Actively hunt for:
               - Integer overflow (e.g., needing `long long`).
               - Array out-of-bounds or segmentation faults.
               - Time Limit Exceeded (Does their complexity match the optimal tutorial complexity?).
            6. NEVER use backslashes to escape underscores (write `dp[i]`, not `dp\\[i\\]`).
            7. DO NOT output a top-level title header.

             Format your response exactly using these sections:
            
            ### 1. Algorithmic Analysis & Complexity
            Briefly state how the user's code attempts to solve the problem description. Then provide the rigorous Time and Space Complexity (e.g., $O(N \\log N)$).
            
            ### 2. Adversarial Edge Case Check
            Based on the problem statement, walk through a mental dry-run of a tricky edge case. Show your step-by-step reasoning evaluating if the code breaks.
            
            ### 3. Final Verdict
            - If the code fails the constraints or logic of the problem statement, state "**Status: [Verdict]**" (Wrong Answer, TLE, MLE). You MUST provide the failing input, expected output, and observed output.
            - ONLY if the logic perfectly solves the provided problem statement, state "**Status: Likely Accepted**".
            
            ### 4. Optimization & Fixes
            If flawed, provide the corrected C++ logic. If correct, provide algorithmic optimizations.
            """

            
            content, reasoning = call_ai_engine(prompt)
            review_html = markdown.markdown(content, extensions=['fenced_code', 'tables'])
            if reasoning:
                reasoning_html = markdown.markdown(f"**AI Chain of Thought:**\n\n{reasoning}")

    return render(request, 'core/code_review.html', {
        'form': form, 
        'review_result': review_html,
        'reasoning_result': reasoning_html
    })


@login_required(login_url='home')
def weak_spot_view(request):
    ai_roadmap = None # FIXED: Template looks for ai_roadmap
    error_message = None
    handle = request.user.codeforces_handle

    if not handle:
        error_message = "Please update your profile with your Codeforces handle to use the Weak-Spot Engine."
        return render(request, 'core/weak_spot.html', {'error_message': error_message})

    if request.method == 'POST':
        try:
            weak_tags, history_error = get_weak_tags(handle)
            if not history_error:
                sorted_weak_tags = [(item['tag'], item['failures']) for item in weak_tags]
                
                if not sorted_weak_tags:
                    ai_roadmap = "<div class='alert alert-success text-center mt-4'><h4>🎉 Flawless!</h4><p>No failed submissions found in your recent history.</p></div>"
                else:
                    tags_str = ", ".join([f"{tag} ({count} fails)" for tag, count in sorted_weak_tags])
                    top_tag = sorted_weak_tags[0][0] 
                    
                    prompt = f"""
                    You are an elite Competitive Programming Coach. 
                    Your student `{handle}` is analyzing their last 100 submissions. They have predominantly failed on problems with these tags: {tags_str}.

                    Create a personalized, highly structured 4-week practice roadmap to fix these core weaknesses. Follow these formatting rules EXACTLY:
                    - NEVER use backslashes to escape underscores.
                    - Wrap all topic tags, problem metrics, and complexities inside standard backticks.
                    - DO NOT output an overall container title header at the top.

                    Format strictly in Markdown using this exact structure:

                    ### 🎯 Diagnostic Summary
                    A precise, 2-sentence technical explanation of *why* developers typically struggle with `{top_tag}` and how it relates to the other failed tags: {tags_str}.

                    ### 🗓️ 4-Week Action Plan
                    - **Week 1 (Foundations):** Outline the specific mathematical or algorithmic lemmas to review based on their weakest tag: `{top_tag}`.
                    - **Week 2 (Application):** Detail specific problem structural patterns to identify and practice.
                    - **Week 3 (Advanced):** Detail methods for combining concepts, structural optimization, or reducing memory footprints.
                    - **Week 4 (Mock Contests):** Outline an execution and timing strategy to handle these specific problems under high pressure.

                    ### 💡 Coach's Advice for {top_tag}
                    Provide exactly two highly technical, actionable coding tips designed to prevent Time Limit Exceeded (TLE) or Wrong Answer (WA) verdicts when implementing solutions for `{top_tag}`.

                    You MUST format these tips as numbered list items, and each item MUST be separated by a full empty line so they render cleanly on separate lines:

                    1. [Insert first highly technical tip here with deep algorithmic context.]

                    2. [Insert second highly technical tip here focusing on implementation or edge-case control.]

                    CRITICAL: Be encouraging but deeply technical. Do not write filler intros/outros. Output ONLY the markdown content.
                    """
                    
                    content, _ = call_ai_engine(prompt)
                    ai_roadmap = markdown.markdown(content)
            else:
                error_message = history_error
        except Exception as e:
            error_message = "System Error connecting to Codeforces."
            
    return render(request, 'core/weak_spot.html', {
        'ai_roadmap': ai_roadmap,
        'error_message': error_message,
        'handle': handle
    })


def register_view(request):
    if request.method == 'POST':
        form = CustomRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = CustomRegistrationForm()
    return render(request, 'core/register.html', {'form': form})


def logout_view(request):
    logout(request)
    return redirect('home')

@login_required(login_url='home')
def update_profile_view(request):
    if request.method == 'POST':
        form = ProfileUpdateForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile updated successfully!")
            return redirect('profile')
    else:
        form = ProfileUpdateForm(instance=request.user)
    return render(request, 'core/update_profile.html', {'form': form})