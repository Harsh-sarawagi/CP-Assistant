"""First-party public-extension PKCE flow and opaque, revocable credentials."""
import base64
from datetime import timedelta
from functools import wraps
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse, Http404
from django.utils import timezone
from django.utils.cache import patch_vary_headers
from django.views.decorators.csrf import csrf_exempt

from core.models import ExtensionGrant, ExtensionLinkRequest, ExtensionRefreshToken


class APIError(Exception):
    def __init__(self, message, status=400, code='invalid_request'):
        super().__init__(message)
        self.status, self.code = status, code


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


def allowed_origin(origin):
    return origin in {'chrome-extension://' + value for value in settings.EXTENSION_ALLOWED_IDS}


def respond(request, data, status=200):
    result = JsonResponse(data, status=status)
    origin = request.headers.get('Origin', '')
    if allowed_origin(origin):
        result['Access-Control-Allow-Origin'] = origin
        result['Access-Control-Allow-Credentials'] = 'true'
    patch_vary_headers(result, ['Origin'])
    result['Cache-Control'] = 'no-store'
    return result


def transport(request):
    if not request.is_secure() and urlsplit('http://' + request.get_host()).hostname not in {'localhost', '127.0.0.1', '::1'}:
        raise APIError('HTTPS is required outside loopback development.', 403)


def browser_transport(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            transport(request)
        except APIError as error:
            return respond(request, {'error': str(error)}, error.status)
        return view(request, *args, **kwargs)
    return wrapped


def body(request):
    if not request.content_type == 'application/json':
        raise APIError('Send application/json.', 415)
    if len(request.body) > 131072:
        raise APIError('Request too large.', 413)
    try:
        value = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise APIError('Invalid JSON.') from None
    if not isinstance(value, dict):
        raise APIError('Expected a JSON object.')
    return value


def limit(request, action, maximum=60, seconds=60):
    key = 'public_limit_' + digest(action + ':' + request.META.get('REMOTE_ADDR', 'unknown'))
    if cache.add(key, 1, timeout=seconds):
        return
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, seconds)
        count = 1
    if count > maximum:
        raise APIError('Request limit reached. Retry later.', 429, 'rate_limited')


def client_id(request, data):
    value = data.get('client_id', '')
    if not isinstance(value, str) or value not in settings.EXTENSION_ALLOWED_IDS:
        raise APIError('Extension ID is not allowlisted on this backend.', 403)
    origin = request.headers.get('Origin', '')
    if origin and origin != 'chrome-extension://' + value:
        raise APIError('Extension origin does not match the client.', 403)
    return value


def api(methods, scope=None):
    def decorate(view):
        @csrf_exempt  # No cookie authentication accepted; PKCE or scoped Bearer proof is mandatory.
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            try:
                origin = request.headers.get('Origin', '')
                if origin and not allowed_origin(origin):
                    raise APIError('Origin not allowed.', 403)
                if request.method == 'OPTIONS':
                    if not allowed_origin(origin):
                        raise APIError('Origin not allowed.', 403)
                    result = respond(request, {}, 204)
                    result['Access-Control-Allow-Methods'] = ', '.join(methods) + ', OPTIONS'
                    result['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
                    return result
                if request.method not in methods:
                    raise APIError('Method not allowed.', 405)
                if scope:
                    transport(request)
                    request.extension_grant = authenticate(request, scope)
                return view(request, *args, **kwargs)
            except APIError as error:
                return respond(request, {'error': str(error), 'code': error.code}, error.status)
            except Http404:
                return respond(request, {'error': 'Resource not found.'}, 404)
        return wrapped
    return decorate


def authenticate(request, scope=None):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer ') or len(header) > 200:
        raise APIError('Connect your Django account.', 401, 'not_connected')
    grant = ExtensionGrant.objects.select_related('user').filter(access_hash=digest(header[7:])).first()
    now = timezone.now()
    if not grant or grant.revoked_at or grant.expires_at <= now or not grant.user.is_active:
        raise APIError('Authorization is expired or revoked.', 401, 'authorization_invalid')
    if grant.access_expires_at <= now:
        raise APIError('Access credential expired.', 401, 'access_expired')
    origin = request.headers.get('Origin', '')
    if grant.extension_id not in settings.EXTENSION_ALLOWED_IDS or (origin and origin != 'chrome-extension://' + grant.extension_id):
        raise APIError('Authorization belongs to a different extension.', 403)
    if scope and scope not in grant.scopes.split():
        raise APIError('Scope not authorized.', 403)
    return grant


def start(request):
    transport(request)
    limit(request, 'connect', 20, 3600)
    data = body(request)
    extension = client_id(request, data)
    state, proof = data.get('state'), data.get('code_challenge')
    if not isinstance(state, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', state):
        raise APIError('Invalid state.')
    if not isinstance(proof, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', proof) or data.get('code_challenge_method') != 'S256':
        raise APIError('PKCE S256 is required.')
    redirect = f'https://{extension}.chromiumapp.org/callback'
    if data.get('redirect_uri') != redirect:
        raise APIError('Redirect URI is not allowed.', 403)
    item = ExtensionLinkRequest.objects.create(extension_id=extension, state_hash=digest(state), challenge=proof, expires_at=timezone.now() + timedelta(minutes=10))
    return {'request_id': str(item.pk), 'authorization_url': request.build_absolute_uri(f'/extension/authorize/{item.pk}/?state={state}')}


def issue(grant):
    access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    grant.access_hash = digest(access)
    grant.access_expires_at = timezone.now() + timedelta(seconds=settings.EXTENSION_ACCESS_SECONDS)
    grant.save()
    ExtensionRefreshToken.objects.create(grant=grant, digest=digest(refresh))
    return {'access_token': access, 'refresh_token': refresh, 'token_type': 'Bearer', 'expires_in': settings.EXTENSION_ACCESS_SECONDS,
            'authorization_expires_at': grant.expires_at.isoformat(), 'scopes': grant.scopes.split(), 'account': {'username': grant.user.username, 'codeforces_handle': grant.user.codeforces_handle}}


def exchange(request):
    transport(request)
    limit(request, 'exchange', 60, 3600)
    data = body(request)
    extension = client_id(request, data)
    verifier, state, code = data.get('code_verifier'), data.get('state'), data.get('code')
    if not isinstance(verifier, str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}', verifier) or not all(isinstance(x, str) and 1 <= len(x) <= 128 for x in [state, code]):
        raise APIError('Invalid authorization proof.')
    with transaction.atomic():
        item = ExtensionLinkRequest.objects.select_for_update().filter(pk=safe_uuid(data.get('request_id'))).first()
        now = timezone.now()
        if not item or item.extension_id != extension or item.consumed_at or item.expires_at <= now or not item.code_expires_at or item.code_expires_at <= now or not item.user_id:
            raise APIError('Authorization code expired or already used.', 400, 'invalid_code')
        if not hmac.compare_digest(item.state_hash, digest(state)) or not hmac.compare_digest(item.code_hash, digest(code)) or not hmac.compare_digest(item.challenge, challenge(verifier)):
            raise APIError('Authorization proof did not match.', 400, 'invalid_code')
        if not item.user.is_active:
            raise APIError('Account unavailable.', 403)
        item.consumed_at = now
        item.save(update_fields=['consumed_at'])
        grant = ExtensionGrant(user=item.user, extension_id=extension, expires_at=now + timedelta(days=settings.EXTENSION_AUTHORIZATION_DAYS))
        return issue(grant)


def renew(request):
    transport(request)
    limit(request, 'refresh', 120, 3600)
    data = body(request)
    extension = client_id(request, data)
    raw = data.get('refresh_token')
    if not isinstance(raw, str) or not 32 <= len(raw) <= 128:
        raise APIError('Invalid refresh credential.', 401)
    token = ExtensionRefreshToken.objects.filter(digest=digest(raw)).first()
    if not token:
        raise APIError('Authorization unavailable.', 401)
    reused = False
    result = None
    with transaction.atomic():
        grant = ExtensionGrant.objects.select_for_update().select_related('user').get(pk=token.grant_id)
        token = ExtensionRefreshToken.objects.select_for_update().get(pk=token.pk)
        now = timezone.now()
        if grant.extension_id != extension or grant.revoked_at or grant.expires_at <= now or not grant.user.is_active:
            raise APIError('Authorization expired or revoked.', 401)
        if token.used_at:
            grant.revoked_at = now
            grant.save(update_fields=['revoked_at'])
            reused = True
        else:
            token.used_at = now
            token.save(update_fields=['used_at'])
            result = issue(grant)
    # Raise after commit so replay revocation is not rolled back.
    if reused:
        raise APIError('Refresh credential reuse detected. Reconnect your account.', 401, 'refresh_reused')
    return result


def safe_uuid(value):
    from uuid import UUID
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None
