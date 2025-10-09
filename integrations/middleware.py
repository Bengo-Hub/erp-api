from cryptography.fernet import Fernet
from core.models import AppSettings
from .models import Integrations, MpesaSettings, PayPalSettings, CardPaymentSettings

class AppConfigs:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        #create default key
        if AppSettings.objects.first() is None:
            _,created=AppSettings.objects.update_or_create(app_key=Fernet.generate_key().decode('utf-8'),cypher_key=Fernet.generate_key().decode('utf-8'))
        if Integrations.objects.filter(name='MPESA',integration_type='PAYMENT').first() is None:
            integration,created=Integrations.objects.update_or_create()
            setting,created=MpesaSettings.objects.update_or_create(integration=integration)
        if Integrations.objects.filter(name='PAYPAL',integration_type='PAYMENT').first() is None:
            integration,created=Integrations.objects.update_or_create()
            setting,created=PayPalSettings.objects.update_or_create(integration=integration)
        if Integrations.objects.filter(name='CARD',integration_type='PAYMENT').first() is None:
            integration,created=Integrations.objects.update_or_create()
            setting,created=CardPaymentSettings.objects.update_or_create(integration=integration)

        response = self.get_response(request)
        return response
