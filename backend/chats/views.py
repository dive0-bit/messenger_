from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from accounts.models import Profiles

from .models import Conversation, ConversationMember, Message
from .serializers import MessageSerializer
from .services import broadcast_message


def is_member(conversation_id, user):
    # is this user really part of the conversation?
    return ConversationMember.objects.filter(
        conversation_id=conversation_id, user=user
    ).exists()


def conversation_to_dict(conversation, user):
    # Build the data for one row of the sidebar list.
    # "participant" is the OTHER person, not the logged in user.
    other_member = (
        conversation.conversationmember_set
        .exclude(user=user)
        .select_related('user')
        .first()
    )
    last_message = conversation.message_set.order_by('-created_at').first()

    participant = ''
    participant_picture = ''
    if other_member:
        participant = other_member.user.username
        profile = getattr(other_member.user, 'profiles', None)
        if profile and profile.profile_picture:
            participant_picture = profile.profile_picture.url

    return {
        'id': conversation.id,
        'participant': participant,
        'participant_picture': participant_picture,
        'last_message': last_message.content if last_message else 'No messages yet',
        'last_message_at': last_message.created_at if last_message else conversation.created_at,
    }


@api_view(['GET'])
def conversation_list(request):
    conversations = Conversation.objects.filter(conversationmember__user=request.user)
    data = [conversation_to_dict(item, request.user) for item in conversations]

    # the chat with the newest message goes to the top
    data.sort(key=lambda item: item['last_message_at'], reverse=True)
    return Response(data)


@api_view(['POST'])
def add_conversation(request):
    # Start a chat with someone by typing their unique id
    unique_id = str(request.data.get('unique_id', '')).strip()
    if not unique_id:
        return Response({'detail': 'Unique ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

    profile = Profiles.objects.select_related('user').filter(unique_id=unique_id).first()
    if profile is None:
        return Response(
            {'detail': 'User with this Unique ID does not exist.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    recipient = profile.user
    if recipient == request.user:
        return Response(
            {'detail': 'You cannot start a conversation with yourself.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # if these two people already have a chat, just return it
    # (two separate filter() calls = "has a member X" AND "has a member Y")
    existing = (
        Conversation.objects
        .filter(conversationmember__user=request.user)
        .filter(conversationmember__user=recipient)
        .first()
    )
    if existing:
        return Response({
            'created': False,
            'conversation': conversation_to_dict(existing, request.user),
        })

    # atomic = either everything below is saved, or nothing is
    with transaction.atomic():
        conversation = Conversation.objects.create()
        ConversationMember.objects.create(conversation=conversation, user=request.user)
        ConversationMember.objects.create(conversation=conversation, user=recipient)
        first_message = Message.objects.create(
            conversation=conversation, sender=request.user, content='Hi!'
        )

    # tell the other person right now (if they are online)
    broadcast_message(dict(MessageSerializer(first_message).data), [recipient.id])

    return Response(
        {
            'created': True,
            'conversation': conversation_to_dict(conversation, request.user),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'POST'])
def conversation_messages(request, conversation_id):
    # A non-member gets 404 (not 403), so nobody can find out which ids exist
    if not is_member(conversation_id, request.user):
        return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        messages = (
            Message.objects
            .filter(conversation_id=conversation_id)
            .select_related('sender')
            .order_by('created_at')
        )
        return Response(MessageSerializer(messages, many=True).data)

    # POST = send a message with plain HTTP (used when the websocket is not connected)
    serializer = MessageSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    message = serializer.save(conversation_id=conversation_id, sender=request.user)
    message_data = dict(MessageSerializer(message).data)

    other_user_ids = list(
        ConversationMember.objects
        .filter(conversation_id=conversation_id)
        .exclude(user=request.user)
        .values_list('user_id', flat=True)
    )
    broadcast_message(message_data, other_user_ids)

    return Response(message_data, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def conversation_delete(request, conversation_id):
    if not is_member(conversation_id, request.user):
        return Response({'detail': 'Conversation not found.'}, status=status.HTTP_404_NOT_FOUND)

    # messages and members are deleted automatically (on_delete=CASCADE)
    Conversation.objects.filter(id=conversation_id).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)
