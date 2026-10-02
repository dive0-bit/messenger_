import uuid

from django.contrib.auth.models import User
from django.db import models


class Profiles(models.Model):
    # Django's built-in User only has username/email/password,
    # so extra information lives in this one-to-one profile table.
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    bio = models.TextField(blank=True, max_length=500)
    profile_picture = models.ImageField(upload_to='profile_pictures/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Public id that other people type to start a chat with this user
    unique_id = models.CharField(max_length=15, unique=True, blank=True, null=True)

    def __str__(self):
        return self.user.username

    def save(self, *args, **kwargs):
        # if the user did not choose an id, generate one like "user_1a2b3c4d"
        if not self.unique_id:
            self.unique_id = f"user_{uuid.uuid4().hex[:8]}"
        super().save(*args, **kwargs)
