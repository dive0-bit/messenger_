import asyncio

from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import Profiles

from .models import Conversation, ConversationMember, Message
from .routing import websocket_urlpatterns

# tests should never need a running Redis, so they use the in-memory channel layer
IN_MEMORY_LAYER = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


def make_user(username):
    user = User.objects.create_user(username, password='a-strong-password')
    Profiles.objects.create(user=user)
    return user


def make_conversation(*users):
    conversation = Conversation.objects.create()
    for user in users:
        ConversationMember.objects.create(conversation=conversation, user=user)
    return conversation


class ChatApiTests(TestCase):
    def setUp(self):
        self.alice = make_user('alice')
        self.bob = make_user('bob')
        self.client = APIClient()
        self.client.force_login(self.alice)

    def test_add_conversation_by_unique_id(self):
        response = self.client.post(
            '/api/conversations/add/',
            {'unique_id': self.bob.profiles.unique_id},
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data['created'])
        self.assertEqual(response.data['conversation']['participant'], 'bob')
        self.assertEqual(Message.objects.filter(content='Hi!').count(), 1)

    def test_adding_same_person_twice_reuses_conversation(self):
        data = {'unique_id': self.bob.profiles.unique_id}
        self.client.post('/api/conversations/add/', data, format='json')
        second = self.client.post('/api/conversations/add/', data, format='json')

        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.data['created'])
        self.assertEqual(Conversation.objects.count(), 1)

    def test_cannot_add_yourself_or_unknown_id(self):
        yourself = self.client.post(
            '/api/conversations/add/', {'unique_id': self.alice.profiles.unique_id}, format='json'
        )
        unknown = self.client.post(
            '/api/conversations/add/', {'unique_id': 'nobody'}, format='json'
        )

        self.assertEqual(yourself.status_code, 400)
        self.assertEqual(unknown.status_code, 404)

    def test_conversation_list_shows_only_my_conversations(self):
        mine = make_conversation(self.alice, self.bob)
        make_conversation(self.bob, make_user('carol'))

        response = self.client.get('/api/conversations/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data], [mine.id])

    def test_member_can_send_and_read_messages(self):
        conversation = make_conversation(self.alice, self.bob)

        sent = self.client.post(
            f'/api/conversations/{conversation.id}/messages/',
            {'content': '  Hello Bob  '},
            format='json',
        )
        self.assertEqual(sent.status_code, 201)
        self.assertEqual(sent.data['content'], 'Hello Bob')
        self.assertEqual(sent.data['sender_username'], 'alice')

        read = self.client.get(f'/api/conversations/{conversation.id}/messages/')
        self.assertEqual(read.status_code, 200)
        self.assertEqual(read.data[0]['content'], 'Hello Bob')

    def test_empty_message_is_rejected(self):
        conversation = make_conversation(self.alice, self.bob)

        response = self.client.post(
            f'/api/conversations/{conversation.id}/messages/', {'content': '   '}, format='json'
        )

        self.assertEqual(response.status_code, 400)

    def test_non_member_cannot_read_or_send(self):
        conversation = make_conversation(self.bob, make_user('carol'))
        Message.objects.create(conversation=conversation, sender=self.bob, content='Private')

        read = self.client.get(f'/api/conversations/{conversation.id}/messages/')
        send = self.client.post(
            f'/api/conversations/{conversation.id}/messages/', {'content': 'hi'}, format='json'
        )

        self.assertEqual(read.status_code, 404)
        self.assertEqual(send.status_code, 404)

    def test_member_can_delete_conversation(self):
        conversation = make_conversation(self.alice, self.bob)
        Message.objects.create(conversation=conversation, sender=self.alice, content='Delete me')

        response = self.client.delete(f'/api/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Conversation.objects.filter(id=conversation.id).exists())
        self.assertFalse(Message.objects.filter(content='Delete me').exists())

    def test_non_member_cannot_delete_conversation(self):
        conversation = make_conversation(self.bob, make_user('carol'))

        response = self.client.delete(f'/api/conversations/{conversation.id}/')

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Conversation.objects.filter(id=conversation.id).exists())

    def test_login_is_required(self):
        response = APIClient().get('/api/conversations/')

        self.assertEqual(response.status_code, 403)


@override_settings(CHANNEL_LAYERS=IN_MEMORY_LAYER)
class ChatWebsocketTests(TransactionTestCase):
    def setUp(self):
        self.alice = make_user('alice')
        self.bob = make_user('bob')
        self.conversation = make_conversation(self.alice, self.bob)

    def connect_to(self, path, user):
        # we skip the login middleware here and put the user in the scope directly
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), path)
        communicator.scope['user'] = user
        return communicator

    def test_message_is_saved_and_sent_to_the_chat_group(self):
        async def run():
            communicator = self.connect_to(f'/ws/conversations/{self.conversation.id}/', self.alice)
            connected, _ = await communicator.connect()
            self.assertTrue(connected)

            await communicator.send_json_to({'type': 'message', 'content': 'Hello over websocket'})
            payload = await communicator.receive_json_from()

            self.assertEqual(payload['type'], 'message')
            self.assertEqual(payload['message']['content'], 'Hello over websocket')
            await communicator.disconnect()

        asyncio.run(run())
        self.assertTrue(Message.objects.filter(content='Hello over websocket').exists())

    def test_other_member_gets_a_notification(self):
        async def run():
            chat = self.connect_to(f'/ws/conversations/{self.conversation.id}/', self.alice)
            notifications = self.connect_to('/ws/notifications/', self.bob)
            await chat.connect()
            await notifications.connect()

            await chat.send_json_to({'type': 'message', 'content': 'Are you there?'})
            payload = await notifications.receive_json_from()

            self.assertEqual(payload['type'], 'notification')
            self.assertEqual(payload['message']['content'], 'Are you there?')
            await chat.disconnect()
            await notifications.disconnect()

        asyncio.run(run())

    def test_non_member_cannot_connect(self):
        outsider = make_user('mallory')

        async def run():
            communicator = self.connect_to(f'/ws/conversations/{self.conversation.id}/', outsider)
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        asyncio.run(run())
