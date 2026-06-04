"""Phase 6 tests: onboarding workflow seeding + completion."""
from datetime import date

from django.test import TestCase

from hrm.employees.models import Employee, CustomUser
from hrm.recruitment.onboarding_models import EmployeeOnboarding, OnboardingTask, DEFAULT_ONBOARDING_TASKS


class OnboardingTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="hire@example.com", password="x", first_name="New", last_name="Hire")
        self.employee = Employee.objects.create(
            user=self.user, gender="Male", date_of_birth=date(1995, 3, 3),
            residential_status="Resident", national_id="ID-HIRE", pin_no="P-HR",
            shif_or_nhif_number="SH-HR", nssf_no="NS-HR",
        )

    def test_seed_default_tasks_and_progress(self):
        onboarding = EmployeeOnboarding.objects.create(employee=self.employee)
        onboarding.seed_default_tasks()
        self.assertEqual(onboarding.tasks.count(), len(DEFAULT_ONBOARDING_TASKS))
        self.assertEqual(onboarding.status, "in_progress")
        self.assertIsNotNone(onboarding.started_at)
        # idempotent
        onboarding.seed_default_tasks()
        self.assertEqual(onboarding.tasks.count(), len(DEFAULT_ONBOARDING_TASKS))

    def test_completing_all_tasks_completes_onboarding(self):
        onboarding = EmployeeOnboarding.objects.create(employee=self.employee)
        onboarding.seed_default_tasks()
        OnboardingTask.objects.filter(onboarding=onboarding).update(is_done=True)
        onboarding.refresh_status()
        onboarding.refresh_from_db()
        self.assertEqual(onboarding.status, "completed")
        self.assertIsNotNone(onboarding.completed_at)
