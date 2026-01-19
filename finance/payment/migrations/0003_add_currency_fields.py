# Generated manually to add multi-currency support
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payment', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='billingdocument',
            name='currency',
            field=models.CharField(default='KES', help_text='ISO 4217 currency code (e.g., KES, USD, EUR)', max_length=3),
        ),
        migrations.AddField(
            model_name='billingdocument',
            name='exchange_rate',
            field=models.DecimalField(decimal_places=6, default=Decimal('1.000000'), help_text='Exchange rate to KES at time of document creation', max_digits=15),
        ),
        migrations.AddField(
            model_name='payment',
            name='currency',
            field=models.CharField(default='KES', help_text='ISO 4217 currency code (e.g., KES, USD, EUR)', max_length=3),
        ),
        migrations.AddField(
            model_name='payment',
            name='exchange_rate',
            field=models.DecimalField(decimal_places=6, default=Decimal('1.000000'), help_text='Exchange rate to KES at time of payment', max_digits=15),
        ),
        migrations.AddIndex(
            model_name='payment',
            index=models.Index(fields=['currency'], name='idx_payment_currency'),
        ),
    ]
