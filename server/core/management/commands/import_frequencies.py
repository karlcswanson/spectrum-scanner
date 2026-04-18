"""
Import monitored frequencies from a text file (one MHz value per line).

Usage:
    python manage.py import_frequencies freqs.txt
    python manage.py import_frequencies freqs.txt --category "Wireless Mics"
    python manage.py import_frequencies freqs.txt --group <uuid>
    python manage.py import_frequencies freqs.txt --scanner <uuid>
    python manage.py import_frequencies freqs.txt --prefix "Vox" --dry-run
"""

from django.core.management.base import BaseCommand

from core.models import MonitoredFrequency, Scanner, ScannerGroup


class Command(BaseCommand):
    help = "Import monitored frequencies from a text file (one MHz value per line)"

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            type=str,
            help="Path to text file with one frequency (MHz) per line",
        )
        parser.add_argument(
            "--category",
            type=str,
            default="Wireless Mics",
            help="Category for imported frequencies (default: Wireless Mics)",
        )
        parser.add_argument(
            "--prefix",
            type=str,
            default="Ch",
            help="Name prefix — each freq gets '{prefix} {n}' (default: Ch)",
        )
        parser.add_argument(
            "--scanner",
            type=str,
            default=None,
            help="Assign to this scanner UUID",
        )
        parser.add_argument(
            "--group",
            type=str,
            default=None,
            help="Assign to this scanner group UUID",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without saving",
        )

    def handle(self, *args, **options):
        filepath = options["file"]
        category = options["category"]
        prefix = options["prefix"]
        dry_run = options["dry_run"]

        # Read frequencies
        with open(filepath) as f:
            lines = [line.strip() for line in f if line.strip()]

        freqs_mhz = []
        for line in lines:
            try:
                freqs_mhz.append(float(line))
            except ValueError:
                self.stderr.write(f"Skipping invalid line: {line}")

        freqs_mhz.sort()

        if not freqs_mhz:
            self.stderr.write("No valid frequencies found.")
            return

        self.stdout.write(f"Found {len(freqs_mhz)} frequencies")

        # Resolve scope targets
        scanner = None
        group = None
        if options["scanner"]:
            scanner = Scanner.objects.get(pk=options["scanner"])
            self.stdout.write(f"  Scanner: {scanner.name}")
        if options["group"]:
            group = ScannerGroup.objects.get(pk=options["group"])
            self.stdout.write(f"  Group: {group.name}")

        if dry_run:
            self.stdout.write("\n[DRY RUN] Would create:")
            for i, mhz in enumerate(freqs_mhz, 1):
                self.stdout.write(f"  {prefix} {i}: {mhz:.4f} MHz ({int(mhz * 1e6)} Hz)")
            return

        created = 0
        skipped = 0
        for i, mhz in enumerate(freqs_mhz, 1):
            hz = int(mhz * 1_000_000)
            name = f"{prefix} {i}"

            # Skip if exact frequency already exists
            if MonitoredFrequency.objects.filter(frequency_hz=hz).exists():
                self.stdout.write(f"  Skip (exists): {mhz:.4f} MHz")
                skipped += 1
                continue

            mf = MonitoredFrequency.objects.create(
                frequency_hz=hz,
                name=name,
                category=category,
            )
            if scanner:
                mf.scanners.add(scanner)
            if group:
                mf.groups.add(group)

            created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Created {created} monitored frequencies ({skipped} skipped as duplicates)"
        ))
