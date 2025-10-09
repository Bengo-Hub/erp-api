"""
Comprehensive Formula Seeder Service
Handles seeding of all historical and current payroll formulas for Kenya
Updated for 2025 tax changes and relief repeals
"""

from datetime import date
from decimal import Decimal
from django.db import transaction
from hrm.payroll_settings.models import (
    Formulas, FormulaItems, PayrollComponents, 
    SplitRatio, Relief
)
from .utils import generate_random_code


class FormulaSeederService:
    """
    Service for seeding all historical and current payroll formulas
    Updated for 2025 tax changes and relief repeals
    """
    
    def __init__(self):
        self.seed_date = date.today()
    
    def seed_all_formulas(self):
        """Seed all formulas from 2018 to current"""
        try:
            # Check if formulas already exist
            if self._formulas_exist():
                print("📋 Formulas already exist, skipping seeding process")
                return True
            
            with transaction.atomic():
                # Seed PAYE formulas
                self.seed_paye_formulas()
                
                # Seed NHIF formulas
                self.seed_nhif_formulas()
                
                # Seed SHIF formulas
                self.seed_shif_formulas()
                
                # Seed NSSF formulas
                self.seed_nssf_formulas()
                
                # Seed Housing Levy formulas
                self.seed_housing_levy_formulas()
                
                # Seed FBT formulas
                self.seed_fbt_formulas()
                
                # Seed relief formulas
                self.seed_relief_formulas()
                
                # Seed payroll components
                self.seed_payroll_components()
                
                print("✅ All formulas seeded successfully")
                return True
                
        except Exception as e:
            print(f"❌ Error seeding formulas: {e}")
            return False
    
    def _formulas_exist(self):
        """Check if core formulas already exist"""
        # Check for key formulas that indicate seeding has been done
        key_formulas = [
            "P.A.Y.E Kenya (Primary Employee) - 2025 Onwards",
            "N.H.I.F - 2018-2024",
            "N.S.S.F - 2025 Onwards",
            "Housing Levy - 2024 Onwards"
        ]
        
        existing_count = Formulas.objects.filter(title__in=key_formulas).count()
        return existing_count >= 2  # At least 2 key formulas should exist
    
    def seed_paye_formulas(self):
        """Seed all PAYE formulas from 2018 to 2025"""
        print("🌱 Seeding PAYE formulas...")
        
        # PAYE 2018-2020 (5 brackets, KES 1,408 relief)
        self._create_paye_formula(
            title="P.A.Y.E Kenya (Primary Employee) - 2018-2020",
            effective_from=date(2018, 1, 1),
            effective_to=date(2020, 12, 31),
            version="2018.1",
            personal_relief=Decimal('1408.00'),
            tax_brackets=[
                (0, 12298, 10),
                (12298, 23885, 15),
                (23885, 35472, 20),
                (35472, 47059, 25),
                (47059, 999999, 30)
            ],
            regulatory_source="Finance Act 2017",
            
        )
        
        # PAYE 2021-2022 (3 brackets, KES 2,400 relief)
        self._create_paye_formula(
            title="P.A.Y.E Kenya (Primary Employee) - 2021-2022",
            effective_from=date(2021, 1, 1),
            effective_to=date(2022, 12, 31),
            version="2021.1",
            personal_relief=Decimal('2400.00'),
            tax_brackets=[
                (0, 24000, 10),
                (24000, 32333, 25),
                (32333, 999999, 30)
            ],
            regulatory_source="Tax Laws (Amendment) Act 2020",
            
        )
        
        # PAYE 2023-2024 (5 brackets, KES 2,400 relief)
        self._create_paye_formula(
            title="P.A.Y.E Kenya (Primary Employee) - 2023-2024",
            effective_from=date(2023, 7, 1),
            effective_to=date(2024, 12, 31),
            version="2023.1",
            personal_relief=Decimal('2400.00'),
            tax_brackets=[
                (0, 24000, 10),
                (24000, 32333, 25),
                (32333, 500000, 30),
                (500000, 799999, 32.5),
                (800000, 999999, 35)
            ],
            regulatory_source="Finance Act 2023",
            
        )
        
        # PAYE 2025 onwards (5 brackets, KES 2,400 relief only - reliefs repealed)
        self._create_paye_formula(
            title="P.A.Y.E Kenya (Primary Employee) - 2025 Onwards",
            effective_from=date(2025, 2, 1),
            effective_to=None,
            version="2025.1",
            personal_relief=Decimal('2400.00'),
            tax_brackets=[
                (0, 24000, 10),
                (24000, 32333, 25),
                (32333, 500000, 30),
                (500000, 799999, 32.5),
                (800000, 999999, 35)
            ],
            regulatory_source="Finance Act 2024",
            is_current=True,
            notes="Personal relief only - SHIF and Housing Levy reliefs repealed as of Dec 2024"
        )
        
        # Secondary Employee formulas (flat 35% rate)
        self._create_paye_formula(
            title="P.A.Y.E Kenya (Secondary Employee) - 2018-2024",
            effective_from=date(2018, 1, 1),
            effective_to=date(2024, 12, 31),
            version="2018.1",
            category="secondary",
            personal_relief=Decimal('0.00'),
            tax_brackets=[
                (0, 999999, 35)
            ],
            regulatory_source="Finance Act 2017",
            
        )
        
        self._create_paye_formula(
            title="P.A.Y.E Kenya (Secondary Employee) - 2025 Onwards",
            effective_from=date(2025, 2, 1),
            effective_to=None,
            version="2025.1",
            category="secondary",
            personal_relief=Decimal('0.00'),
            tax_brackets=[
                (0, 999999, 35)
            ],
            regulatory_source="Finance Act 2024",
            is_current=True
        )
    
    def seed_nhif_formulas(self):
        """Seed NHIF formulas (2018-Sep 2024) - now deprecated"""
        print("🌱 Seeding NHIF formulas...")
        
        # NHIF 2018-Sep 2024 (fixed amounts)
        nhif_formula = self._create_deduction_formula(
            title="N.H.I.F - 2018-2024",
            effective_from=date(2018, 1, 1),
            effective_to=date(2024, 9, 30),
            version="2018.1",
            category="nhif",
            
            notes="Deprecated - replaced by SHIF effective Oct 2024"
        )
        
        # NHIF fixed amount brackets
        nhif_brackets = [
            (0, 5999, 150),
            (6000, 7999, 300),
            (8000, 11999, 400),
            (12000, 14999, 500),
            (15000, 19999, 650),
            (20000, 24999, 750),
            (25000, 29999, 850),
            (30000, 34999, 900),
            (35000, 39000, 950),
            (40000, 44999, 1000),
            (45000, 49000, 1100),
            (50000, 59999, 1200),
            (60000, 69999, 1300),
            (70000, 79999, 1400),
            (80000, 89999, 1500),
            (90000, 99999, 1600),
            (100000, 999999, 1700)
        ]
        
        for lower, upper, amount in nhif_brackets:
            FormulaItems.objects.update_or_create(
                formula=nhif_formula,
                amount_from=lower,
                amount_to=upper,
                defaults={'deduct_amount': amount}
            )
        
        # Create NHIF component
        nhif_component = self._create_payroll_component(
            title="N.H.I.F",
            category="Deductions",
            statutory=True,
            is_active=False  # Deprecated
        )
        
        # Create NHIF relief (15% - repealed Dec 2024)
        nhif_relief = Relief.objects.update_or_create(
            title="N.H.I.F Relief",
            defaults={
                "type": "Personal",
                "percentage": Decimal('15.00'),
                "fixed_limit": Decimal('5000.00'),
                "percent_of": "Actual",
                "is_active": False  # Repealed
            }
        )[0]
        
        nhif_component.applicable_relief = nhif_relief
        nhif_component.save()
        nhif_formula.deduction = nhif_component
        nhif_formula.save()
    
    def seed_shif_formulas(self):
        """Seed SHIF formulas (Oct 2024 onwards)"""
        print("🌱 Seeding SHIF formulas...")
        
        # SHIF Oct 2024 onwards (2.75% of gross)
        shif_formula = self._create_deduction_formula(
            title="S.H.I.F - 2024 Onwards",
            effective_from=date(2024, 10, 1),
            effective_to=None,
            version="2024.1",
            category="shif",
            is_current=True,
            notes="2.75% of gross salary, minimum KES 300/month"
        )
        
        # SHIF percentage-based calculation (2.75% of gross, minimum KES 300)
        FormulaItems.objects.update_or_create(
            formula=shif_formula,
            amount_from=0,
            amount_to=999999,  # Apply to all salary levels
            defaults={'deduct_percentage': Decimal('2.75')}
        )
        
        # Create SHIF component
        shif_component = self._create_payroll_component(
            title="S.H.I.F",
            category="Deductions",
            statutory=True,
            is_active=True,
            deduction_phase='before_tax',
            deduction_priority=2
        )
        
        # Create SHIF relief (15% - repealed Dec 2024)
        shif_relief = Relief.objects.update_or_create(
            title="S.H.I.F Relief",
            defaults={
                "type": "Personal",
                "percentage": Decimal('15.00'),
                "fixed_limit": Decimal('5000.00'),
                "percent_of": "Actual",
                "is_active": False  # Repealed
            }
        )[0]
        
        shif_component.applicable_relief = shif_relief
        shif_component.save()
        shif_formula.deduction = shif_component
        shif_formula.save()
        
        # Create split ratio (employee 100%, employer 0%)
        SplitRatio.objects.update_or_create(
            formula=shif_formula,
            defaults={
                "employee_percentage": Decimal('100.00'),
                "employer_percentage": Decimal('0.00')
            }
        )
    
    def seed_nssf_formulas(self):
        """Seed NSSF formulas with all historical rates"""
        print("🌱 Seeding NSSF formulas...")
        
        # NSSF 2018-Jan 2023 (flat KES 200/month)
        nssf_2018 = self._create_deduction_formula(
            title="N.S.S.F - 2018-2023",
            effective_from=date(2018, 1, 1),
            effective_to=date(2023, 1, 31),
            version="2018.1",
            category="social_security_fund",
            
            notes="Flat KES 200/month until court case resolved"
        )
        
        # NSSF Feb 2023-Jan 2024 (6% on KES 6,000-18,000)
        nssf_2023 = self._create_deduction_formula(
            title="N.S.S.F - 2023-2024",
            effective_from=date(2023, 2, 1),
            effective_to=date(2024, 1, 31),
            version="2023.1",
            category="social_security_fund",
            
            notes="6% on KES 6,000-18,000 (max KES 2,160)"
        )
        
        # NSSF Feb 2024-Jan 2025 (6% on KES 7,000-36,000)
        nssf_2024 = self._create_deduction_formula(
            title="N.S.S.F - 2024-2025",
            effective_from=date(2024, 2, 1),
            effective_to=date(2025, 1, 31),
            version="2024.1",
            category="social_security_fund",
            
            notes="6% on KES 7,000-36,000 (max KES 4,320)"
        )
        
        # NSSF Feb 2025 onwards (6% on KES 8,000-72,000) - UPDATED
        nssf_2025 = self._create_deduction_formula(
            title="N.S.S.F - 2025 Onwards",
            effective_from=date(2025, 2, 1),
            effective_to=None,
            version="2025.1",
            category="social_security_fund",
            is_current=True,
            notes="6% on KES 8,000-72,000 (max KES 4,800) - Updated limits effective Feb 2025"
        )
        
        # Create NSSF components
        nssf_component = self._create_payroll_component(
            title="N.S.S.F",
            category="Deductions",
            statutory=True,
            is_active=True,
            deduction_phase='before_tax',
            deduction_priority=1
        )
        
        nssf_voluntary = self._create_payroll_component(
            title="Voluntary N.S.S.F",
            category="Deductions",
            statutory=False,
            is_active=True
        )
        
        # Create NSSF relief (30% up to KES 20,000)
        nssf_relief = Relief.objects.update_or_create(
            title="Retirement Fund Relief",
            defaults={
                "type": "Deductible",
                "percentage": Decimal('30.00'),
                "fixed_limit": Decimal('20000.00'),
                "percent_of": "Basic_benefits",
                "is_active": True
            }
        )[0]
        
        nssf_component.applicable_relief = nssf_relief
        nssf_voluntary.applicable_relief = nssf_relief
        nssf_component.save()
        nssf_voluntary.save()
        
        # Link components to formulas
        nssf_2025.deduction = nssf_component
        nssf_2025.save()
        
        # Create formula items for each NSSF version
        self._create_nssf_formula_items(nssf_2018, [(0, 200, 200)])  # Flat amount
        self._create_nssf_formula_items(nssf_2023, [(0, 6000, 6), (6000, 18000, 6)])  # 6% tiers
        self._create_nssf_formula_items(nssf_2024, [(0, 7000, 6), (7000, 36000, 6)])  # 6% tiers
        self._create_nssf_formula_items(nssf_2025, [(0, 8000, 6), (8000, 72000, 6)])  # 6% tiers - UPDATED
        
        # Create split ratios (employee 100%, employer 100%)
        for formula in [nssf_2018, nssf_2023, nssf_2024, nssf_2025]:
            SplitRatio.objects.update_or_create(
                formula=formula,
                defaults={
                    "employee_percentage": Decimal('100.00'),
                    "employer_percentage": Decimal('100.00')
                }
            )
    
    def seed_housing_levy_formulas(self):
        """Seed Housing Levy formulas (Mar 2024 onwards)"""
        print("🌱 Seeding Housing Levy formulas...")
        
        # Housing Levy Mar 2024 onwards (1.5% of gross)
        housing_formula = self._create_deduction_formula(
            title="Housing Levy - 2024 Onwards",
            effective_from=date(2024, 3, 19),
            effective_to=None,
            version="2024.1",
            category="housing_levy",
            is_current=True,
            notes="1.5% of gross salary, employer matches 100%"
        )
        
        # Housing Levy percentage-based calculation
        FormulaItems.objects.update_or_create(
            formula=housing_formula,
            amount_from=0,
            amount_to=999999,
            defaults={'deduct_percentage': Decimal('1.5')}
        )
        
        # Create Housing Levy component
        housing_component = self._create_payroll_component(
            title="Housing Levy",
            category="Deductions",
            statutory=True,
            is_active=True,
            deduction_phase='before_tax',
            deduction_priority=3
        )
        
        # Create Housing Levy relief (15% - repealed Dec 2024)
        housing_relief = Relief.objects.update_or_create(
            title="AHL Relief",
            defaults={
                "type": "Deductible",
                "percentage": Decimal('15.00'),
                "fixed_limit": Decimal('9000.00'),
                "percent_of": "Actual",
                "is_active": False  # Repealed
            }
        )[0]
        
        housing_component.applicable_relief = housing_relief
        housing_component.save()
        housing_formula.deduction = housing_component
        housing_formula.save()
        
        # Create split ratio (employee 100%, employer 100%)
        SplitRatio.objects.update_or_create(
            formula=housing_formula,
            defaults={
                "employee_percentage": Decimal('100.00'),
                "employer_percentage": Decimal('100.00')
            }
        )
    
    def seed_fbt_formulas(self):
        """Seed Fringe Benefit Tax formulas"""
        print("🌱 Seeding FBT formulas...")
        
        # FBT 2021 onwards (30% on benefits)
        fbt_formula = self._create_deduction_formula(
            title="F.B.T. 2021",
            effective_from=date(2021, 1, 1),
            effective_to=None,
            version="2021.1",
            category="fbt",
            is_current=True,
            notes="30% on fringe benefits up to KES 10,000"
        )
        
        # FBT percentage-based calculation
        FormulaItems.objects.update_or_create(
            formula=fbt_formula,
            amount_from=0,
            amount_to=10000,
            defaults={'deduct_percentage': Decimal('30.00')}
        )
        
        # Create split ratio (employee 0%, employer 100%)
        SplitRatio.objects.update_or_create(
            formula=fbt_formula,
            defaults={
                "employee_percentage": Decimal('0.00'),
                "employer_percentage": Decimal('100.00')
            }
        )
    
    def seed_relief_formulas(self):
        """Seed relief formulas - Updated for 2025 changes"""
        print("🌱 Seeding relief formulas...")
        
        # Personal Relief (KES 2,400 only as of Dec 2024)
        Relief.objects.update_or_create(
            title="Personal Relief",
            defaults={
                "type": "Personal",
                "percentage": Decimal('0.00'),
                "fixed_limit": Decimal('2400.00'),
                "percent_of": "Actual",
                "is_active": True
            }
        )
        
        # Create repealed reliefs for historical reference
        Relief.objects.update_or_create(
            title="SHIF Relief (Repealed)",
            defaults={
                "type": "Personal",
                "percentage": Decimal('15.00'),
                "fixed_limit": Decimal('5000.00'),
                "percent_of": "Actual",
                "is_active": False
            }
        )
        
        Relief.objects.update_or_create(
            title="Housing Levy Relief (Repealed)",
            defaults={
                "type": "Deductible",
                "percentage": Decimal('15.00'),
                "fixed_limit": Decimal('9000.00'),
                "percent_of": "Actual",
                "is_active": False
            }
        )
    
    def seed_payroll_components(self):
        """Seed basic payroll components"""
        print("🌱 Seeding payroll components...")
        
        # Deductions
        deductions = [
            {"title": "Absent(Days)", "mode": "perday", "constant": False, "deduct_after_taxing": False},
            {"title": "Absent(Hours)", "mode": "perhour", "constant": False, "deduct_after_taxing": False},
            {"title": "Absenteeism", "mode": None, "deduct_after_taxing": False},
            {"title": "Advance Pay", "mode": "monthly", "constant": False, "deduct_after_taxing": True},
            {"title": "Incomplete Month Adjustment", "mode": None, "deduct_after_taxing": False},
            {"title": "Leave Days Owed", "mode": "perday", "deduct_after_taxing": False},
            {"title": "Losses/Damages", "mode": None, "deduct_after_taxing": False},
            {"title": "N.I.T.A", "mode": "monthly", "deduct_after_taxing": True},
            {"title": "P.A.Y.E Arrears", "mode": "monthly", "deduct_after_taxing": True},
            {"title": "P.A.Y.E Gratuity", "mode": "monthly", "deduct_after_taxing": True},
            {"title": "Rent Recovered From Employee", "mode": None, "deduct_after_taxing": True},
        ]
        
        for deduction_data in deductions:
            deduction_data['wb_code'] = generate_random_code('D')
            title = deduction_data.pop('title')
            self._create_payroll_component(
                title=title,
                category="Deductions",
                **deduction_data
            )
        
        # Earnings
        earnings = [
            {"title": "Bonus", "mode": "monthly", "taxable_status": "taxable"},
            {"title": "Commissions", "mode": "monthly", "taxable_status": "taxable"},
            {"title": "Daily Wages", "mode": "perday", "taxable_status": "nontaxable"},
            {"title": "Hourly Wages", "mode": "perhour", "taxable_status": "nontaxable"},
            {"title": "Overtime", "mode": "monthly", "taxable_status": "nontaxable"},
            {"title": "Overtime @1.5x", "mode": "perhour", "taxable_status": "nontaxable"},
            {"title": "Overtime @2x", "mode": "perhour", "taxable_status": "nontaxable"},
            {"title": "Payment in Lieu of Leave", "mode": "perday", "taxable_status": "nontaxable"},
            {"title": "Service Gratuity", "mode": "monthly", "taxable_status": "gratuity"},
            {"title": "Severance Pay", "mode": "monthly", "taxable_status": "gratuity"},
        ]
        
        for earning_data in earnings:
            earning_data['wb_code'] = generate_random_code('E')
            title = earning_data.pop('title')
            self._create_payroll_component(
                title=title,
                category="Earnings",
                **earning_data
            )
        
        # Benefits
        benefits = [
            {"title": "Car Benefit", "mode": "monthly", "taxable_status": "taxable"},
            {"title": "Food Allowance", "mode": "monthly", "taxable_status": "nontaxable"},
            {"title": "House Allowance", "mode": "monthly", "taxable_status": "nontaxable"},
            {"title": "Housing Benefit", "mode": "monthly", "taxable_status": "taxable"},
            {"title": "Per Diem", "mode": None, "taxable_status": "nontaxable"},
            {"title": "Transport Allowance", "mode": "monthly", "taxable_status": "taxable"},
        ]
        
        for benefit_data in benefits:
            benefit_data['wb_code'] = generate_random_code('B')
            title = benefit_data.pop('title')
            self._create_payroll_component(
                title=title,
                category="Benefits",
                **benefit_data
            )
    
    def _create_paye_formula(self, **kwargs):
        """Helper to create PAYE formula with items"""
        formula = self._create_deduction_formula(
            type="income",
            **kwargs
        )
        
        # Create tax bracket items
        tax_brackets = kwargs.get('tax_brackets', [])
        for lower, upper, rate in tax_brackets:
            FormulaItems.objects.update_or_create(
                formula=formula,
                amount_from=lower,
                amount_to=upper,
                defaults={'deduct_percentage': rate}
            )
        
        return formula
    
    def _create_deduction_formula(self, **kwargs):
        """Helper to create deduction formula"""
        defaults = {
            'type': kwargs.get('type', 'deduction'),
            'category': kwargs.get('category', 'primary'),
            'unit': 'KES',
            'effective_from': kwargs.get('effective_from', date.today()),
            'effective_to': kwargs.get('effective_to'),
            'personal_relief': kwargs.get('personal_relief', Decimal('0.00')),
            'is_current': kwargs.get('is_current', False),

            'version': kwargs.get('version', '1.0'),
            'regulatory_source': kwargs.get('regulatory_source', ''),
            'notes': kwargs.get('notes', ''),
            'created_at': date.today()
        }
        
        formula, created = Formulas.objects.update_or_create(
            title=kwargs['title'],
            defaults=defaults
        )
        
        # Set deduction order based on formula version
        if formula.type == 'income':
            formula.deduction_order = self._get_deduction_order_for_version(formula.version)
            formula.save()
        
        if created:
            print(f"✅ Created formula: {formula.title}")
        else:
            print(f"🔄 Updated formula: {formula.title}")
        
        return formula
    
    def _create_payroll_component(self, **kwargs):
        """Helper to create payroll component"""
        defaults = {
            'category': kwargs.get('category', 'Deductions'),
            'mode': kwargs.get('mode', 'monthly'),
            'non_cash': kwargs.get('non_cash', False),
            'deduct_after_taxing': kwargs.get('deduct_after_taxing', False),
            'checkoff': kwargs.get('checkoff', True),
            'constant': kwargs.get('constant', True),
            'statutory': kwargs.get('statutory', False),
            'is_active': kwargs.get('is_active', True),
            'taxable_status': kwargs.get('taxable_status'),
            'wb_code': kwargs.get('wb_code', generate_random_code('C')),
            'acc_code': kwargs.get('acc_code', ''),
            'description': kwargs.get('description', ''),
            'deduction_phase': kwargs.get('deduction_phase', 'before_tax'),
            'deduction_priority': kwargs.get('deduction_priority', 1)
        }
        
        component, created = PayrollComponents.objects.update_or_create(
            title=kwargs['title'],
            defaults=defaults
        )
        
        return component
    
    def _get_deduction_order_for_version(self, version):
        """Get deduction order based on formula version"""
        if version.startswith('2018') or version.startswith('2021') or version.startswith('2023'):
            # Pre-2025: SHIF/NHIF and Housing Levy were deducted AFTER PAYE
            return [
                {"phase": "before_tax", "components": ["nssf"]},
                {"phase": "after_tax", "components": ["paye"]},
                {"phase": "after_paye", "components": ["shif", "housing_levy", "loans", "advances", "loss_damages"]},
                {"phase": "final", "components": ["non_cash_benefits"]}
            ]
        elif version.startswith('2025'):
            # 2025 onwards: SHIF and Housing Levy deducted BEFORE PAYE
            return [
                {"phase": "before_tax", "components": ["nssf", "shif", "housing_levy"]},
                {"phase": "after_tax", "components": ["paye"]},
                {"phase": "after_paye", "components": ["loans", "advances", "loss_damages"]},
                {"phase": "final", "components": ["non_cash_benefits"]}
            ]
        else:
            # Default order for unknown versions
            return [
                {"phase": "before_tax", "components": ["nssf", "shif", "housing_levy"]},
                {"phase": "after_tax", "components": ["paye"]},
                {"phase": "after_paye", "components": ["loans", "advances", "loss_damages"]},
                {"phase": "final", "components": ["non_cash_benefits"]}
            ]
    
    def _create_nssf_formula_items(self, formula, tiers):
        """Helper to create NSSF formula items"""
        for lower, upper, rate in tiers:
            if rate <= 100:  # Percentage
                FormulaItems.objects.update_or_create(
                    formula=formula,
                    amount_from=lower,
                    amount_to=upper,
                    defaults={'deduct_percentage': rate}
                )
            else:  # Fixed amount
                FormulaItems.objects.update_or_create(
                    formula=formula,
                    amount_from=lower,
                    amount_to=upper,
                    defaults={'deduct_amount': rate}
                )
