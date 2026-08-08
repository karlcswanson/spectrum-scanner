from django.db import migrations


class Migration(migrations.Migration):
    """Reunify the migration graph: 0010_scanner_asset_tag_scanner_metadata
    (asset_tag/metadata) and 0010_remove_access_access_exactly_one_principal_and_more
    (SSO) both branched off 0009, creating two leaf nodes. This empty merge
    migration depends on both so the graph has a single leaf again."""

    dependencies = [
        ('core', '0010_remove_access_access_exactly_one_principal_and_more'),
        ('core', '0010_scanner_asset_tag_scanner_metadata'),
    ]

    operations = []
