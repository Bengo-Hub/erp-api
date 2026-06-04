"""Phase 5 tests: leave accrual + year-end carry-over."""
from decimal import Decimal
from datetime import date

from django.test import TestCase
from django.core.management import call_command

from hrm.employees.models import Employee, CustomUser
from hrm.leave.models import LeaveCategory, LeaveBalance


class LeaveAccrualTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="lv@example.com", password="x", first_name="Lv", last_name="User")
        self.employee = Employee.objects.create(
            user=self.user, gender="Male", date_of_birth=date(1990, 1, 1), residential_status="Resident",
            national_id="ID-LV", pin_no="P-LV", shif_or_nhif_number="SH-LV", nssf_no="NS-LV")
        self.annual = LeaveCategory.objects.create(
            name="Annual Leave", default_annual_days=Decimal("21"), allow_carryover=True, max_carryover_days=Decimal("10"))

    def test_accrual_creates_balance(self):
        call_command("accrue_leave", "--year", "2026")
        bal = LeaveBalance.objects.get(employee=self.employee, category=self.annual, year=2026)
        self.assertEqual(bal.days_entitled, Decimal("21.00"))
        self.assertEqual(bal.days_remaining, Decimal("21.00"))

    def test_carryover_capped(self):
        # Prior year leaves 12 remaining; cap is 10 → 2027 entitlement = 21 + 10.
        LeaveBalance.objects.create(employee=self.employee, category=self.annual, year=2026,
                                    days_entitled=Decimal("21"), days_taken=Decimal("9"), days_remaining=Decimal("12"))
        call_command("accrue_leave", "--year", "2027")
        bal = LeaveBalance.objects.get(employee=self.employee, category=self.annual, year=2027)
        self.assertEqual(bal.days_entitled, Decimal("31.00"))  # 21 + capped 10

    def test_no_carryover_when_disabled(self):
        sick = LeaveCategory.objects.create(name="Sick Leave", default_annual_days=Decimal("14"), allow_carryover=False)
        LeaveBalance.objects.create(employee=self.employee, category=sick, year=2026,
                                    days_entitled=Decimal("14"), days_taken=Decimal("2"), days_remaining=Decimal("12"))
        call_command("accrue_leave", "--year", "2027")
        bal = LeaveBalance.objects.get(employee=self.employee, category=sick, year=2027)
        self.assertEqual(bal.days_entitled, Decimal("14.00"))  # no carry-over
