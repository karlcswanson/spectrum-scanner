"""Tests for API permission scoping, read-only enforcement, and input parsing.

These cover the security-review fixes: request-aware scanner scoping
(F3), the ReadOnlyIfShareSession guarantee, and the F5 input clamps.
"""

import json
from datetime import timedelta

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.test import override_settings
from django.utils import timezone

from core.models import Access, Band, MonitoredFrequency, Scan, Scanner
from api.auth.pipeline import assign_default_groups
from api.cache import (
    bucket_epoch, cached_or_compute, history_cache_key, register_warm,
    warm_spec, WARM_PREFIX, _warm_sig, compute_timeline, _timeline_grain,
)
from api.permissions import (
    HasScannerAccess, ReadOnlyIfShareSession, get_active_grants,
    get_request_scanner_ids, get_request_max_history_seconds,
    READONLY_MAX_HISTORY_SECONDS,
)
from api.views import _parse_hours, _parse_int


class GetRequestScannerIdsTest(TestCase):
    """Request-aware scoping used by ScanViewSet / at_time / BandViewSet."""

    def setUp(self):
        self.factory = RequestFactory()
        self.s1 = Scanner.objects.create(name="S1")
        self.s2 = Scanner.objects.create(name="S2")

    def _req(self, user, session=None):
        req = self.factory.get("/api/scans/")
        req.user = user
        req.session = session or {}
        return req

    def _scoped_user(self, name):
        # A user WITHOUT the read-all baseline (removed from the default group),
        # so object-level Access scoping applies.
        u = User.objects.create_user(name)
        u.groups.clear()
        return u

    def test_staff_unrestricted(self):
        staff = User.objects.create_user("staff", is_staff=True)
        self.assertIsNone(get_request_scanner_ids(self._req(staff)))

    def test_new_user_gets_read_all_baseline(self):
        # A newly-created user auto-joins the default group (which carries
        # view_scanner), so it reads every scanner. End-to-end: the post_migrate
        # group setup + the post_save enrollment + the has_perm check.
        u = User.objects.create_user("reader")
        self.assertTrue(u.groups.filter(name="Viewers").exists())
        self.assertIsNone(get_request_scanner_ids(self._req(u)))

    def test_user_grant_scopes_when_no_baseline(self):
        u = self._scoped_user("u1")
        Access.objects.create(user=u, scanner=self.s1, permission="r")
        self.assertEqual(get_request_scanner_ids(self._req(u)), {self.s1.id})

    def test_no_baseline_no_grants_sees_nothing(self):
        u = self._scoped_user("nobody")
        self.assertEqual(get_request_scanner_ids(self._req(u)), set())

    def test_share_access_id_scopes_to_grant(self):
        # A share session stays scoped even though demo is in the default group.
        demo = User.objects.create_user("demo_viewer")
        access = Access.objects.create(token="tok-share", scanner=self.s2, permission="r")
        req = self._req(demo, {"access_id": str(access.id), "readonly": True})
        got = get_request_scanner_ids(req)
        self.assertEqual(got, {self.s2.id})
        # The key IDOR guarantee: a share scoped to s2 cannot see s1.
        self.assertNotIn(self.s1.id, got)

    def test_legacy_readonly_share_is_unrestricted(self):
        # Legacy ShareLink: readonly flag, no access_id -> global demo (None).
        demo = User.objects.create_user("demo_viewer")
        self.assertIsNone(get_request_scanner_ids(self._req(demo, {"readonly": True})))

    def test_inactive_share_grant_excluded(self):
        demo = User.objects.create_user("demo_viewer")
        access = Access.objects.create(
            token="tok-dead", scanner=self.s2, permission="r", is_active=False
        )
        req = self._req(demo, {"access_id": str(access.id)})
        # is_active=False -> not found; share session stays scoped -> empty.
        self.assertEqual(get_request_scanner_ids(req), set())


class ReadOnlyIfShareSessionTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.perm = ReadOnlyIfShareSession()

    def test_safe_method_allowed_for_share(self):
        req = self.factory.get("/x")
        req.session = {"readonly": True}
        self.assertTrue(self.perm.has_permission(req, None))

    def test_write_blocked_for_share(self):
        req = self.factory.post("/x")
        req.session = {"readonly": True}
        self.assertFalse(self.perm.has_permission(req, None))

    def test_write_allowed_for_non_share(self):
        req = self.factory.post("/x")
        req.session = {}
        self.assertTrue(self.perm.has_permission(req, None))


class HasScannerAccessReadTest(TestCase):
    """Object permission: reads are request-aware (share sessions work),
    writes still require an rw grant for the user."""

    def setUp(self):
        self.factory = RequestFactory()
        self.perm = HasScannerAccess()
        self.s1 = Scanner.objects.create(name="A")
        self.s2 = Scanner.objects.create(name="B")

    def _req(self, method, user, session):
        req = getattr(self.factory, method)("/x")
        req.user = user
        req.session = session
        return req

    def test_share_session_reads_only_granted_scanner(self):
        demo = User.objects.create_user("demo_viewer")
        access = Access.objects.create(token="t-read", scanner=self.s1, permission="r")
        req = self._req("get", demo, {"access_id": str(access.id), "readonly": True})
        self.assertTrue(self.perm.has_object_permission(req, None, self.s1))
        # Scoped share must not read a scanner outside its grant.
        self.assertFalse(self.perm.has_object_permission(req, None, self.s2))

    def test_staff_reads_any_scanner(self):
        staff = User.objects.create_user("staff-read", is_staff=True)
        req = self._req("get", staff, {})
        self.assertTrue(self.perm.has_object_permission(req, None, self.s1))

    def test_write_requires_rw_grant(self):
        u = User.objects.create_user("writer")
        Access.objects.create(user=u, scanner=self.s1, permission="r")
        req = self._req("post", u, {})
        self.assertFalse(self.perm.has_object_permission(req, None, self.s1))
        Access.objects.create(user=u, scanner=self.s1, permission="rw")
        self.assertTrue(self.perm.has_object_permission(req, None, self.s1))


class CachedOrComputeTest(SimpleTestCase):
    """Single-flight cache wrapper: computes once, then serves from cache."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_miss_then_hit_computes_once(self):
        calls = []

        def compute():
            calls.append(1)
            return {"v": 42}

        data, hit = cached_or_compute("k1", 30, compute)
        self.assertEqual(data, {"v": 42})
        self.assertFalse(hit)

        def _boom():
            raise AssertionError("must not recompute on a hit")

        data2, hit2 = cached_or_compute("k1", 30, _boom)
        self.assertEqual(data2, {"v": 42})
        self.assertTrue(hit2)
        self.assertEqual(len(calls), 1)

    def test_none_is_cached_as_a_hit(self):
        # at_time caches "not found" as None; it must count as a hit, not a
        # perpetual miss that recomputes every request.
        data, hit = cached_or_compute("k-none", 30, lambda: None)
        self.assertIsNone(data)
        self.assertFalse(hit)
        data2, hit2 = cached_or_compute("k-none", 30, lambda: "RECOMPUTED")
        self.assertIsNone(data2)
        self.assertTrue(hit2)

    def test_bucket_epoch_floors_to_window(self):
        t = timezone.now()
        b = bucket_epoch(t, 10)
        self.assertEqual(b % 10, 0)
        self.assertEqual(bucket_epoch(t, 10), bucket_epoch(t, 10))


class HistoryEndpointShareScopeTest(TestCase):
    """End-to-end: a scoped share session can read its granted scanner's
    history (F3 completion) and the response is cached (X-Cache)."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.granted = Scanner.objects.create(name="Granted")
        self.foreign = Scanner.objects.create(name="Foreign")
        self.band = Band.objects.create(
            scanner=self.granted, name="UHF",
            start_hz=470_000_000, stop_hz=473_000_000,
        )
        Scan.objects.create(
            scanner=self.granted, band=self.band, timestamp=timezone.now(),
            hz_lo=470_000_000, hz_hi=473_000_000, step_hz=1_000_000.0,
            power=[1.0, 2.0, 3.0], metadata={},
        )
        self.demo = User.objects.create_user("demo_viewer")
        self.access = Access.objects.create(
            token="share-tok", scanner=self.granted, permission="r",
        )

    def _share_client(self):
        client = Client()
        client.force_login(self.demo)
        session = client.session
        session["access_id"] = str(self.access.id)
        session["readonly"] = True
        session.save()
        return client

    def test_share_reads_granted_history_with_cache(self):
        client = self._share_client()
        r1 = client.get(f"/api/scanners/{self.granted.id}/history/")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1["X-Cache"], "MISS")
        self.assertEqual(len(r1.json()), 1)

        r2 = client.get(f"/api/scanners/{self.granted.id}/history/")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2["X-Cache"], "HIT")

    def test_share_cannot_read_foreign_history(self):
        client = self._share_client()
        r = client.get(f"/api/scanners/{self.foreign.id}/history/")
        self.assertEqual(r.status_code, 404)


class ReadOnlyHistoryCapTest(TestCase):
    """Read-only share sessions are bounded to the recent live window; full
    logins keep unlimited history."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.factory = RequestFactory()
        self.scanner = Scanner.objects.create(name="Capped")
        self.band = Band.objects.create(
            scanner=self.scanner, name="UHF",
            start_hz=470_000_000, stop_hz=473_000_000,
        )
        now = timezone.now()
        # One scan inside the 10-min window, one well outside it.
        self.recent = Scan.objects.create(
            scanner=self.scanner, band=self.band, timestamp=now - timedelta(minutes=1),
            hz_lo=470_000_000, hz_hi=473_000_000, step_hz=1_000_000.0,
            power=[1.0, 2.0, 3.0], metadata={},
        )
        self.old = Scan.objects.create(
            scanner=self.scanner, band=self.band, timestamp=now - timedelta(minutes=30),
            hz_lo=470_000_000, hz_hi=473_000_000, step_hz=1_000_000.0,
            power=[4.0, 5.0, 6.0], metadata={},
        )
        self.demo = User.objects.create_user("demo_viewer")
        self.access = Access.objects.create(
            token="cap-tok", scanner=self.scanner, permission="r",
        )
        self.staff = User.objects.create_user("cap-staff", is_staff=True)

    def _req(self, session):
        req = self.factory.get("/x")
        req.session = session
        return req

    def test_helper_caps_readonly_only(self):
        self.assertEqual(
            get_request_max_history_seconds(self._req({"readonly": True})),
            READONLY_MAX_HISTORY_SECONDS,
        )
        self.assertIsNone(get_request_max_history_seconds(self._req({})))
        self.assertIsNone(get_request_max_history_seconds(self._req({"access_id": "x"})))

    def _share_client(self):
        client = Client()
        client.force_login(self.demo)
        session = client.session
        session["access_id"] = str(self.access.id)
        session["readonly"] = True
        session.save()
        return client

    def test_share_history_excludes_data_older_than_window(self):
        # Even asking for hours=24, a read-only share only sees the last 10 min.
        client = self._share_client()
        r = client.get(f"/api/scanners/{self.scanner.id}/history/?hours=24")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 1)  # only the recent scan

    def test_full_login_sees_full_history(self):
        client = Client()
        client.force_login(self.staff)
        r = client.get(f"/api/scanners/{self.scanner.id}/history/?hours=24")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)  # both scans

    def test_share_at_time_rejects_old_timestamp(self):
        client = self._share_client()
        old = (timezone.now() - timedelta(minutes=30)).isoformat()
        r = client.get(f"/api/scans/at_time/?scanner={self.scanner.id}&time={old}")
        self.assertEqual(r.status_code, 404)


class TimelineBoundingTest(TestCase):
    """Wide scrubber windows are bucketed so the timeline can't return 100k+
    rows (which locked up the server); short windows stay per-scan."""

    def setUp(self):
        self.scanner = Scanner.objects.create(name="TL")
        self.band = Band.objects.create(
            scanner=self.scanner, name="UHF",
            start_hz=470_000_000, stop_hz=473_000_000,
        )

    def _scan(self, ts):
        Scan.objects.create(
            scanner=self.scanner, band=self.band, timestamp=ts,
            hz_lo=470_000_000, hz_hi=473_000_000, step_hz=1_000_000.0,
            power=[1.0], metadata={},
        )

    def test_grain_selection(self):
        now = timezone.now()
        self.assertIsNone(_timeline_grain(now - timedelta(minutes=30), now))
        self.assertEqual(_timeline_grain(now - timedelta(hours=24), now), 'minute')
        self.assertEqual(_timeline_grain(now - timedelta(days=30), now), 'hour')
        self.assertEqual(_timeline_grain(now - timedelta(days=200), now), 'day')

    def test_wide_window_collapses_dense_scans(self):
        now = timezone.now()
        base = (now - timedelta(hours=2)).replace(second=0, microsecond=0)  # 2h -> minute grain
        for i in range(12):  # 12 scans, 5s apart, all within one minute
            self._scan(base + timedelta(seconds=i * 5))
        entries = compute_timeline(self.scanner.id, "UHF", base - timedelta(seconds=1), now)
        self.assertEqual(len(entries), 1)  # collapsed to a single bucket marker
        self.assertEqual(entries[0]['band__name'], "UHF")
        self.assertIn('id', entries[0])

    def test_short_window_is_per_scan(self):
        now = timezone.now()
        base = now - timedelta(minutes=10)  # <= 1h -> per-scan
        for i in range(20):
            self._scan(base + timedelta(seconds=i * 30))
        entries = compute_timeline(self.scanner.id, "UHF", base - timedelta(seconds=1), now)
        self.assertEqual(len(entries), 20)  # every scan
        ts = [e['timestamp'] for e in entries]
        self.assertEqual(ts, sorted(ts))


class WarmRegistryTest(SimpleTestCase):
    """Demand-driven warm markers: registration writes a retrievable spec."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_register_warm_writes_marker(self):
        spec = {
            "kind": "history", "scanner_id": "abc", "band": "UHF",
            "hours": 24.0, "limit": 1000, "decimated": True,
        }
        register_warm(spec)
        self.assertEqual(cache.get(f"{WARM_PREFIX}{_warm_sig(spec)}"), spec)

    def test_identical_requests_share_one_marker(self):
        base = {
            "kind": "timeline", "scanner_id": "abc", "band": None, "hours": 24.0,
        }
        register_warm(dict(base))
        register_warm(dict(base))
        self.assertEqual(_warm_sig(base), _warm_sig(dict(base)))


class WarmNoDriftTest(TestCase):
    """The warmer must fill the *exact* key a real request reads — otherwise
    warming is a silent no-op. Proven end-to-end: warm a spec, then the
    matching endpoint request is a HIT with no client-triggered compute."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.scanner = Scanner.objects.create(name="Warmed")
        self.band = Band.objects.create(
            scanner=self.scanner, name="UHF",
            start_hz=470_000_000, stop_hz=473_000_000,
        )
        Scan.objects.create(
            scanner=self.scanner, band=self.band, timestamp=timezone.now(),
            hz_lo=470_000_000, hz_hi=473_000_000, step_hz=1_000_000.0,
            power=[1.0, 2.0, 3.0], metadata={},
        )
        self.staff = User.objects.create_user("warm-staff", is_staff=True)

    def test_warm_prefills_key_endpoint_reads(self):
        # The spec matching the endpoint's default history request.
        spec = {
            "kind": "history", "scanner_id": str(self.scanner.id), "band": None,
            "hours": 24.0, "limit": 1000, "decimated": False,
        }
        key = warm_spec(spec)
        # The warmed key is populated straight from the warmer (no request yet).
        self.assertIsNotNone(cache.get(key))
        self.assertEqual(
            key, history_cache_key(self.scanner.id, None, "h24.0", 1000, False)
        )

        # A real request with the same params must hit that pre-filled key.
        client = Client()
        client.force_login(self.staff)
        r = client.get(f"/api/scanners/{self.scanner.id}/history/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Cache"], "HIT")
        self.assertEqual(len(r.json()), 1)


class MonitoredFrequencyCRUDTest(TestCase):
    """CRUD + permissions for monitored frequencies (existing perm model)."""

    def setUp(self):
        self.s1 = Scanner.objects.create(name="S1")
        self.s2 = Scanner.objects.create(name="S2")
        self.staff = User.objects.create_user("mf-staff", is_staff=True)
        self.rw = User.objects.create_user("mf-rw")
        Access.objects.create(user=self.rw, scanner=self.s1, permission="rw")
        self.ro = User.objects.create_user("mf-ro")
        Access.objects.create(user=self.ro, scanner=self.s1, permission="r")

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _post(self, client, scanner):
        return client.post(
            '/api/monitored-frequencies/',
            data=json.dumps({'frequency_hz': 517000000, 'name': 'Vox 1', 'scanner': str(scanner.id)}),
            content_type='application/json',
        )

    def _freq_on(self, scanner, name='F'):
        f = MonitoredFrequency.objects.create(frequency_hz=517000000, name=name)
        f.scanners.add(scanner)
        return f

    def test_rw_user_creates_scoped_freq(self):
        r = self._post(self._client(self.rw), self.s1)
        self.assertEqual(r.status_code, 201)
        freq = MonitoredFrequency.objects.get(name='Vox 1')
        self.assertIn(self.s1, list(freq.scanners.all()))

    def test_readonly_grant_cannot_create(self):
        self.assertEqual(self._post(self._client(self.ro), self.s1).status_code, 403)

    def test_rw_cannot_create_for_other_scanner(self):
        self.assertEqual(self._post(self._client(self.rw), self.s2).status_code, 403)

    def test_rw_updates_own_freq(self):
        freq = self._freq_on(self.s1)
        r = self._client(self.rw).patch(
            f'/api/monitored-frequencies/{freq.id}/',
            data=json.dumps({'name': 'Vox 2'}), content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        freq.refresh_from_db()
        self.assertEqual(freq.name, 'Vox 2')

    def test_nonstaff_cannot_edit_global_freq(self):
        gf = MonitoredFrequency.objects.create(frequency_hz=500000000, name='Global')  # no scope
        r = self._client(self.rw).patch(
            f'/api/monitored-frequencies/{gf.id}/',
            data=json.dumps({'name': 'Hacked'}), content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)

    def test_staff_edits_global_freq(self):
        gf = MonitoredFrequency.objects.create(frequency_hz=500000000, name='Global')
        r = self._client(self.staff).patch(
            f'/api/monitored-frequencies/{gf.id}/',
            data=json.dumps({'name': 'Updated'}), content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)

    def test_share_session_cannot_write(self):
        demo = User.objects.create_user("demo_viewer")
        access = Access.objects.create(token="mf-share", scanner=self.s1, permission="r")
        client = Client()
        client.force_login(demo)
        sess = client.session
        sess['access_id'] = str(access.id)
        sess['readonly'] = True
        sess.save()
        freq = self._freq_on(self.s1)
        r = client.patch(
            f'/api/monitored-frequencies/{freq.id}/',
            data=json.dumps({'name': 'X'}), content_type='application/json',
        )
        self.assertEqual(r.status_code, 403)

    def test_rw_deletes_own_freq(self):
        freq = self._freq_on(self.s1)
        r = self._client(self.rw).delete(f'/api/monitored-frequencies/{freq.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(MonitoredFrequency.objects.filter(id=freq.id).exists())


class ParseHelpersTest(SimpleTestCase):
    def test_parse_hours_clamps_and_defaults(self):
        self.assertEqual(_parse_hours("abc"), 24.0)      # garbage -> default
        self.assertEqual(_parse_hours(None), 24.0)
        self.assertEqual(_parse_hours("1e18"), 8760.0)   # clamp to max
        self.assertEqual(_parse_hours("-5"), 0.0)        # clamp to min
        self.assertEqual(_parse_hours("5"), 5.0)

    def test_parse_int_clamps_and_defaults(self):
        self.assertEqual(_parse_int("abc", 100, minimum=1, maximum=5000), 100)
        self.assertEqual(_parse_int(None, 100, minimum=1, maximum=5000), 100)
        self.assertEqual(_parse_int("99999", 100, minimum=1, maximum=5000), 5000)
        self.assertEqual(_parse_int("0", 100, minimum=1, maximum=5000), 1)
        self.assertEqual(_parse_int("50", 100, minimum=1, maximum=5000), 50)


class GetActiveGrantsGroupTest(TestCase):
    """The group-principal path in get_active_grants: a grant made to a Django
    auth Group is inherited by every member (how auto-created SSO users pick up
    baseline Access)."""

    def setUp(self):
        self.scanner = Scanner.objects.create(name="S1")
        self.group = Group.objects.create(name="sso-users")

    def test_member_sees_group_grant(self):
        member = User.objects.create_user("member")
        member.groups.add(self.group)
        grant = Access.objects.create(group=self.group, scanner=self.scanner, permission="r")
        self.assertIn(grant, get_active_grants(member))

    def test_non_member_does_not_see_group_grant(self):
        outsider = User.objects.create_user("outsider")
        Access.objects.create(group=self.group, scanner=self.scanner, permission="r")
        self.assertEqual(list(get_active_grants(outsider)), [])

    def test_direct_and_group_grants_union(self):
        member = User.objects.create_user("member")
        member.groups.add(self.group)
        s2 = Scanner.objects.create(name="S2")
        direct = Access.objects.create(user=member, scanner=s2, permission="rw")
        via_group = Access.objects.create(group=self.group, scanner=self.scanner, permission="r")
        self.assertCountEqual(get_active_grants(member), [direct, via_group])

    def test_inactive_group_grant_excluded(self):
        member = User.objects.create_user("member")
        member.groups.add(self.group)
        Access.objects.create(
            group=self.group, scanner=self.scanner, permission="r", is_active=False,
        )
        self.assertEqual(list(get_active_grants(member)), [])

    def test_expired_group_grant_excluded(self):
        member = User.objects.create_user("member")
        member.groups.add(self.group)
        Access.objects.create(
            group=self.group, scanner=self.scanner, permission="r",
            expires_at=timezone.now() - timedelta(hours=1),
        )
        self.assertEqual(list(get_active_grants(member)), [])

    def test_anonymous_user_gets_none(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertEqual(list(get_active_grants(AnonymousUser())), [])


class AccessPrincipalConstraintTest(TestCase):
    """Exactly-one-of user/group/token must hold at the DB level."""

    def setUp(self):
        self.scanner = Scanner.objects.create(name="S1")
        self.group = Group.objects.create(name="sso-users")
        self.user = User.objects.create_user("u1")

    def test_group_only_is_allowed(self):
        Access.objects.create(group=self.group, scanner=self.scanner, permission="r")

    def test_user_plus_group_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Access.objects.create(
                    user=self.user, group=self.group,
                    scanner=self.scanner, permission="r",
                )

    def test_no_principal_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Access.objects.create(scanner=self.scanner, permission="r")


# DEFAULT_USER_GROUP="" disables the baseline auto-enroll signal so these tests
# exercise the SSO pipeline step in isolation (otherwise every created user is in
# the Viewers group and "no groups" assertions can't hold).
@override_settings(SSO_DEFAULT_GROUPS=["sso-users"], DEFAULT_USER_GROUP="")
class AssignDefaultGroupsTest(TestCase):
    """The SSO pipeline step that drops newly-created users into the local
    baseline group(s)."""

    def test_new_user_added_to_default_groups(self):
        user = User.objects.create_user("new")
        assign_default_groups(backend=None, user=user, response={}, is_new=True)
        self.assertTrue(user.groups.filter(name="sso-users").exists())
        # Group is auto-created if missing.
        self.assertTrue(Group.objects.filter(name="sso-users").exists())

    def test_existing_user_not_touched(self):
        user = User.objects.create_user("returning")
        assign_default_groups(backend=None, user=user, response={}, is_new=False)
        self.assertFalse(user.groups.exists())

    @override_settings(SSO_DEFAULT_GROUPS=[])
    def test_no_default_groups_is_noop(self):
        user = User.objects.create_user("new")
        assign_default_groups(backend=None, user=user, response={}, is_new=True)
        self.assertFalse(user.groups.exists())
