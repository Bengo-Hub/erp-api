"""
Behavioural tests for the payroll generation correctness fixes (Phase 1):
  - recurring earnings and payroll-scheduled expense claims are added to gross pay
  - after-PAYE recoverables (salary advances) actually reduce net pay
  - the recover_advances flag gates advance recovery
  - pay_type="net_pay" grosses the take-home target up

Statutory deductions and PAYE are switched off (no formulas seeded + deduct flags False) so the
assertions isolate the Phase 1 logic from tax-band configuration (covered separately in Phase 2).
"""
from decimal import Decimal
from datetime import date
from types import SimpleNamespace

from django.test import TestCase

from hrm.employees.models import Employee, SalaryDetails, CustomUser
from hrm.employees.models import Contract
from hrm.payroll_settings.models import PayrollComponents, RepayOption
from hrm.payroll.models import Earnings, ExpenseClaims, Advances
from hrm.payroll.utils import PayrollGenerator

PERIOD = date(2026, 6, 1)


class PayrollGenerationTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="emp@example.com", password="x", first_name="Test", last_name="Emp")
        self.employee = Employee.objects.create(
            user=self.user, gender="Male", date_of_birth=date(1990, 1, 1),
            residential_status="Resident", national_id="ID-001", pin_no="A001",
            shif_or_nhif_number="SH001", nssf_no="NS001",
        )
        SalaryDetails.objects.create(
            employee=self.employee, employment_type="regular-open", monthly_salary=Decimal("50000"),
            pay_type="gross", income_tax="primary", deduct_nssf=False, deduct_shif_or_nhif=False,
        )
        Contract.objects.create(
            employee=self.employee, contract_start_date=date(2026, 1, 1),
            contract_end_date=date(2026, 12, 31), status="active", salary=Decimal("50000"), pay_type="gross",
        )
        # A recurring allowance (+5000) effective for the period.
        allowance = PayrollComponents.objects.create(title="House Allowance", category="Earnings")
        Earnings.objects.create(employee=self.employee, earning=allowance, quantity=0, amount=Decimal("5000"), is_active=True)
        # A payroll-scheduled, approved, unpaid expense claim (+2000).
        ExpenseClaims.objects.create(
            employee=self.employee, category="Other", application_date=PERIOD, amount=Decimal("2000"),
            approved=True, is_paid=False, schedule_to_payroll=True,
        )

    def _generate(self, recover_advances, command="process"):
        request = SimpleNamespace(user=self.user)
        gen = PayrollGenerator(request, self.employee, PERIOD, recover_advances, command)
        result = gen.generate_payroll()
        self.assertTrue(result.get("success"), result)
        return result["payslip"]

    def test_earnings_and_expense_claims_added_to_gross(self):
        payslip = self._generate(recover_advances=False)
        # 50000 basic + 5000 allowance + 2000 scheduled claim
        self.assertEqual(Decimal(payslip.gross_pay), Decimal("57000"))
        # No statutory/PAYE/advances => net equals gross
        self.assertEqual(Decimal(payslip.net_pay), Decimal("57000"))

    def test_advance_recovery_reduces_net_and_respects_flag(self):
        repay = RepayOption.objects.create(amount=Decimal("12000"), no_of_installments=12)  # 1000/month
        Advances.objects.create(
            employee=self.employee, issue_date=date(2026, 1, 1), next_payment_date=PERIOD,
            repay_option=repay, is_active=True, amount_repaid=Decimal("0"),
        )
        with_recovery = self._generate(recover_advances=True)
        self.assertEqual(Decimal(with_recovery.net_pay), Decimal("56000"))  # 57000 - 1000

        # Re-running with the flag off must recompute (a plain "process" returns the cached payslip).
        without_recovery = self._generate(recover_advances=False, command="rerun")
        self.assertEqual(Decimal(without_recovery.net_pay), Decimal("57000"))

    def test_net_pay_type_is_grossed_up(self):
        # Switch the employee to a take-home target and remove extra earnings/claims for a clean check.
        Earnings.objects.filter(employee=self.employee).delete()
        ExpenseClaims.objects.filter(employee=self.employee).delete()
        sd = self.employee.salary_details.first()
        sd.pay_type = "net_pay"
        sd.save()
        payslip = self._generate(recover_advances=False)
        # With no statutory/PAYE, the grossed-up figure equals the 50000 net target.
        self.assertEqual(Decimal(payslip.gross_pay), Decimal("50000"))
        self.assertEqual(Decimal(payslip.net_pay), Decimal(payslip.gross_pay))
