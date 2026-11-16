from django.http import JsonResponse
from django.urls import resolve, Resolver404
from . import http_test_urls as public


class PublicReadOnly:
    """Runs before all other middleware: no auth/session/static/redirect bypasses."""
    allowed = {
        'http_test_index': (public.index, {'GET', 'HEAD'}),
        'http_test_health': (public.health, {'GET', 'HEAD'}),
        'http_test_analytics': (public.public_analytics, {'GET'}),
        'http_test_weaknesses': (public.public_analytics, {'GET'}),
        'http_test_practice': (public.public_analytics, {'GET'}),
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.get_host()  # Validate the exact allowed host even on the tiny landing page.
        permitted = False
        try:
            match = resolve(request.path_info)
            view, methods = self.allowed.get(match.url_name, (None, set()))
            permitted = match.func is view and request.method in methods
        except Resolver404:
            pass
        if (not permitted or request.META.get('QUERY_STRING') or request.META.get('HTTP_COOKIE')
                or request.META.get('HTTP_AUTHORIZATION') or request.META.get('HTTP_X_HTTP_METHOD_OVERRIDE')
                or request.META.get('HTTP_TRANSFER_ENCODING') or request.META.get('CONTENT_LENGTH') not in (None, '', '0')):
            response = JsonResponse({'error': 'Unavailable in HTTP read-only test mode.'}, status=403)
        else:
            response = self.get_response(request)
        response['Cache-Control'] = 'no-store'
        return response
