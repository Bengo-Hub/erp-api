"""
Focused tests for the HR/manager permission gating applied to the sensitive
approve/reject actions of the appraisals viewsets.

These test the reusable permission classes from hrm.employees.permissions
directly (via the viewset's get_permissions), avoiding heavy Appraisal fixtures
while still proving the wiring: reads stay open, approve/reject are gated.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIRequestFactory

from hrm.employees.permissions import IsHRorManager, ReadOnlyOrHR, is_hr_or_manager
from .views import AppraisalViewSet

User = get_user_model()


class AppraisalPermissionGatingTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.plain = User.objects.create_user(
            email="plain@example.com", password="x", first_name="P", last_name="One"
        )
        self.hr = User.objects.create_user(
            email="hr@example.com", password="x", first_name="H", last_name="R"
        )
        hr_group, _ = Group.objects.get_or_create(name="hr")
        self.hr.groups.add(hr_group)
        self.staff = User.objects.create_user(
            email="staff@example.com", password="x", first_name="S", last_name="T"
        )
        self.staff.is_staff = True
        self.staff.save(update_fields=["is_staff"])

    def test_get_permissions_uses_hr_gate_for_approve_reject(self):
        for action in ("approve", "reject"):
            view = AppraisalViewSet()
            view.action = action
            classes = [type(p) for p in view.get_permissions()]
            self.assertIn(IsHRorManager, classes)

    def test_get_permissions_open_for_read_actions(self):
        for action in ("list", "retrieve", "submit"):
            view = AppraisalViewSet()
            view.action = action
            classes = [type(p) for p in view.get_permissions()]
            self.assertNotIn(IsHRorManager, classes)

    def test_plain_user_denied_hr_action(self):
        self.assertFalse(is_hr_or_manager(self.plain))
        perm = IsHRorManager()
        request = self.factory.post("/approve/")
        request.user = self.plain
        self.assertFalse(perm.has_permission(request, AppraisalViewSet()))

    def test_hr_group_user_allowed_hr_action(self):
        self.assertTrue(is_hr_or_manager(self.hr))
        perm = IsHRorManager()
        request = self.factory.post("/approve/")
        request.user = self.hr
        self.assertTrue(perm.has_permission(request, AppraisalViewSet()))

    def test_staff_user_allowed_hr_action(self):
        self.assertTrue(is_hr_or_manager(self.staff))

    def test_readonly_or_hr_allows_safe_methods_for_all(self):
        perm = ReadOnlyOrHR()
        request = self.factory.get("/")
        request.user = self.plain
        self.assertTrue(perm.has_permission(request, AppraisalViewSet()))

    def test_readonly_or_hr_blocks_writes_for_plain_user(self):
        perm = ReadOnlyOrHR()
        request = self.factory.post("/")
        request.user = self.plain
        self.assertFalse(perm.has_permission(request, AppraisalViewSet()))
