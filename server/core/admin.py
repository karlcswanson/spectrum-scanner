"""Admin configuration for core models."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html
from .models import Scanner, Band, Scan, UserMQTTCredentials, ShareLink, ScannerGroup, MonitoredFrequency, Access, SiteSettings, ScanSummary


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
    filter_horizontal = ['scanner_groups']
    actions = ['regenerate_tokens']
    change_form_template = 'admin/core/scanner/change_form.html'

    fieldsets = (
        (None, {
            'fields': ('name', 'scanner_type', 'location', 'description')
        }),
        ('Groups', {
            'fields': ('scanner_groups',),
        }),
        ('Authentication', {
            'fields': ('enabled', 'credentials_display'),
            'description': 'Copy these credentials to the scanner config.yaml'
        }),
        ('Data Retention', {
            'fields': ('retention_policy',),
            'classes': ('collapse',),
            'description': 'Override the global retention policy for this scanner. Leave empty to use the global default.'
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


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    list_display = ['label', 'short_token', 'is_active', 'expires_at', 'use_count', 'last_used_at', 'created_at', 'created_by']
    list_filter = ['is_active', 'created_by']
    search_fields = ['label', 'token']
    readonly_fields = ['token', 'share_url_display', 'use_count', 'last_used_at', 'created_at', 'created_by']
    ordering = ['-created_at']
    actions = ['revoke_links', 'activate_links']

    fieldsets = (
        (None, {
            'fields': ('label', 'is_active')
        }),
        ('Share URL', {
            'fields': ('share_url_display', 'token'),
            'description': 'Copy this URL to share read-only access'
        }),
        ('Expiration', {
            'fields': ('expires_at',),
        }),
        ('Usage Stats', {
            'fields': ('use_count', 'last_used_at', 'created_at', 'created_by'),
            'classes': ('collapse',)
        }),
    )

    def short_token(self, obj):
        """Show truncated token for list display."""
        return f"{obj.token[:12]}..."
    short_token.short_description = 'Token'

    def share_url_display(self, obj):
        """Show the full share URL."""
        if obj.pk:
            url = f"/share/{obj.token}"
            return format_html(
                '<input type="text" value="{}" readonly style="width:100%;font-family:monospace;padding:8px;" '
                'onclick="this.select();" />'
                '<p style="color:#666;margin-top:4px;font-size:11px;">Click to select, then copy. '
                'Prepend your domain (e.g., https://spectrum.example.com{})</p>',
                url, url
            )
        return "Save first to generate URL"
    share_url_display.short_description = 'Share URL'

    @admin.action(description='Revoke selected share links')
    def revoke_links(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Revoked {count} share link(s)")

    @admin.action(description='Activate selected share links')
    def activate_links(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"Activated {count} share link(s)")

    def save_model(self, request, obj, form, change):
        if not change:  # New object
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ScannerGroupMembershipInline(admin.TabularInline):
    """Inline for managing scanners in a group."""
    model = Scanner.scanner_groups.through
    extra = 1
    verbose_name = 'Scanner'
    verbose_name_plural = 'Scanners'
    autocomplete_fields = ['scanner']


@admin.register(ScannerGroup)
class ScannerGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'short_id', 'scanner_count', 'start_date', 'end_date', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
    inlines = [ScannerGroupMembershipInline]

    fieldsets = (
        (None, {
            'fields': ('name', 'description', 'start_date', 'end_date')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def short_id(self, obj):
        return str(obj.id)[:8]
    short_id.short_description = 'ID'

    def scanner_count(self, obj):
        return obj.scanners.count()
    scanner_count.short_description = 'Scanners'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MonitoredFrequency)
class MonitoredFrequencyAdmin(admin.ModelAdmin):
    list_display = ['name', 'frequency_mhz_display', 'category', 'color_swatch', 'scope_summary', 'active']
    list_filter = ['category', 'active']
    search_fields = ['name', 'notes']
    filter_horizontal = ['scanners', 'groups']
    readonly_fields = ['id', 'created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('name', 'frequency_hz', 'category', 'color', 'active')
        }),
        ('Scope', {
            'fields': ('scanners', 'groups'),
            'description': 'Assign to specific scanners and/or groups. Leave both empty for a global frequency visible to all scanners.'
        }),
        ('Notes & Metadata', {
            'fields': ('notes', 'id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def frequency_mhz_display(self, obj):
        return f"{obj.frequency_hz / 1e6:.3f} MHz"
    frequency_mhz_display.short_description = 'Frequency'
    frequency_mhz_display.admin_order_field = 'frequency_hz'

    def color_swatch(self, obj):
        if obj.color:
            return format_html(
                '<span style="display:inline-block;width:14px;height:14px;background:{};border-radius:2px;vertical-align:middle;"></span> {}',
                obj.color, obj.color
            )
        return '—'
    color_swatch.short_description = 'Color'

    def scope_summary(self, obj):
        parts = []
        scanner_count = obj.scanners.count()
        group_count = obj.groups.count()
        if scanner_count:
            parts.append(f"{scanner_count} scanner{'s' if scanner_count > 1 else ''}")
        if group_count:
            parts.append(f"{group_count} group{'s' if group_count > 1 else ''}")
        return ', '.join(parts) if parts else 'Global'
    scope_summary.short_description = 'Scope'


@admin.register(Access)
class AccessAdmin(admin.ModelAdmin):
    list_display = ['label', 'who_display', 'scope_display', 'permission', 'is_active', 'use_count', 'created_at']
    list_filter = ['permission', 'is_active']
    search_fields = ['label', 'token']
    readonly_fields = ['id', 'created_at', 'updated_at', 'last_used_at', 'use_count']
    actions = ['revoke_access', 'activate_access']

    fieldsets = (
        (None, {
            'fields': ('label', 'permission', 'is_active')
        }),
        ('Principal (set exactly one)', {
            'fields': ('user', 'group', 'token'),
        }),
        ('Scope (set exactly one)', {
            'fields': ('scanner_group', 'scanner'),
        }),
        ('Expiration', {
            'fields': ('expires_at',),
        }),
        ('Usage Stats', {
            'fields': ('use_count', 'last_used_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id',),
            'classes': ('collapse',)
        }),
    )

    def who_display(self, obj):
        if obj.user:
            return obj.user.username
        if obj.group_id:
            return f"group:{obj.group.name}"
        if obj.token:
            return f"token:{obj.token[:12]}..."
        return "—"
    who_display.short_description = 'Who'

    def scope_display(self, obj):
        if obj.scanner_group:
            return f"Group: {obj.scanner_group.name}"
        if obj.scanner:
            return f"Scanner: {obj.scanner.name}"
        return "—"
    scope_display.short_description = 'Scope'

    @admin.action(description='Revoke selected access grants')
    def revoke_access(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"Revoked {count} access grant(s)")

    @admin.action(description='Activate selected access grants')
    def activate_access(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"Activated {count} access grant(s)")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ['name', 'value', 'updated_at']
    search_fields = ['name']
    readonly_fields = ['updated_at']

    fieldsets = (
        (None, {
            'fields': ('name', 'value', 'description', 'updated_at')
        }),
    )


@admin.register(ScanSummary)
class ScanSummaryAdmin(admin.ModelAdmin):
    list_display = ['scanner', 'band', 'bucket_start', 'bucket_seconds_display', 'scan_count', 'hz_lo', 'hz_hi']
    list_filter = ['scanner', 'band', 'bucket_seconds']
    date_hierarchy = 'bucket_start'
    readonly_fields = ['scanner', 'band', 'bucket_start', 'bucket_seconds', 'hz_lo', 'hz_hi', 'step_hz', 'peak_power', 'avg_power', 'scan_count']
    change_list_template = 'admin/core/scansummary/change_list.html'

    def bucket_seconds_display(self, obj):
        if obj.bucket_seconds >= 3600:
            return f"{obj.bucket_seconds // 3600}h"
        return f"{obj.bucket_seconds // 60}m"
    bucket_seconds_display.short_description = 'Resolution'

    def has_add_permission(self, request):
        return False

    def get_urls(self):
        from django.urls import path
        urls = super().get_urls()
        custom_urls = [
            path('run-rollup/', self.admin_site.admin_view(self.run_rollup_view), name='core_scansummary_rollup'),
        ]
        return custom_urls + urls

    def run_rollup_view(self, request):
        from django.shortcuts import redirect
        from django.contrib import messages
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        try:
            call_command('rollup', stdout=out)
            messages.success(request, f'Rollup completed. {out.getvalue()}')
        except Exception as e:
            messages.error(request, f'Rollup failed: {e}')
        return redirect('admin:core_scansummary_changelist')


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
