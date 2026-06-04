"""
Focused tests for the branding-aware employment contract PDF (Phase 5).

Verifies that the generator produces a valid PDF byte stream and that the
ContractViewSet ``pdf`` action returns a 200 application/pdf response for a
seeded contract. Branding is mocked so the test does not hit auth-api.
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from hrm.employees.models import Employee, Contract
from hrm.employees.contract_pdf import build_contract_pdf_bytes
from hrm.employees.views import ContractViewSet

User = get_user_model()


class ContractPDFTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="pdfuser@example.com", password="x",
            first_name="Jane", last_name="Doe",
        )
        self.employee = Employee.objects.create(
            user=self.user,
            gender="female",
            date_of_birth=date(1990, 5, 1),
            residential_status="Resident",
            national_id="PDF-NID-001",
            pin_no="A001122334Z",
            nssf_no="NSSF001",
        )
        self.contract = Contract.objects.create(
            employee=self.employee,
            contract_type="permanent",
            contract_start_date=date(2024, 1, 1),
            contract_end_date=date(2025, 12, 31),
            status="active",
            salary=Decimal("180119.00"),
            pay_type="gross",
            probation_end_date=date(2024, 4, 1),
            notes="Standard terms apply.\nConfidentiality clause in effect.",
        )

    def test_build_contract_pdf_bytes_returns_pdf(self):
        branding = {
            "name": "Acme Ltd",
            "primary_color": "#0055aa",
            "kra_pin": "P000000000A",
            "address": "Nairobi, Kenya",
        }
        pdf = build_contract_pdf_bytes(self.contract, branding=branding)
        self.assertIsInstance(pdf, (bytes, bytearray))
        self.assertGreater(len(pdf), 500)
        # PDF magic header.
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_build_contract_pdf_bytes_without_branding(self):
        # Empty branding must still render (falls back to defaults).
        pdf = build_contract_pdf_bytes(self.contract, branding={})
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_pdf_action_returns_200_pdf(self):
        # Patch the branding accessor used inside _resolve_branding so the test
        # does not call out to auth-api.
        with patch("integrations.branding.get_tenant_branding", return_value={"name": "Acme Ltd"}):
            factory = APIRequestFactory()
            request = factory.get(f"/hrm/employees/contracts/{self.contract.pk}/pdf/")
            force_authenticate(request, user=self.user)
            view = ContractViewSet.as_view({"get": "pdf"})
            response = view(request, pk=self.contract.pk)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            content = b"".join(response) if hasattr(response, "streaming_content") else response.content
            self.assertTrue(content.startswith(b"%PDF"))
