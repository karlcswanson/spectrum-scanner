from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_alter_scannergroup_options_alter_scansummary_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='scanner',
            name='asset_tag',
            field=models.CharField(blank=True, db_index=True, max_length=200),
        ),
        migrations.AddField(
            model_name='scanner',
            name='metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
