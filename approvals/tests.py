"""
Focused tests for approvals.integration: start_approval / record_decision.

We use a lightweight stand-in content object (auth Group) with a generic FK so
the test does not depend on heavy HR fixtures. The behaviour under test is the
integration contract, which is model-agnostic (generic content types).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from approvals.integration import start_approval, record_decision
from approvals.models import ApprovalWorkflow, ApprovalRequest

User = get_user_model()


class ApprovalIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="requester@example.com", password="x",
            first_name="R", last_name="Q",
        )
        # A generic content object to stand in for an appraisal/review.
        self.obj = Group.objects.create(name="content-obj")

    def test_start_approval_is_noop_without_workflow(self):
        result = start_approval(self.obj, "appraisal", self.user)
        self.assertIsNone(result)
        self.assertFalse(ApprovalRequest.objects.exists())

    def test_start_approval_creates_request_when_workflow_configured(self):
        ApprovalWorkflow.objects.create(
            name="Appraisal WF", workflow_type="appraisal", is_active=True,
        )
        request = start_approval(self.obj, "appraisal", self.user,
                                 title="Appraisal #1")
        self.assertIsNotNone(request)
        self.assertEqual(request.requester, self.user)
        self.assertEqual(request.workflow.workflow_type, "appraisal")
        # submit() should have advanced it out of draft.
        self.assertIn(request.status, ("submitted", "in_progress"))

    def test_start_approval_reuses_existing_request(self):
        ApprovalWorkflow.objects.create(
            name="Appraisal WF", workflow_type="appraisal", is_active=True,
        )
        first = start_approval(self.obj, "appraisal", self.user)
        second = start_approval(self.obj, "appraisal", self.user)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(ApprovalRequest.objects.count(), 1)

    def test_record_decision_noop_without_request(self):
        # No ApprovalRequest exists -> returns None, does not raise.
        self.assertIsNone(record_decision(self.obj, self.user, approved=True))

    def test_record_decision_approves_request(self):
        ApprovalWorkflow.objects.create(
            name="Appraisal WF", workflow_type="appraisal", is_active=True,
        )
        start_approval(self.obj, "appraisal", self.user)
        result = record_decision(self.obj, self.user, approved=True)
        self.assertIsNotNone(result)
        result.refresh_from_db()
        self.assertEqual(result.status, "approved")
        self.assertIsNotNone(result.approved_at)

    def test_record_decision_rejects_request(self):
        ApprovalWorkflow.objects.create(
            name="Appraisal WF", workflow_type="appraisal", is_active=True,
        )
        start_approval(self.obj, "appraisal", self.user)
        result = record_decision(self.obj, self.user, approved=False,
                                 notes="not good enough")
        self.assertIsNotNone(result)
        result.refresh_from_db()
        self.assertEqual(result.status, "rejected")
        self.assertIsNotNone(result.rejected_at)

    def test_new_workflow_type_choices_present(self):
        choices = dict(ApprovalWorkflow.WORKFLOW_TYPES)
        for key in ("appraisal", "performance_review", "recruitment_offer"):
            self.assertIn(key, choices)
