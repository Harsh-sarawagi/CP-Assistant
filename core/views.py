# filepath: core/views.py
import requests
import time
import re
import numpy as np
import markdown
from datetime import datetime, timezone
from sklearn.linear_model import LinearRegression
from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import CustomRegistrationForm, ProfileUpdateForm, CodeReviewForm, ComparisonForm
from bs4 import BeautifulSoup
from django.core.cache import cache

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


@login_required(login_url='home')
def profile_view(request):
    handle = request.user.codeforces_handle
    profile_data = None
    error_message = None

    if handle:
        try:
            rating_resp = requests.get(f"https://codeforces.com/api/user.rating?handle={handle}", timeout=5).json()
            time.sleep(0.5) 
            status_resp = requests.get(f"https://codeforces.com/api/user.status?handle={handle}", timeout=8).json()

            if rating_resp.get('status') == 'OK' and status_resp.get('status') == 'OK':
                contests = rating_resp['result']
                submissions = status_resp['result']

                labels, y_list, trend_line, future_preds = [], [], [], []
                current_rating, next_predicted = 0, 0
                
                if len(contests) >= 3:
                    X = np.array([i+1 for i in range(len(contests))]).reshape(-1, 1)
                    y = np.array([c['newRating'] for c in contests])
                    labels = [f"C{i+1}" for i in range(len(contests))]
                    
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
                
                for prob in unique_solved:
                    if 'rating' in prob:
                        r = prob['rating']
                        rating_counts[r] = rating_counts.get(r, 0) + 1
                    for tag in prob.get('tags', []):
                        tag_counts[tag] = tag_counts.get(tag, 0) + 1

                sorted_ratings = sorted(rating_counts.items())
                hist_labels = [str(r[0]) for r in sorted_ratings]
                hist_data = [r[1] for r in sorted_ratings]

                sorted_tags = sorted(tag_counts.items(), key=lambda item: item[1], reverse=True)
                pie_labels = [t[0] for t in sorted_tags]
                pie_data = [t[1] for t in sorted_tags]

                profile_data = {
                    'handle': handle,
                    'ml_labels': labels,
                    'ml_actual': y_list,
                    'ml_trend': trend_line,
                    'ml_future': future_preds,
                    'current_rating': current_rating,
                    'next_predicted': next_predicted,
                    'hist_labels': hist_labels,
                    'hist_data': hist_data,
                    'pie_labels': pie_labels,
                    'pie_data': pie_data,
                    'total_solved': len(unique_solved)
                }
            else:
                error_message = "Failed to fetch data from Codeforces."
        except Exception as e:
            error_message = "Could not load analytics. Please check your network or try again."

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
def compare_view(request):
    chart_data = None
    ai_analysis = None
    error_message = None
    
    initial_data = {}
    if request.user.codeforces_handle:
        initial_data['handle_1'] = request.user.codeforces_handle

    if request.method == 'POST':
        form = ComparisonForm(request.POST)
        if form.is_valid():
            # FIXED: Looking for handle_1 and handle_2
            h1 = form.cleaned_data['handle_1']
            h2 = form.cleaned_data['handle_2']

            try:
                info_resp = requests.get(f"https://codeforces.com/api/user.info?handles={h1};{h2}", timeout=5).json()
                time.sleep(0.5)
                s1_resp = requests.get(f"https://codeforces.com/api/user.status?handle={h1}", timeout=8).json()
                time.sleep(0.5)
                s2_resp = requests.get(f"https://codeforces.com/api/user.status?handle={h2}", timeout=8).json()

                if info_resp.get('status') == 'OK' and s1_resp.get('status') == 'OK' and s2_resp.get('status') == 'OK':
                    u1_info, u2_info = info_resp['result'][0], info_resp['result'][1]
                    s1_data, s2_data = s1_resp['result'], s2_resp['result']

                    def analyze_submissions(subs):
                        total = len(subs)
                        if total == 0: return 0, 0, {}
                        accepted = [s for s in subs if s.get('verdict') == 'OK']
                        unique_solved = len(set([s['problem']['name'] for s in accepted if 'name' in s['problem']]))
                        acc_rate = round((len(accepted) / total) * 100, 1)
                        tag_counts = {}
                        for s in accepted:
                            for tag in s['problem'].get('tags', []):
                                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                        return unique_solved, acc_rate, tag_counts

                    u1_solved, u1_acc, u1_tags = analyze_submissions(s1_data)
                    u2_solved, u2_acc, u2_tags = analyze_submissions(s2_data)

                    common_tags = list(set(list(u1_tags.keys()) + list(u2_tags.keys())))
                    common_tags.sort(key=lambda t: u1_tags.get(t, 0) + u2_tags.get(t, 0), reverse=True)
                    top_5_categories = common_tags[:5] if common_tags else ["Math", "Greedy", "DP", "Graphs", "Strings"]

                    # FIXED: Restored the dictionary Chart.js needs to draw the visuals
                    chart_data = {
                        'u1_name': u1_info.get('handle', h1),
                        'u2_name': u2_info.get('handle', h2),
                        'solved': [u1_solved, u2_solved],
                        'acc_rates': [u1_acc, u2_acc],
                        'categories': top_5_categories,
                        'u1_categories': [u1_tags.get(tag, 0) for tag in top_5_categories],
                        'u2_categories': [u2_tags.get(tag, 0) for tag in top_5_categories]
                    }

                    u1_handle = u1_info.get('handle', 'Player 1')
                    u2_handle = u2_info.get('handle', 'Player 2')
                    prompt = f"""
                    You are an elite Competitive Programming Coach. Compare these two competitor profiles:
                    - {u1_handle}: Rating: {u1_info.get('rating', 'Unrated')}, Solved: {u1_solved}, Accuracy: {u1_acc}%
                    - {u2_handle}: Rating: {u2_info.get('rating', 'Unrated')}, Solved: {u2_solved}, Accuracy: {u2_acc}%

                    Write a highly detailed, sharp professional comparison formatted strictly in Markdown. 
                    Follow these formatting rules EXACTLY:
                    - NEVER use backslashes to escape underscores or special characters. Do NOT write `S\\_i`.
                    - Refer to the competitors ONLY by their actual handles (`{u1_handle}` and `{u2_handle}`). Do NOT use generic terms like "Competitor 1" or "Player 2".
                    - Wrap all handles, tags, and code elements in standard backticks.

                    Format your response exactly using these sections:

                    ### 🎯 The Matchup: {u1_handle} vs {u2_handle}
                    Provide a clear, 2-sentence statistical summary evaluating the skill gap or competitive tension between these two profiles.

                    ### ⚡ Competitive Metrics Breakdown
                    Analyze who is more accurate and who grinds out more problems. Contrast their styles (e.g., speed vs accuracy).

                    ### 🛠️ Strategic Roadmap for {u1_handle}
                    Based on their performance gaps, provide exactly two highly technical, actionable points showing what `{u1_handle}` must change or practice to outpace `{u2_handle}`.

                    CRITICAL: Do NOT write introductory or concluding filler. Output ONLY the requested Markdown analysis.
                    """
                    content, _ = call_ai_engine(prompt)
                    ai_analysis = markdown.markdown(content)
                else:
                    error_message = "Codeforces API error. One or both handles might not exist."
            except Exception as e:
                error_message = f"Backend Network Error connecting to Codeforces."
    else:
        form = ComparisonForm(initial=initial_data)

    return render(request, 'core/compare.html', {
        'form': form,
        'chart_data': chart_data,
        'ai_analysis': ai_analysis,
        'error_message': error_message
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
            resp = requests.get(f"https://codeforces.com/api/user.status?handle={handle}&from=1&count=100", timeout=8).json()
            if resp.get('status') == 'OK':
                submissions = resp['result']
                failed_verdicts = ['TIME_LIMIT_EXCEEDED', 'WRONG_ANSWER', 'MEMORY_LIMIT_EXCEEDED', 'RUNTIME_ERROR']
                failed_subs = [s for s in submissions if s.get('verdict') in failed_verdicts]
                
                weak_tags = {}
                for s in failed_subs:
                    for tag in s['problem'].get('tags', []):
                        weak_tags[tag] = weak_tags.get(tag, 0) + 1
                
                sorted_weak_tags = sorted(weak_tags.items(), key=lambda item: item[1], reverse=True)[:5]
                
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
                error_message = "Failed to fetch submission history from Codeforces."
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