import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

# This must run before we import anything that uses models
django_app = get_asgi_application()

from chats.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    # normal requests (REST API, admin) are handled by Django
    'http': django_app,

    # websocket requests:
    #  - AllowedHostsOriginValidator blocks websocket calls coming from other websites
    #  - AuthMiddlewareStack reads the login cookie and sets scope["user"]
    'websocket': AllowedHostsOriginValidator(
        AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    ),
})
