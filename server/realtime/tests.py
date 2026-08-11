"""Tests for dynsec role computation — the broker-side mirror of the REST scope.

Regression cover for the bug where legacy ShareLink demo sessions (unrestricted
REST read, no access_id) were granted no MQTT role and so got no live stream.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Access, Scanner
from realtime.dynsec import compute_desired_roles


class ComputeDesiredRolesTest(TestCase):
    def setUp(self):
        self.s1 = Scanner.objects.create(name="S1")
        self.s2 = Scanner.objects.create(name="S2")

    def _scoped_user(self, name):
        # A user WITHOUT the read-all baseline (removed from the default Viewers
        # group), so only the Access-grant -> role mapping applies.
        u = User.objects.create_user(name)
        u.groups.clear()
        return u

    def test_staff_gets_all_scanners(self):
        staff = User.objects.create_user("staff", is_staff=True)
        self.assertEqual(compute_desired_roles(staff), {"staff-all-scanners"})

    def test_legacy_global_share_gets_read_all(self):
        # The bug: this used to return an empty set -> no MQTT subscribe -> no
        # live stream, even though REST read was unrestricted.
        demo = User.objects.create_user("demo_viewer")
        self.assertEqual(
            compute_desired_roles(demo, access_id=None, global_read=True),
            {"read-all-scanners"},
        )

    def test_view_scanner_baseline_gets_read_all(self):
        # A real login in the default Viewers group (view_scanner) subscribes to
        # every scanner — the broker mirror of the REST read-all baseline.
        u = User.objects.create_user("reader")
        self.assertTrue(u.groups.filter(name="Viewers").exists())
        self.assertEqual(compute_desired_roles(u), {"read-all-scanners"})

    def test_user_grant_gets_scanner_read_role(self):
        u = self._scoped_user("u1")
        Access.objects.create(user=u, scanner=self.s1, permission="r")
        self.assertEqual(compute_desired_roles(u), {f"scanner-{self.s1.id}-read"})

    def test_scoped_share_access_id_gets_only_its_scanner(self):
        # Even though demo is in the default group, a share session (access_id)
        # stays scoped to its granted scanner — not read-all.
        demo = User.objects.create_user("demo_viewer")
        access = Access.objects.create(token="tok", scanner=self.s2, permission="r")
        roles = compute_desired_roles(demo, access_id=str(access.id))
        self.assertEqual(roles, {f"scanner-{self.s2.id}-read"})
        # IDOR guarantee: a scope for s2 grants no role for s1.
        self.assertNotIn(f"scanner-{self.s1.id}-read", roles)

    def test_rw_grant_gets_rw_role(self):
        u = self._scoped_user("writer")
        Access.objects.create(user=u, scanner=self.s1, permission="rw")
        self.assertEqual(compute_desired_roles(u), {f"scanner-{self.s1.id}-rw"})

    def test_group_grant_gives_member_scanner_role(self):
        # A grant to a Django auth Group is inherited by every member (the model
        # SSO users land in). The broker scope must mirror that.
        from django.contrib.auth.models import Group
        grp = Group.objects.create(name="sso-users")
        member = self._scoped_user("member")
        member.groups.add(grp)
        Access.objects.create(group=grp, scanner=self.s1, permission="r")
        self.assertEqual(compute_desired_roles(member), {f"scanner-{self.s1.id}-read"})

    def test_group_grant_not_seen_by_non_member(self):
        # IDOR guarantee for the group principal: a user not in the group gets
        # none of the group's roles.
        from django.contrib.auth.models import Group
        grp = Group.objects.create(name="sso-users")
        Access.objects.create(group=grp, scanner=self.s1, permission="rw")
        outsider = self._scoped_user("outsider")
        self.assertEqual(compute_desired_roles(outsider), set())

    def test_plain_user_gets_nothing(self):
        u = self._scoped_user("nobody")
        self.assertEqual(compute_desired_roles(u), set())
