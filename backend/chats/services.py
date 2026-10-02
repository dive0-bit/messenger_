import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def broadcast_message(message_data, other_user_ids):
    """
    Push a saved message to the websocket clients (used by the normal REST views).

    1. the conversation group  -> everybody who has this chat open sees it instantly
    2. one notification group per other member -> their sidebar updates even
       when they are looking at a different chat
    (The websocket consumer does the same thing itself in chats/consumers.py.)
    """
    channel_layer = get_channel_layer()

    try:
        async_to_sync(channel_layer.group_send)(
            f"conversation_{message_data['conversation']}",
            {'type': 'chat.message', 'message': message_data},
        )
        for user_id in other_user_ids:
            async_to_sync(channel_layer.group_send)(
                f"user_notify_{user_id}",
                {'type': 'new_notification', 'message': message_data},
            )
    except Exception:
        # The message is already saved in the database. If realtime fails
        # (for example Redis is down) we only log it, the user can still refresh.
        logger.exception('Could not broadcast the message over websocket')
