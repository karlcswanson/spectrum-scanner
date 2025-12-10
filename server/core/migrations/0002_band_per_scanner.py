# Generated manually - Band now belongs to Scanner

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        # Create BandTemplate model (copy of old Band structure)
        migrations.CreateModel(
            name='BandTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('start_hz', models.BigIntegerField()),
                ('stop_hz', models.BigIntegerField()),
                ('description', models.TextField(blank=True)),
                ('color', models.CharField(default='#3b82f6', max_length=20)),
            ],
            options={
                'ordering': ['start_hz'],
            },
        ),

        # Add new fields to Band
        migrations.AddField(
            model_name='band',
            name='enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='band',
            name='antenna',
            field=models.CharField(blank=True, max_length=10),
        ),
        migrations.AddField(
            model_name='band',
            name='dwell_time_ms',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='band',
            name='scanner',
            field=models.ForeignKey(
                null=True,  # Temporarily allow null
                on_delete=django.db.models.deletion.CASCADE,
                related_name='bands',
                to='core.scanner'
            ),
        ),

        # Add unique constraint
        migrations.AlterUniqueTogether(
            name='band',
            unique_together={('scanner', 'name')},
        ),
    ]
