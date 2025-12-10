"""Admin configuration for core models."""

from django.contrib import admin
from .models import Scanner, Band, BandTemplate, Scan, ScanAggregate


class BandInline(admin.TabularInline):
    """Inline editor for scanner bands."""
    model = Band
    extra = 1
    fields = ['name', 'start_hz', 'stop_hz', 'enabled', 'antenna', 'color']


@admin.register(Scanner)
class ScannerAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'scanner_type', 'location', 'online', 'scanning', 'last_seen']
    list_filter = ['scanner_type', 'online', 'scanning']
    search_fields = ['id', 'name', 'location']
    readonly_fields = ['online', 'scanning', 'current_band', 'last_seen']
    inlines = [BandInline]


@admin.register(BandTemplate)
class BandTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_hz', 'stop_hz', 'color']
    ordering = ['start_hz']


@admin.register(Band)
class BandAdmin(admin.ModelAdmin):
    list_display = ['scanner', 'name', 'start_mhz', 'stop_mhz', 'enabled', 'antenna', 'color']
    list_filter = ['scanner', 'enabled']
    ordering = ['scanner', 'start_hz']


@admin.register(Scan)
class ScanAdmin(admin.ModelAdmin):
    list_display = ['scanner', 'band', 'timestamp', 'hz_lo', 'hz_hi', 'bin_count']
    list_filter = ['scanner', 'band']
    date_hierarchy = 'timestamp'
    readonly_fields = ['scanner', 'timestamp', 'hz_lo', 'hz_hi', 'step_hz', 'power', 'metadata']


@admin.register(ScanAggregate)
class ScanAggregateAdmin(admin.ModelAdmin):
    list_display = ['scanner', 'band', 'aggregate_type', 'period_type', 'period_start', 'scan_count']
    list_filter = ['scanner', 'aggregate_type', 'period_type']
    date_hierarchy = 'period_start'
