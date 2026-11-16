from datetime import timedelta
import hmac
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import PersonalNoteForm
from .models import ExtensionLinkRequest, ExtensionGrant, PersonalNote
from .services import extension_auth as auth, notebook, improvement
from .services.codeforces import CodeforcesError, get_profile, public_profile
from .services.analytics import valid_handle


@auth.api(['GET'])
def public_analytics(request, handle, section=None):
    auth.limit(request, 'analytics', 60, 60)
    try:
        data = public_profile(get_profile(handle))
    except CodeforcesError as error:
        return auth.respond(request, {'error': str(error)}, error.status)
    if section == 'weaknesses':
        data = {k: data[k] for k in ['history', 'weak_topics', 'focus_topics', 'patterns', 'verdicts', 'difficulty_performance', 'methodology']}
    elif section == 'practice':
        data = {'focus_topics': data['focus_topics'], 'practice': data['practice'], 'history': data['history']}
    return auth.respond(request, data)


@auth.api(['POST'])
def connection_start(request):
    return auth.respond(request, auth.start(request), 201)


@auth.api(['POST'])
def connection_exchange(request):
    return auth.respond(request, auth.exchange(request))


@auth.api(['POST'])
def connection_refresh(request):
    return auth.respond(request, auth.renew(request))


@auth.api(['GET'])
def connection_status(request):
    if not request.headers.get('Authorization'):
        return auth.respond(request, {'authenticated': False, 'website_session_active': request.user.is_authenticated})
    auth.transport(request)
    grant = auth.authenticate(request)
    return auth.respond(request, {'authenticated': True, 'account': {'username': grant.user.username, 'codeforces_handle': grant.user.codeforces_handle}, 'scopes': grant.scopes.split(), 'expires_at': grant.expires_at.isoformat()})


@auth.api(['POST'], scope='notes:read')
def connection_revoke(request):
    grant = request.extension_grant
    grant.revoked_at = timezone.now()
    grant.save(update_fields=['revoked_at'])
    return auth.respond(request, {'revoked': True})


@auth.browser_transport
@login_required(login_url='home')
@require_http_methods(['GET', 'POST'])
def authorize(request, request_id):
    item = get_object_or_404(ExtensionLinkRequest, pk=request_id)
    state = request.POST.get('state', '') if request.method == 'POST' else request.GET.get('state', '')
    if not hmac.compare_digest(item.state_hash, auth.digest(state)) or item.expires_at <= timezone.now() or item.consumed_at or item.code_hash or item.extension_id not in settings.EXTENSION_ALLOWED_IDS:
        return render(request, 'core/extension_authorize.html', {'invalid': True}, status=400)
    if request.method == 'POST':
        # Lock and recheck so parallel approvals cannot mint two codes.
        from django.db import transaction
        import secrets
        with transaction.atomic():
            item = ExtensionLinkRequest.objects.select_for_update().get(pk=item.pk)
            if item.code_hash or item.consumed_at or item.expires_at <= timezone.now():
                return render(request, 'core/extension_authorize.html', {'invalid': True}, status=400)
            params = {'state': state, 'request_id': str(item.pk)}
            if request.POST.get('decision') == 'approve':
                code = secrets.token_urlsafe(32)
                item.user = request.user
                item.code_hash = auth.digest(code)
                item.code_expires_at = timezone.now() + timedelta(seconds=90)
                params['code'] = code
            else:
                item.consumed_at = timezone.now()
                params['error'] = 'access_denied'
            item.save()
        return redirect(f'https://{item.extension_id}.chromiumapp.org/callback?' + urlencode(params))
    return render(request, 'core/extension_authorize.html', {'connection': item, 'state': state})


def notes_response(request, user, note_id=None):
    if request.method == 'GET':
        data = notebook.serialize(get_object_or_404(PersonalNote, owner=user, pk=note_id)) if note_id else notebook.listing(user, request.GET)
    elif request.method == 'POST' and note_id is None:
        data = notebook.save(user, auth.body(request))
    elif request.method in ['PUT', 'DELETE'] and note_id is not None:
        data = notebook.save(user, auth.body(request), note_id=note_id, delete=request.method == 'DELETE')
    else:
        raise auth.APIError('Method not allowed.', 405)
    return auth.respond(request, data, 201 if request.method == 'POST' else 200)


@auth.api(['GET', 'POST', 'PUT', 'DELETE'], scope='notes:read')
def extension_notes(request, note_id=None):
    if request.method != 'GET' and 'notes:write' not in request.extension_grant.scopes.split():
        raise auth.APIError('Scope not authorized.', 403)
    return notes_response(request, request.extension_grant.user, note_id)


@require_http_methods(['GET', 'POST', 'PUT', 'DELETE'])
def website_notes_api(request, note_id=None):
    if not request.user.is_authenticated:
        return auth.respond(request, {'error': 'Log in to use your notebook.'}, 401)
    try:
        return notes_response(request, request.user, note_id)
    except auth.APIError as error:
        return auth.respond(request, {'error': str(error)}, error.status)
    except Http404:
        return auth.respond(request, {'error': 'Note not found.'}, 404)


def plan_response(request, user):
    data = auth.body(request)
    if not valid_handle(data.get('handle')):
        raise auth.APIError('Invalid Codeforces handle.')
    try:
        return auth.respond(request, improvement.generate(user, data['handle']))
    except CodeforcesError as error:
        return auth.respond(request, {'error': str(error)}, error.status)


@auth.api(['POST'], scope='ai:generate')
def extension_plan(request):
    return plan_response(request, request.extension_grant.user)


@require_POST
def website_plan(request):
    if not request.user.is_authenticated:
        return auth.respond(request, {'error': 'Log in to generate a plan.'}, 401)
    try:
        return plan_response(request, request.user)
    except auth.APIError as error:
        return auth.respond(request, {'error': str(error)}, error.status)


@login_required(login_url='home')
@require_http_methods(['GET', 'POST'])
def notes_page(request):
    error, form = None, PersonalNoteForm()
    identifier = None
    edit = request.GET.get('edit')
    if request.method == 'POST':
        try:
            identifier = int(request.POST['note_id']) if request.POST.get('note_id') else None
            notebook.save(request.user, request.POST, note_id=identifier, delete=request.POST.get('action') == 'delete' and identifier is not None)
            return redirect('notes')
        except (auth.APIError, ValueError) as failure:
            error = str(failure) if isinstance(failure, auth.APIError) else 'Invalid note ID.'
            instance = get_object_or_404(PersonalNote, owner=request.user, pk=identifier) if identifier else None
            form = PersonalNoteForm(request.POST, instance=instance)
    elif edit:
        try:
            note = get_object_or_404(PersonalNote, owner=request.user, pk=int(edit))
        except ValueError:
            raise Http404() from None
        form = PersonalNoteForm(instance=note)
    try:
        data = notebook.listing(request.user, request.GET)
    except auth.APIError as failure:
        data, error = {'results': [], 'topics': [], 'count': 0}, str(failure)
    version = request.POST.get('updated_at', '') if request.method == 'POST' else form.instance.updated_at.isoformat() if form.instance.pk else ''
    return render(request, 'core/notes.html', {'form': form, 'notebook': data, 'error': error, 'note_version': version})


@login_required(login_url='home')
@require_http_methods(['GET', 'POST'])
def connections_page(request):
    if request.method == 'POST':
        grant = get_object_or_404(ExtensionGrant, user=request.user, pk=auth.safe_uuid(request.POST.get('grant_id')))
        grant.revoked_at = timezone.now()
        grant.save(update_fields=['revoked_at'])
        return redirect('extension_connections')
    return render(request, 'core/extension_connections.html', {'connections': request.user.extension_grants.filter(revoked_at__isnull=True, expires_at__gt=timezone.now())})
