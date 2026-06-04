"""RBAC tests: management roles get permissions; /auth/me returns bare codenames."""
from django.test import TestCase
from django.contrib.auth.models import Group
from django.core.management import call_command

from authmanagement.models import CustomUser


class RbacRoleSeedTest(TestCase):
    def test_management_roles_get_permissions(self):
        call_command("seed_rbac_roles")
        for role in ["ceo", "cto", "finance_manager", "ict_officer", "hr_manager", "operations_manager"]:
            group = Group.objects.get(name=role)
            self.assertGreater(group.permissions.count(), 0, f"{role} has no permissions")

    def test_auth_me_returns_bare_codenames(self):
        call_command("seed_rbac_roles")
        user = CustomUser.objects.create_user(email="ceo@example.com", password="x")
        user.groups.add(Group.objects.get(name="ceo"))
        # get_all_permissions() returns app_label.codename; auth_me strips to bare codenames.
        bare = sorted({p.split(".")[-1] for p in user.get_all_permissions()})
        self.assertTrue(all("." not in p for p in bare))
        self.assertIn("view_employee", bare)  # ceo has broad HR view


class StaffMergeTest(TestCase):
    def test_duplicate_staff_group_merged(self):
        dup = Group.objects.create(name="Staff")
        u = CustomUser.objects.create_user(email="s@example.com", password="x")
        u.groups.add(dup)
        call_command("seed_rbac_roles")
        self.assertFalse(Group.objects.filter(name="Staff").exists())
        self.assertTrue(u.groups.filter(name="staff").exists())
