from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    # Added specific fields for the CP Analyzer
    codeforces_handle = models.CharField(max_length=100, blank=True, null=True, unique=True)
    profile_picture = models.URLField(blank=True, null=True, help_text="URL to Codeforces avatar")

    def __str__(self):
        return self.username