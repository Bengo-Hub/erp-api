# Generated migration for making content_type and object_id nullable

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('core_orders', '0005_alter_baseorder_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='orderitem',
            name='content_type',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='contenttypes.contenttype',
            ),
        ),
        migrations.AlterField(
            model_name='orderitem',
            name='object_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
