from rest_framework import serializers

from .models import Message

MAX_MESSAGE_LENGTH = 2000


class MessageSerializer(serializers.ModelSerializer):
    # show the sender's name too, so the client does not need another request
    sender_username = serializers.CharField(source='sender.username', read_only=True)

    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'sender_username',
            'content', 'created_at', 'is_read',
        ]
        read_only_fields = ['conversation', 'sender', 'is_read']

    def validate_content(self, value):
        content = value.strip()
        if not content:
            raise serializers.ValidationError('Message cannot be empty.')
        if len(content) > MAX_MESSAGE_LENGTH:
            raise serializers.ValidationError(
                f'Message is too long (maximum {MAX_MESSAGE_LENGTH} characters).'
            )
        return content
