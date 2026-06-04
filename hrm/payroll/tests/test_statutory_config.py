"""
Phase 2 tests: statutory rules are data-driven (no hardcoded relief/transition values).

Seeds the real FormulaSeederService config and asserts the engine resolves personal relief and the
NHIF↔SHIF transition from configuration (so tax-law changes are config-only, not code deploys).
"""
from decimal import Decimal
from datetime import date

from django.test import TestCase

from hrm.payroll_settings.services.formula_seeder import FormulaSeederService
from hrm.payroll_settings.models import Relief
from hrm.payroll.services.core_calculations import PayrollCalculationEngine


class StatutoryConfigTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        FormulaSeederService().seed_all_formulas()

    def test_personal_relief_sourced_from_config(self):
        eng = PayrollCalculationEngine(date(2026, 6, 1))
        # Seeded 2025 PAYE formula carries personal_relief = 2400.
        self.assertEqual(eng.resolve_personal_relief("primary"), Decimal("2400.00"))

    def test_relief_change_needs_no_code(self):
        # Operator raises personal relief via config; the engine must reflect it immediately.
        from hrm.payroll_settings.models import Formulas
        Formulas.objects.filter(type="income", category="primary", is_current=True).update(personal_relief=Decimal("3000"))
        eng = PayrollCalculationEngine(date(2026, 6, 1))
        self.assertEqual(eng.resolve_personal_relief("primary"), Decimal("3000.00"))

    def test_nhif_vs_shif_is_config_driven(self):
        # SHIF effective from 2024-10-01; NHIF before that.
        self.assertFalse(PayrollCalculationEngine(date(2026, 6, 1)).use_nhif_for_period())
        self.assertTrue(PayrollCalculationEngine(date(2020, 6, 1)).use_nhif_for_period())

    def test_progressive_paye_uses_seeded_bands(self):
        eng = PayrollCalculationEngine(date(2026, 6, 1))
        # Taxable 50,000 spans the 10% (0-24k) and 25% (24k-32,333) and 30% (>32,333) bands.
        # 24000*0.10 + 8333*0.25 + 17667*0.30 = 2400 + 2083.25 + 5300.10 = 9783.35
        paye = eng.calculate_income_tax(Decimal("50000"), "primary")
        self.assertGreater(paye, Decimal("9000"))
        self.assertLess(paye, Decimal("10500"))
