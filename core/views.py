# filepath: core/views.py
import requests
import re
from datetime import datetime, timezone
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from urllib.parse import urlsplit, urlencode
from .forms import CustomRegistrationForm, ProfileUpdateForm, CodeReviewForm
from .services.code_review import parse_review, review_prompt, source_lines
from bs4 import BeautifulSoup
from django.core.cache import cache

def scrape_codeforces_data(url):
    """
    Fetches the problem statement AND attempts to fetch the official contest tutorial.
    Returns a dictionary: {'problem': text, 'tutorial': text}
    """
    from .services.urls import problem_url
    url = problem_url(url)
    if not url:
        return {"problem": "Not a supported Codeforces problem URL.", "tutorial": ""}
        
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
        response = requests.get(url, headers=headers, timeout=8, allow_redirects=False)
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
                
            parsed_tutorial = urlsplit(tutorial_url)
            if parsed_tutorial.hostname not in {'codeforces.com', 'www.codeforces.com'} or parsed_tutorial.username or not re.fullmatch(r'/blog/entry/[0-9]+/?', parsed_tutorial.path):
                return scraped_data
            tutorial_url = 'https://codeforces.com' + parsed_tutorial.path
            tut_response = requests.get(tutorial_url, headers=headers, timeout=8, allow_redirects=False)
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
        scraped_data["problem"] = "Scraping failed. Please retry later."
        return scraped_data
    

# ==========================================
# CENTRALIZED HIGH-THROUGHPUT AI HELPER    
# ==========================================
def call_ai_engine(prompt_text, *, max_tokens=None):
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

    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 200:
            raw_text = response.json()['choices'][0]['message']['content']
            if not isinstance(raw_text, str) or not raw_text.strip():
                return "The AI engine returned an invalid response. Please try again.", ""
            
            # Extract DeepSeek Reasoning Chain if present
            think_match = re.search(r'<think>(.*?)</think>', raw_text, re.DOTALL)
            reasoning = think_match.group(1).strip() if think_match else ""
            
            # Clean original text of the think block for markdown rendering
            clean_content = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
            return clean_content, reasoning
            
        elif response.status_code == 429:
            return "The upstream engine is experiencing heavy traffic volume. Please wait 60 seconds.", ""
            
        else:
            return f"AI service unavailable (HTTP {response.status_code}). Please try again.", ""
            
    except requests.RequestException:
        return "AI network communication failed. Please try again.", ""
    except (ValueError, KeyError, IndexError, TypeError):
        return "The AI engine returned an invalid response. Please try again.", ""


# ==========================================
# VIEWS & ROUTING ENGINE                    
# ==========================================
def post_login_redirect(request):
    target = request.POST.get('next') or request.GET.get('next') or ''
    if target.startswith('/') and not target.startswith('//') and url_has_allowed_host_and_scheme(target, {request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect('dashboard')


def home_view(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user is not None:
            login(request, user)
            return post_login_redirect(request)
        else:
            messages.error(request, "Invalid credentials.")
            target = request.POST.get('next', '')
            return redirect('/?' + urlencode({'next': target})) if target else redirect('home')

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
    from .models import PersonalNote, ExtensionGrant
    from django.utils import timezone as django_timezone
    return render(request, 'core/dashboard.html', {
        'note_count': PersonalNote.objects.filter(owner=request.user).count(),
        'connection_count': ExtensionGrant.objects.filter(user=request.user, revoked_at__isnull=True, expires_at__gt=django_timezone.now()).count(),
    })


def get_profile_analytics(handle):
    if not handle:
        return None, None
    from .services.codeforces import website_profile, CodeforcesError
    try:
        return website_profile(handle), None
    except CodeforcesError as error:
        return None, str(error)


@login_required(login_url='home')
def profile_view(request):
    handle = request.user.codeforces_handle
    profile_data, error_message = get_profile_analytics(handle)

    return render(request, 'core/profile.html', {'profile_data': profile_data, 'error_message': error_message})


@login_required(login_url='home')
def ai_code_review_view(request):
    form = CodeReviewForm(request.POST or None)
    context = {'form': form}
    if request.method == 'POST' and form.is_valid():
        link, code = form.cleaned_data['problem_link'], form.cleaned_data['code']
        context.update({'submitted_code': code, 'source_lines': source_lines(code)})
        scraped = scrape_codeforces_data(link)
        statement = scraped.get('problem', '')
        if not statement or statement.startswith(('Could not fetch', 'Not a supported', 'Scraping failed', 'High traffic')):
            form.add_error('problem_link', 'The problem statement is unavailable. Retry later; no AI request was made.')
        else:
            context['problem_statement'] = statement
            content, _ = call_ai_engine(review_prompt(link, statement, scraped.get('tutorial', ''), code, form.cleaned_data['language']), max_tokens=8192)
            review = parse_review(content, code)
            if review is None:
                form.add_error(None, 'AI review unavailable or incomplete. Your source is preserved. Retry only when ready.')
            else:
                context.update({'review': review, 'source_lines': source_lines(code, review['issues']),
                                'corrected_lines': source_lines(review['corrected_code']),
                                'copy_sources': {'original': code, 'suggested': review['corrected_code']}})
    return render(request, 'core/code_review.html', context)


@login_required(login_url='home')
def retired_weak_spot(request):
    return redirect('profile')


def register_view(request):
    if request.method == 'POST':
        form = CustomRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return post_login_redirect(request)
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
