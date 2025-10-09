"""
ASGI config for ProcureProKEAPI project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.0/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from ecommerce.pos import routing as pos_routing
from hrm.payroll import routing as payroll_routing
from task_management import routing as task_routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            pos_routing.websocket_urlpatterns + 
            payroll_routing.websocket_urlpatterns +
            task_routing.websocket_urlpatterns
        )
    ),
})
