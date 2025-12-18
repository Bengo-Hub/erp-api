# Generated migration to add tax_mode and tax_rate to BaseOrder
from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('core_orders', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='baseorder',
            name='tax_mode',
            field=models.CharField(choices=[('line_items', 'Per Line Items'), ('on_total', 'On Final Amount')], default='line_items', max_length=20),
        ),
        migrations.AddField(
            model_name='baseorder',
            name='tax_rate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Tax percentage applied to subtotal when tax_mode is on_total', max_digits=5, null=True),
        ),
    ]
