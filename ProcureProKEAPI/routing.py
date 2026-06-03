from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from hrm.payroll import routing as payroll_routing
from task_management import routing as task_routing

application = ProtocolTypeRouter({
    'websocket': AuthMiddlewareStack(
        URLRouter(
            payroll_routing.websocket_urlpatterns +
            task_routing.websocket_urlpatterns
        )
    ),
})