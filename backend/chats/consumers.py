from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .models import ConversationMember, Message
from .serializers import MAX_MESSAGE_LENGTH, MessageSerializer


def is_logged_in(user):
    return user is not None and user.is_authenticated


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """
    One websocket connection = one user with one chat window open.
    Everybody who opens the same conversation joins the group "conversation_<id>",
    so a message sent to the group reaches all of them.
    """

    async def connect(self):
        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.group_name = f'conversation_{self.conversation_id}'

        if not await self.user_can_join():
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        # group_name only exists if connect() got far enough
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        # called when the browser sends something: {"type": "message", "content": "hello"}
        if not isinstance(content, dict) or content.get('type') != 'message':
            await self.send_json({'type': 'error', 'detail': 'Unsupported event type.'})
            return

        text = str(content.get('content', '')).strip()
        if not text:
            await self.send_json({'type': 'error', 'detail': 'Message cannot be empty.'})
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            await self.send_json({'type': 'error', 'detail': 'Message is too long.'})
            return

        message_data, other_user_ids = await self.save_message(text)

        # 1) everybody who has this chat open
        await self.channel_layer.group_send(self.group_name, {
            'type': 'chat.message',
            'message': message_data,
        })

        # 2) the other members get a notification, even if this chat is not open for them
        for user_id in other_user_ids:
            await self.channel_layer.group_send(f'user_notify_{user_id}', {
                'type': 'new_notification',
                'message': message_data,
            })

    async def chat_message(self, event):
        # runs for every connection in the group when group_send(type='chat.message') is called
        await self.send_json({'type': 'message', 'message': event['message']})

    @database_sync_to_async
    def user_can_join(self):
        user = self.scope.get('user')
        if not is_logged_in(user):
            return False
        return ConversationMember.objects.filter(
            conversation_id=self.conversation_id, user=user
        ).exists()

    @database_sync_to_async
    def save_message(self, text):
        # database work is normal (sync) code, so it is wrapped with database_sync_to_async
        user = self.scope['user']
        message = Message.objects.create(
            conversation_id=self.conversation_id,
            sender=user,
            content=text,
        )
        other_user_ids = list(
            ConversationMember.objects
            .filter(conversation_id=self.conversation_id)
            .exclude(user=user)
            .values_list('user_id', flat=True)
        )
        return dict(MessageSerializer(message).data), other_user_ids


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """
    Every logged in user keeps one of these connections open the whole time.
    It only receives "you got a new message" events for that user.
    """

    async def connect(self):
        user = self.scope.get('user')
        if not is_logged_in(user):
            await self.close(code=4401)
            return

        self.group_name = f'user_notify_{user.id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def new_notification(self, event):
        await self.send_json({'type': 'notification', 'message': event['message']})
