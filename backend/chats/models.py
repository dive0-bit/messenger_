from django.contrib.auth.models import User
from django.db import models


class Conversation(models.Model):
    # One chat between users. Who is inside it is stored in ConversationMember.
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Conversation {self.id}"


class ConversationMember(models.Model):
    # Links a user to a conversation (a many-to-many table written by hand)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # the same user can not be added twice to one conversation
            models.UniqueConstraint(
                fields=['conversation', 'user'],
                name='unique_conversation_member',
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - Conversation {self.conversation.id}"


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    sender = models.ForeignKey(User, on_delete=models.CASCADE)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sender.username}: {self.content[:30]}"
