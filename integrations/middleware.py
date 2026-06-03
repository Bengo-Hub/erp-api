from cryptography.fernet import Fernet
from core.models import AppSettings

class AppConfigs:
    """Ensures the ERP-local crypto keys exist. Payment-integration seeding
    (MPESA/PAYPAL/CARD) moved to treasury-api with the payment gateways."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # create default crypto keys (ERP-local, used by core.AppSettings)
        if AppSettings.objects.first() is None:
            AppSettings.objects.update_or_create(
                app_key=Fernet.generate_key().decode('utf-8'),
                cypher_key=Fernet.generate_key().decode('utf-8'),
            )

        response = self.get_response(request)
        return response
