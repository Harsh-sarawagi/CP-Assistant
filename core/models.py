from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid

class CustomUser(AbstractUser):
    # Added specific fields for the CP Analyzer
    codeforces_handle = models.CharField(max_length=100, blank=True, null=True, unique=True)
    profile_picture = models.URLField(blank=True, null=True, help_text="URL to Codeforces avatar")

    def __str__(self):
        return self.username


class MistakeNote(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='mistake_notes')
    contest_id = models.PositiveBigIntegerField()
    problem_index = models.CharField(max_length=16)
    problem_name = models.CharField(max_length=200, blank=True)
    mistake = models.TextField(max_length=4000, blank=True)
    lesson = models.TextField(max_length=4000, blank=True)
    topics = models.CharField(max_length=300, blank=True)
    needs_revision = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'contest_id', 'problem_index'], name='unique_user_problem_note')]
        ordering = ['-updated_at']


class PersonalNote(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='personal_notes')
    title = models.CharField(max_length=200)
    content = models.TextField(max_length=20000)
    topic = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    legacy_note = models.OneToOneField(MistakeNote, null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-updated_at', '-id']


class ExtensionLinkRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    extension_id = models.CharField(max_length=32)
    state_hash = models.CharField(max_length=64)
    challenge = models.CharField(max_length=43)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64, blank=True)
    code_expires_at = models.DateTimeField(null=True)
    consumed_at = models.DateTimeField(null=True)


class ExtensionGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='extension_grants')
    extension_id = models.CharField(max_length=32)
    scopes = models.CharField(max_length=100, default='notes:read notes:write ai:generate')
    access_hash = models.CharField(max_length=64, unique=True)
    access_expires_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True)


class ExtensionRefreshToken(models.Model):
    grant = models.ForeignKey(ExtensionGrant, on_delete=models.CASCADE, related_name='refresh_tokens')
    digest = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(default=timezone.now)
    used_at = models.DateTimeField(null=True)


class AIPlanQuota(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, primary_key=True, on_delete=models.CASCADE)
    window_start = models.DateTimeField(default=timezone.now)
    attempts = models.PositiveIntegerField(default=0)
    in_flight_until = models.DateTimeField(null=True)
