# Generated manually to add multi-currency support
from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0003_alter_expense_applicable_tax'),
    ]

    operations = [
        migrations.AddField(
            model_name='expense',
            name='currency',
            field=models.CharField(default='KES', help_text='ISO 4217 currency code (e.g., KES, USD, EUR)', max_length=3),
        ),
        migrations.AddField(
            model_name='expense',
            name='exchange_rate',
            field=models.DecimalField(decimal_places=6, default=Decimal('1.000000'), help_text='Exchange rate to KES at time of expense', max_digits=15),
        ),
    ]
