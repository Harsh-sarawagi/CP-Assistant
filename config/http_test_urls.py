"""Only explicitly reviewed, non-personalized read-only views are exposed."""
from django.http import HttpResponse, JsonResponse
from django.urls import path, re_path
from core.profile_views import public_analytics


def index(request):
    return HttpResponse('''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CP Assistant HTTP test</title><main style="max-width:650px;margin:60px auto;font:16px/1.6 system-ui;padding:20px">
<h1>CP Assistant: public HTTP test</h1><p>Django and Nginx are responding.</p>
<p>Accounts, private data, extension connections and AI actions are disabled.</p>
<p>Public read-only API: <code>/api/profiles/{handle}/analytics/</code></p>
<p>Use the HTTPS deployment for the complete application.</p></main></html>''')


def health(request):
    # Liveness only: HTTP testing is explicitly database-free.
    return JsonResponse({'status': 'ok', 'mode': 'public-read-only', 'database': 'disabled'})


urlpatterns = [
    path('', index, name='http_test_index'),
    path('health/', health, name='http_test_health'),
    re_path(r'^api/profiles/(?P<handle>[A-Za-z0-9_.-]{1,24})/analytics/$', public_analytics, name='http_test_analytics'),
    re_path(r'^api/profiles/(?P<handle>[A-Za-z0-9_.-]{1,24})/weaknesses/$', public_analytics, {'section': 'weaknesses'}, name='http_test_weaknesses'),
    re_path(r'^api/profiles/(?P<handle>[A-Za-z0-9_.-]{1,24})/practice/$', public_analytics, {'section': 'practice'}, name='http_test_practice'),
]
