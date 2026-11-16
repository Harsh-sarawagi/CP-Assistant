from django.core.paginator import Paginator, EmptyPage
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404

from core.forms import PersonalNoteForm
from core.models import PersonalNote
from .extension_auth import APIError


def serialize(note):
    return {'id': note.pk, 'title': note.title, 'content': note.content, 'topic': note.topic,
            'created_at': note.created_at.isoformat(), 'updated_at': note.updated_at.isoformat()}


def listing(user, query):
    q, topic = query.get('q', '').strip(), query.get('topic', '').strip()
    if len(q) > 200 or len(topic) > 300:
        raise APIError('Search or topic is too long.')
    notes = PersonalNote.objects.filter(owner=user)
    topics = list(notes.exclude(topic='').order_by('topic').values_list('topic', flat=True).distinct())
    if q:
        notes = notes.filter(Q(title__icontains=q) | Q(content__icontains=q) | Q(topic__icontains=q))
    if topic:
        notes = notes.filter(topic__iexact=topic)
    try:
        page = int(query.get('page', '1'))
        if page < 1:
            raise ValueError()
        result = Paginator(notes, 20).page(page)
    except (ValueError, TypeError, EmptyPage):
        raise APIError('Invalid notebook page.') from None
    return {'results': [serialize(note) for note in result], 'count': result.paginator.count,
            'page': page, 'next_page': page + 1 if result.has_next() else None, 'topics': topics}


def save(user, payload, note_id=None, delete=False):
    with transaction.atomic():
        note = get_object_or_404(PersonalNote.objects.select_for_update(), owner=user, pk=note_id) if note_id else None
        if note and payload.get('updated_at') != note.updated_at.isoformat():
            raise APIError('This note changed elsewhere. Reload it before saving or deleting.', 409)
        if delete:
            note.delete()
            return {'deleted': True}
        if not all(isinstance(payload.get(k, ''), str) for k in ['title', 'content', 'topic']):
            raise APIError('Note fields must be text.')
        form = PersonalNoteForm(payload, instance=note)
        if not form.is_valid():
            raise APIError('Provide a title (up to 200 characters), content (up to 20,000), and optional topic (up to 300).')
        note = form.save(commit=False)
        note.owner = user
        note.save()
        return serialize(note)
