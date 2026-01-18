# Generated manually for cleanup

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_sharelink_scan_core_scan_scanner_f2f538_idx_and_more'),
    ]

    operations = [
        # Remove unused BandTemplate model
        migrations.DeleteModel(
            name='BandTemplate',
        ),
        # Remove unused ScanAggregate model
        migrations.DeleteModel(
            name='ScanAggregate',
        ),
        # Remove unused dwell_time_ms field from Band
        migrations.RemoveField(
            model_name='band',
            name='dwell_time_ms',
        ),
        # Remove unused config field from Scanner
        migrations.RemoveField(
            model_name='scanner',
            name='config',
        ),
    ]
