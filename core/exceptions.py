from typing import Any, Optional
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Optional[Response]:
    response = exception_handler(exc, context)

    if response is None:
        return Response(
            {
                "success": False,
                "error": {
                    "type": exc.__class__.__name__,
                    "detail": str(exc),
                },
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = {
        "success": False,
        "error": {
            "type": exc.__class__.__name__,
            "detail": response.data,
        },
    }
    response.data = data
    return response


