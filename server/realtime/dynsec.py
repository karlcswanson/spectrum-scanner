"""Mosquitto Dynamic Security plugin client.

Manages MQTT clients, roles, and ACLs via the $CONTROL API topic.
Uses paho-mqtt to publish commands and receive responses synchronously.
"""

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt
from django.conf import settings

from api.permissions import get_active_grants

logger = logging.getLogger(__name__)

CONTROL_TOPIC = '$CONTROL/dynamic-security/v1'
RESPONSE_TOPIC = '$CONTROL/dynamic-security/v1/response'


class DynSecClient:
    """Synchronous client for Mosquitto's Dynamic Security plugin."""

    def __init__(self):
        import uuid
        self._client = mqtt.Client(client_id=f'spectrum-dynsec-{uuid.uuid4().hex[:8]}')
        self._client.username_pw_set(
            settings.MQTT_DYNSEC_USERNAME,
            settings.MQTT_DYNSEC_PASSWORD,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._response = None
        self._response_event = threading.Event()
        self._connected = threading.Event()
        self._connect_error = None
        self._lock = threading.Lock()
        self._loop_started = False

    def _connect(self):
        if self._connected.is_set():
            return
        # If a previous attempt failed with auth error, don't retry
        if self._connect_error is not None:
            raise RuntimeError(f'DynSec admin connection previously failed: {self._connect_error}')
        self._client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT)
        if not self._loop_started:
            self._client.loop_start()
            self._loop_started = True
        if not self._connected.wait(timeout=5.0):
            # Stop the loop so we don't keep retrying with bad credentials
            self._client.loop_stop()
            self._loop_started = False
            if self._connect_error:
                raise RuntimeError(f'DynSec admin auth failed: {self._connect_error}')
            raise RuntimeError('Failed to connect to MQTT broker for dynsec admin')

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(RESPONSE_TOPIC)
            self._connect_error = None
            self._connected.set()
        else:
            self._connect_error = reason_code
            logger.error(f'DynSec admin connect failed: {reason_code}')

    def _on_message(self, client, userdata, msg):
        if msg.topic == RESPONSE_TOPIC:
            try:
                self._response = json.loads(msg.payload.decode())
            except json.JSONDecodeError:
                self._response = {'error': 'invalid JSON response'}
            self._response_event.set()

    def _send_command(self, command: dict, timeout: float = 5.0) -> dict:
        """Publish a command and wait for the response."""
        with self._lock:
            self._connect()
            self._response = None
            self._response_event.clear()
            payload = json.dumps({'commands': [command]})
            self._client.publish(CONTROL_TOPIC, payload)
            if not self._response_event.wait(timeout=timeout):
                raise TimeoutError(f'DynSec command timed out: {command.get("command")}')
            resp = self._response
            if resp and 'responses' in resp:
                r = resp['responses'][0]
                if r.get('error'):
                    logger.debug(f'DynSec {command.get("command")}: {r["error"]}')
                return r
            return resp or {}

    def close(self):
        if self._loop_started:
            self._client.loop_stop()
            self._loop_started = False
        self._client.disconnect()
        self._connected.clear()
        self._connect_error = None

    # ── Client operations ──

    def create_client(self, username: str, password: str, roles: list[dict] | None = None,
                      update_password: bool = False):
        cmd = {
            'command': 'createClient',
            'username': username,
            'password': password,
        }
        if roles:
            cmd['roles'] = roles
        resp = self._send_command(cmd)
        if resp.get('error') == 'Client already exists':
            # Only update password when explicitly requested (token regeneration).
            # setClientPassword disconnects existing sessions.
            if update_password:
                self.set_client_password(username, password)
            if roles:
                for role in roles:
                    self.add_client_role(username, role['rolename'], role.get('priority', -1))
        return resp

    def delete_client(self, username: str):
        return self._send_command({
            'command': 'deleteClient',
            'username': username,
        })

    def set_client_password(self, username: str, password: str):
        return self._send_command({
            'command': 'setClientPassword',
            'username': username,
            'password': password,
        })

    def add_client_role(self, username: str, rolename: str, priority: int = -1):
        return self._send_command({
            'command': 'addClientRole',
            'username': username,
            'rolename': rolename,
            'priority': priority,
        })

    def remove_client_role(self, username: str, rolename: str):
        return self._send_command({
            'command': 'removeClientRole',
            'username': username,
            'rolename': rolename,
        })

    def get_client(self, username: str) -> dict:
        resp = self._send_command({
            'command': 'getClient',
            'username': username,
        })
        return resp.get('data', {})

    def list_clients(self) -> list:
        resp = self._send_command({
            'command': 'listClients',
        })
        return resp.get('data', {}).get('clients', [])

    # ── Role operations ──

    def create_role(self, rolename: str, acls: list[dict] | None = None):
        cmd = {
            'command': 'createRole',
            'rolename': rolename,
        }
        if acls:
            cmd['acls'] = acls
        resp = self._send_command(cmd)
        if resp.get('error') == 'Role already exists':
            # Role exists — leave it. Deleting would strip the role from
            # all assigned clients, disconnecting them. ACL updates are
            # handled by replace_role() for the --force path.
            return resp
        return resp

    def replace_role(self, rolename: str, acls: list[dict] | None = None):
        """Delete and recreate a role to update its ACLs.

        WARNING: this removes the role from all assigned clients.
        Callers must re-assign the role afterwards.
        """
        self.delete_role(rolename)
        cmd = {'command': 'createRole', 'rolename': rolename}
        if acls:
            cmd['acls'] = acls
        return self._send_command(cmd)

    def delete_role(self, rolename: str):
        return self._send_command({
            'command': 'deleteRole',
            'rolename': rolename,
        })

    def get_role(self, rolename: str) -> dict:
        resp = self._send_command({
            'command': 'getRole',
            'rolename': rolename,
        })
        return resp.get('data', {})

    def list_roles(self) -> list:
        resp = self._send_command({
            'command': 'listRoles',
        })
        return resp.get('data', {}).get('roles', [])


# ── Role definitions ──

def _bridge_role_acls() -> list[dict]:
    """ACLs for the bridge-service role."""
    return [
        {'acltype': 'subscribePattern', 'topic': 'spectrum/scanners/+/scan', 'allow': True},
        {'acltype': 'subscribePattern', 'topic': 'spectrum/scanners/+/status', 'allow': True},
        {'acltype': 'subscribePattern', 'topic': 'spectrum/scanners/+/config', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': 'spectrum/scanners/#', 'allow': True},
        {'acltype': 'publishClientSend', 'topic': 'spectrum/scanners/+/timeline', 'allow': True},
        {'acltype': 'publishClientSend', 'topic': 'spectrum/commands/#', 'allow': True},
    ]


def _monitor_role_acls() -> list[dict]:
    """ACLs for a read-only metrics collector (Telegraf -> VictoriaMetrics).

    Broker $SYS stats only. BOTH acls are required: subscribePattern lets it
    subscribe, publishClientReceive lets messages actually be delivered (subscribe
    alone leaves it subscribed but with nothing arriving). No spectrum/# access,
    no publish.
    """
    return [
        {'acltype': 'subscribePattern', 'topic': '$SYS/#', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': '$SYS/#', 'allow': True},
    ]


def _staff_role_acls() -> list[dict]:
    """ACLs for the staff-all-scanners role."""
    return [
        {'acltype': 'subscribePattern', 'topic': 'spectrum/scanners/#', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': 'spectrum/scanners/#', 'allow': True},
        {'acltype': 'publishClientSend', 'topic': 'spectrum/commands/#', 'allow': True},
    ]


def _read_all_scanners_role_acls() -> list[dict]:
    """ACLs for the global read-only role used by legacy demo share links.

    Subscribe/receive every scanner (so the live scan stream reaches the demo
    viewer) but no command publish — the broker mirror of the REST "unrestricted
    read" a legacy ShareLink session gets. Scoped Access shares use the
    per-scanner read role instead.
    """
    return [
        {'acltype': 'subscribePattern', 'topic': 'spectrum/scanners/#', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': 'spectrum/scanners/#', 'allow': True},
    ]


def scanner_device_role_acls(scanner_id: str) -> list[dict]:
    """ACLs for a scanner device role."""
    return [
        {'acltype': 'publishClientSend', 'topic': f'spectrum/scanners/{scanner_id}/scan', 'allow': True},
        {'acltype': 'publishClientSend', 'topic': f'spectrum/scanners/{scanner_id}/status', 'allow': True},
        {'acltype': 'publishClientSend', 'topic': f'spectrum/scanners/{scanner_id}/config', 'allow': True},
        {'acltype': 'subscribePattern', 'topic': f'spectrum/commands/{scanner_id}/#', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': f'spectrum/commands/{scanner_id}/#', 'allow': True},
    ]


def scanner_read_role_acls(scanner_id: str) -> list[dict]:
    """ACLs for user read access to a scanner."""
    return [
        {'acltype': 'subscribePattern', 'topic': f'spectrum/scanners/{scanner_id}/+', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': f'spectrum/scanners/{scanner_id}/#', 'allow': True},
    ]


def scanner_rw_role_acls(scanner_id: str) -> list[dict]:
    """ACLs for user read/write access to a scanner."""
    return [
        {'acltype': 'subscribePattern', 'topic': f'spectrum/scanners/{scanner_id}/+', 'allow': True},
        {'acltype': 'publishClientReceive', 'topic': f'spectrum/scanners/{scanner_id}/#', 'allow': True},
        {'acltype': 'publishClientSend', 'topic': f'spectrum/commands/{scanner_id}/+', 'allow': True},
    ]


# ── Provisioning helpers ──

# Role name prefixes managed by dynsec sync (used for diffing)
MANAGED_PREFIXES = ('scanner-', 'staff-all-scanners', 'read-all-scanners', 'bridge-service')


def ensure_static_roles(dynsec: DynSecClient):
    """Create static roles (bridge-service, staff-all-scanners, read-all-scanners)."""
    dynsec.create_role('bridge-service', _bridge_role_acls())
    dynsec.create_role('staff-all-scanners', _staff_role_acls())
    dynsec.create_role('read-all-scanners', _read_all_scanners_role_acls())


def ensure_bridge_client(dynsec: DynSecClient):
    """Create the bridge service client."""
    dynsec.create_client(
        settings.MQTT_BRIDGE_USERNAME,
        settings.MQTT_BRIDGE_PASSWORD,
        roles=[{'rolename': 'bridge-service', 'priority': -1}],
    )


def ensure_monitor_client(dynsec: DynSecClient):
    """Create the read-only $SYS metrics client — only when MQTT_MONITOR_PASSWORD
    is set (i.e. the observability/ metrics worker is in use). No-op otherwise, so
    deployments without metrics don't get a dangling client."""
    if not settings.MQTT_MONITOR_PASSWORD:
        return
    dynsec.create_role('monitor', _monitor_role_acls())
    dynsec.create_client(
        settings.MQTT_MONITOR_USERNAME,
        settings.MQTT_MONITOR_PASSWORD,
        roles=[{'rolename': 'monitor', 'priority': -1}],
    )


def ensure_scanner_roles(dynsec: DynSecClient, scanner, update_password: bool = False):
    """Create per-scanner roles and device client.

    If the scanner is disabled, deletes its dynsec client (preventing
    connections) but keeps the roles so user role assignments remain valid.
    """
    sid = str(scanner.id)

    # Always ensure roles exist (users may still reference them)
    dynsec.create_role(f'scanner-device-{sid}', scanner_device_role_acls(sid))
    dynsec.create_role(f'scanner-{sid}-read', scanner_read_role_acls(sid))
    dynsec.create_role(f'scanner-{sid}-rw', scanner_rw_role_acls(sid))

    if scanner.enabled:
        # Scanner device client
        dynsec.create_client(
            sid,
            scanner.auth_token,
            roles=[{'rolename': f'scanner-device-{sid}', 'priority': -1}],
            update_password=update_password,
        )
    else:
        # Disabled scanner — remove its MQTT client so it can't connect
        dynsec.delete_client(sid)


def delete_scanner_roles(dynsec: DynSecClient, scanner_id: str):
    """Delete per-scanner roles and device client."""
    dynsec.delete_client(scanner_id)
    dynsec.delete_role(f'scanner-device-{scanner_id}')
    dynsec.delete_role(f'scanner-{scanner_id}-read')
    dynsec.delete_role(f'scanner-{scanner_id}-rw')


def _resolve_scanner_ids(grant) -> set[str]:
    """Resolve a grant to a set of scanner ID strings."""
    if grant.scanner_id:
        return {str(grant.scanner_id)}
    if grant.scanner_group_id:
        from core.models import Scanner
        return set(
            Scanner.objects.filter(
                scanner_groups__id=grant.scanner_group_id,
            ).values_list('id', flat=True).distinct()
        )
    return set()


def sync_user_roles(user, dynsec: DynSecClient, access_id: str | None = None,
                    global_read: bool = False):
    """Synchronise a user's dynsec roles with their Django Access grants.

    Args:
        user: Django User instance.
        dynsec: DynSecClient instance.
        access_id: Optional Access grant UUID (for share-link / token-based sessions).
        global_read: Grant the global read-only role (legacy ShareLink demo
            session, which has unrestricted REST read and no access_id).
    """
    from core.models import UserMQTTCredentials

    creds, created = UserMQTTCredentials.objects.get_or_create(user=user)
    mqtt_username = str(creds.mqtt_id)

    # Ensure client exists (only set password on first creation)
    dynsec.create_client(mqtt_username, creds.auth_token, update_password=created)

    # Inactive users get all managed roles removed
    if not user.is_active:
        client_data = dynsec.get_client(mqtt_username)
        for r in client_data.get('roles', []):
            rn = r['rolename']
            if any(rn.startswith(p) for p in MANAGED_PREFIXES):
                dynsec.remove_client_role(mqtt_username, rn)
        return

    # Get current roles from dynsec
    client_data = dynsec.get_client(mqtt_username)
    current_roles = {r['rolename'] for r in client_data.get('roles', [])}

    desired_roles = compute_desired_roles(user, access_id=access_id, global_read=global_read)

    # Only touch managed roles when diffing
    managed_current = {r for r in current_roles if any(r.startswith(p) for p in MANAGED_PREFIXES)}

    to_add = desired_roles - managed_current
    to_remove = managed_current - desired_roles

    for r in to_add:
        dynsec.add_client_role(mqtt_username, r)
    for r in to_remove:
        dynsec.remove_client_role(mqtt_username, r)


def compute_desired_roles(user, access_id: str | None = None,
                          global_read: bool = False) -> set:
    """The dynsec roles a principal should hold — the broker-side mirror of the
    REST scope in ``api.permissions.get_request_scanner_ids``.

    - staff -> all scanners (with command publish)
    - legacy ShareLink global demo (readonly, no access_id) -> global read-only
    - otherwise -> the user's active grants, plus the share session's access_id
      grant if present (scoped per-scanner read/rw)
    """
    if user.is_staff:
        return {'staff-all-scanners'}
    if global_read:
        # Legacy ShareLink global demo: unrestricted read, no command publish.
        return {'read-all-scanners'}

    desired_roles = set()
    # Read-all baseline: a real login (not a share/token session) holding the
    # view_scanner permission (the Viewers group) subscribes to every scanner —
    # the broker-side mirror of the REST read-all baseline. Share sessions
    # (access_id set) stay scoped, so they don't get this.
    if access_id is None and user.has_perm('core.view_scanner'):
        desired_roles.add('read-all-scanners')
    for grant in get_active_grants(user):
        _add_grant_roles(grant, desired_roles)

    if access_id:
        from core.models import Access
        try:
            grant = Access.objects.get(pk=access_id, is_active=True)
            if grant.is_valid():
                _add_grant_roles(grant, desired_roles)
        except Access.DoesNotExist:
            pass

    return desired_roles


def _add_grant_roles(grant, desired_roles: set):
    """Add the appropriate scanner roles for a single Access grant."""
    scanner_ids = _resolve_scanner_ids(grant)
    for sid in scanner_ids:
        sid = str(sid)
        if grant.permission == 'rw':
            desired_roles.add(f'scanner-{sid}-rw')
            desired_roles.discard(f'scanner-{sid}-read')
        else:
            if f'scanner-{sid}-rw' not in desired_roles:
                desired_roles.add(f'scanner-{sid}-read')


def full_sync(dynsec: DynSecClient):
    """Idempotent full sync of dynsec state with Django DB."""
    from core.models import Scanner, UserMQTTCredentials

    ensure_static_roles(dynsec)
    ensure_bridge_client(dynsec)
    ensure_monitor_client(dynsec)
    for scanner in Scanner.objects.all():
        ensure_scanner_roles(dynsec, scanner)
    for creds in UserMQTTCredentials.objects.select_related('user').all():
        sync_user_roles(creds.user, dynsec)


# ── Module-level singleton ──

_dynsec_client = None
_dynsec_lock = threading.Lock()


def get_dynsec_client() -> DynSecClient:
    """Get or create a module-level DynSecClient singleton."""
    global _dynsec_client
    with _dynsec_lock:
        if _dynsec_client is None:
            _dynsec_client = DynSecClient()
        return _dynsec_client
