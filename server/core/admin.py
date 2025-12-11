"""Admin configuration for core models."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from .models import Scanner, Band, BandTemplate, Scan, ScanAggregate, UserMQTTCredentials


class BandInline(admin.TabularInline):
    """Inline editor for scanner bands."""
    model = Band
    extra = 1
    fields = ['name', 'start_hz', 'stop_hz', 'enabled', 'antenna', 'color']


@admin.register(Scanner)
class ScannerAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_id', 'scanner_type', 'location', 'enabled', 'online', 'scanning', 'last_seen']
    list_filter = ['scanner_type', 'enabled', 'online', 'scanning']
    search_fields = ['id', 'name', 'location']
    readonly_fields = ['id', 'online', 'scanning', 'current_band', 'last_seen', 'created_at', 'updated_at', 'credentials_display']
    inlines = [BandInline]
    actions = ['regenerate_tokens']
    change_form_template = 'admin/core/scanner/change_form.html'

    fieldsets = (
        (None, {
            'fields': ('name', 'scanner_type', 'location', 'description')
        }),
        ('Authentication', {
            'fields': ('enabled', 'credentials_display'),
            'description': 'Copy these credentials to the scanner config.yaml'
        }),
        ('Status (read-only)', {
            'fields': ('online', 'scanning', 'current_band', 'last_seen'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def short_id(self, obj):
        """Show truncated UUID for list display."""
        return str(obj.id)[:8]
    short_id.short_description = 'ID'

    def credentials_display(self, obj):
        """Show credentials in a copyable format."""
        if obj.pk:
            return format_html(
                '<pre style="background:#f5f5f5;padding:10px;border-radius:4px;font-size:12px;">'
                'mqtt:\n'
                '  id: "{}"\n'
                '  token: "{}"</pre>',
                obj.id,
                obj.auth_token
            )
        return "Save scanner first to generate credentials"
    credentials_display.short_description = 'Scanner Credentials'

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<uuid:pk>/regenerate/', self.admin_site.admin_view(self.regenerate_token_view), name='core_scanner_regenerate'),
        ]
        return custom_urls + urls

    def regenerate_token_view(self, request, pk):
        from django.shortcuts import redirect
        from django.contrib import messages
        scanner = Scanner.objects.get(pk=pk)
        scanner.regenerate_token()
        messages.success(request, f'Token regenerated for {scanner.name}')
        return redirect('admin:core_scanner_change', pk)

    @admin.action(description='Regenerate auth tokens for selected scanners')
    def regenerate_tokens(self, request, queryset):
        for scanner in queryset:
            scanner.regenerate_token()
        self.message_user(request, f"Regenerated tokens for {queryset.count()} scanner(s)")


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


class UserMQTTCredentialsInline(admin.StackedInline):
    """Inline for MQTT credentials on User admin."""
    model = UserMQTTCredentials
    can_delete = False
    verbose_name = 'MQTT Credentials'
    verbose_name_plural = 'MQTT Credentials'
    readonly_fields = ['mqtt_id', 'credentials_display', 'created_at', 'updated_at']
    fields = ['credentials_display', 'mqtt_id', 'created_at', 'updated_at']

    def credentials_display(self, obj):
        if obj.pk:
            return format_html(
                '<pre style="background:#f5f5f5;padding:10px;border-radius:4px;font-size:12px;">'
                'username: "{}"\n'
                'password: "{}"</pre>',
                obj.mqtt_id,
                obj.auth_token
            )
        return "Save user first to generate credentials"
    credentials_display.short_description = 'MQTT Credentials'


class UserAdmin(BaseUserAdmin):
    """Extended User admin with MQTT credentials."""
    inlines = list(BaseUserAdmin.inlines) + [UserMQTTCredentialsInline]

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('<int:user_id>/regenerate-mqtt-token/', self.admin_site.admin_view(self.regenerate_mqtt_token_view), name='auth_user_regenerate_mqtt'),
        ]
        return custom_urls + urls

    def regenerate_mqtt_token_view(self, request, user_id):
        from django.shortcuts import redirect
        from django.contrib import messages
        user = User.objects.get(pk=user_id)
        creds, _ = UserMQTTCredentials.objects.get_or_create(user=user)
        creds.regenerate_token()
        messages.success(request, f'MQTT token regenerated for {user.username}')
        return redirect('admin:auth_user_change', user_id)


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
