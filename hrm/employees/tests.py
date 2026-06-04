"""
Employee/contract smoke tests against the CURRENT models.

The previous version of this file targeted the pre-decomposition Employee shape
(employment_type/date_employed on Employee, department/position on HRDetails) which no
longer exists, so every test in it errored. It has been replaced with valid coverage:
employment_type now lives on SalaryDetails; contracts carry type/probation/termination.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from hrm.employees.models import Employee, SalaryDetails, Contract, CustomUser


class EmployeeModelTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email="emp.smoke@example.com", password="x", first_name="Smoke", last_name="Test")
        self.employee = Employee.objects.create(
            user=self.user, gender="Male", date_of_birth=date(1990, 1, 1),
            residential_status="Resident", national_id="ID-SMOKE", pin_no="A-SMK",
            shif_or_nhif_number="SH-SMK", nssf_no="NS-SMK",
        )

    def test_employee_created_with_current_fields(self):
        self.assertEqual(self.employee.user.email, "emp.smoke@example.com")
        self.assertFalse(self.employee.deleted)
        self.assertFalse(self.employee.terminated)

    def test_salary_details_hold_employment_type(self):
        sd = SalaryDetails.objects.create(
            employee=self.employee, employment_type="regular-open",
            monthly_salary=Decimal("50000"), pay_type="gross", income_tax="primary")
        self.assertEqual(self.employee.salary_details.first().employment_type, "regular-open")
        self.assertEqual(sd.monthly_salary, Decimal("50000"))

    def test_contract_type_and_duration(self):
        contract = Contract.objects.create(
            employee=self.employee, contract_type="fixed_term",
            contract_start_date=date(2026, 1, 1), contract_end_date=date(2026, 12, 31),
            status="active", salary=Decimal("50000"), pay_type="gross")
        # contract_duration is auto-computed in days on save.
        self.assertEqual(contract.contract_type, "fixed_term")
        self.assertEqual(int(contract.contract_duration), 364)

    def test_contract_termination_reason(self):
        contract = Contract.objects.create(
            employee=self.employee, contract_start_date=date(2026, 1, 1),
            contract_end_date=date(2026, 12, 31), status="active",
            salary=Decimal("50000"), pay_type="gross")
        contract.status = "terminated"
        contract.termination_reason = "Resignation"
        contract.save()
        self.assertEqual(Contract.objects.get(pk=contract.pk).termination_reason, "Resignation")
