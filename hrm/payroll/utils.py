"""
Modern Payroll Generation System
Main orchestrator for all payroll operations with clean, unified workflow
"""

import calendar
import logging
from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from hrm.employees.models import Employee, SalaryDetails
from hrm.attendance.models import AttendanceRecord
from .models import Payslip, Benefits, Earnings, ExpenseClaims
from .services.core_calculations import PayrollCalculationEngine
from .services.dynamic_deduction_engine import DynamicDeductionEngine
from .services.payroll_notification_service import PayrollNotificationService

logger = logging.getLogger(__name__)


class PayrollGenerator:
    """
    Modern payroll generation orchestrator
    Handles all employment types with unified workflow and dynamic deduction engine
    """
    
    def __init__(self, request, employee, payment_period: date, recover_advances: bool, command: str, formula_overrides: dict = None):
        self.request = request
        self.employee = employee
        self.payment_period = payment_period
        self.recover_advances = recover_advances
        self.command = command
        self.formula_overrides = formula_overrides or {}
        
        # Initialize services
        self.calculation_engine = PayrollCalculationEngine(payment_period, formula_overrides)
        self.notification_service = PayrollNotificationService()
        
        # Resolve employee instance lazily (supports passing IDs or lightweight objects)
        self.employee_instance = self._resolve_employee()

        # Get employee details
        self.salary_details = self._get_salary_details()
        self._set_deduction_preferences()

    def _resolve_employee(self):
        """Return a concrete Employee instance regardless of how it was provided."""
        from hrm.employees.models import Employee

        if isinstance(self.employee, Employee):
            return self.employee

        if isinstance(self.employee, int):
            employee_id = self.employee
        else:
            employee_id = getattr(self.employee, 'id', None) or getattr(self.employee, 'pk', None)

        if not employee_id:
            return None

        return Employee.objects.filter(id=employee_id).first()
    
    def _get_salary_details(self):
        """Get employee's salary details"""
        try:
            if not self.employee_instance:
                return None
            return SalaryDetails.objects.get(employee=self.employee_instance)
        except SalaryDetails.DoesNotExist:
            return None
    
    def _set_deduction_preferences(self):
        """Set deduction preferences based on employee settings"""
        if self.salary_details:
            self.deduct_shif_or_nhif = self.salary_details.deduct_shif_or_nhif
            self.deduct_nssf = self.salary_details.deduct_nssf
        else:
            self.deduct_shif_or_nhif = True
            self.deduct_nssf = True
    
    def should_use_nhif(self):
        """Use NHIF vs SHIF based on which health formula is effective for the period (config-driven)."""
        return self.calculation_engine.use_nhif_for_period()
    
    def get_effective_formula(self, formula_type, category=None):
        """Get effective formula using centralized engine"""
        return self.calculation_engine.get_effective_formula(formula_type, category)
    
    def generate_payroll(self):
        """Main entry point for payroll generation"""
        if not self.salary_details:
            return {"detail": "Salary details not found for the employee.", "success": False}
        
        if not self._validate_payment_period():
            return {"detail": "Invalid payment period.", "success": False}
        
        # Route to appropriate payroll type
        employment_type = self.salary_details.employment_type
        
        if employment_type in ["regular-open", "regular-fixed", "intern", "probationary"]:
            return self._generate_regular_payroll()
        elif employment_type == "consultant":
            return self._generate_consultant_payroll()
        elif employment_type == "casual":
            return self._generate_casual_payroll()
        else:
            return {"detail": "Unsupported employment type.", "success": False}
    
    def _validate_payment_period(self):
        """Validate payment period"""
        try:
            if not self.employee_instance:
                return False

            # Allow future dates for payroll planning, but not too far in the future (max 1 year)
            max_future_date = date.today().replace(year=date.today().year + 1)
            if self.payment_period > max_future_date:
                return False
            
            # Check if employee has active contracts that cover the payment period
            active_contracts = self.employee_instance.contracts.filter(
                status='active',
                contract_start_date__lte=self.payment_period,
                contract_end_date__gte=self.payment_period
            )
            
            return active_contracts.exists()
        except Exception:
            return False
    
    def _generate_regular_payroll(self):
        """Generate payroll for regular employees"""
        try:
            with transaction.atomic():
                existing_payroll = self._check_existing_payroll()
                if existing_payroll and self.command != 'rerun':
                    return existing_payroll
                
                if self.command in ["process", "rerun"]:
                    return self._process_payroll()
                elif self.command == "queue":
                    return self._queue_payroll()
                else:
                    return {"detail": "Invalid command.", "success": False}
        except Exception as e:
            return {"detail": f"Error generating regular payroll: {str(e)}", "success": False}
    
    def _generate_consultant_payroll(self):
        """Generate payroll for consultants"""
        try:
            with transaction.atomic():
                gross_pay = self._calculate_consultant_gross_pay()
                return self._process_payroll_with_gross_pay(gross_pay)
        except Exception as e:
            return {"detail": f"Error generating consultant payroll: {str(e)}", "success": False}
    
    def _generate_casual_payroll(self):
        """Generate payroll for casual employees"""
        try:
            with transaction.atomic():
                gross_pay = self._calculate_casual_gross_pay()
                return self._process_payroll_with_gross_pay(gross_pay)
        except Exception as e:
            return {"detail": f"Error generating casual payroll: {str(e)}", "success": False}
    
    def _process_payroll(self):
        """Process payroll using dynamic deduction engine"""
        try:
            gross_pay, total_earnings = self._calculate_gross_pay()
            return self._process_payroll_with_gross_pay(gross_pay, total_earnings)
        except Exception as e:
            return {"detail": f"Error processing payroll: {str(e)}", "success": False}
    
    def _process_payroll_with_gross_pay(self, gross_pay, total_earnings=Decimal('0')):
        """Process payroll with given gross pay amount"""
        try:
            # Apply deductions using dynamic engine
            deductions_by_phase, component_values = self._apply_deductions_dynamically(gross_pay)
            
            # Calculate taxable income
            taxable_income = gross_pay - deductions_by_phase['before_tax']
            
            # Calculate PAYE
            paye_data = self._calculate_paye(taxable_income)
            
            # Calculate net pay
            net_pay = self._calculate_net_pay(gross_pay, deductions_by_phase, paye_data)
            
            # Create payslip
            payslip = self._create_payslip(
                gross_pay, total_earnings, net_pay, taxable_income,
                deductions_by_phase, component_values, paye_data
            )
            
            return {
                "success": True,
                "payslip_id": payslip.id,
                "payslip": payslip
            }
        except Exception as e:
            return {"detail": f"Error processing payroll: {str(e)}", "success": False}
    
    def _apply_deductions_dynamically(self, gross_pay):
        """Apply deductions using dynamic deduction engine"""
        try:
            income_formula = self.get_effective_formula('income', 'primary')
            
            if income_formula and income_formula.version and income_formula.deduction_order:
                logger.info("Using dynamic deduction engine (v%s)", income_formula.version)

                deduction_engine = DynamicDeductionEngine(
                    formula_version=income_formula.version,
                    payroll_date=self.payment_period,
                    formula_overrides=self.formula_overrides,
                    recover_advances=self.recover_advances
                )
                
                engine_deductions = deduction_engine.calculate_deductions_in_order(
                    gross_pay=gross_pay,
                    employee=self.employee_instance or self.employee,
                    payment_period=self.payment_period,
                    formula_overrides=self.formula_overrides
                )
                
                return self._convert_engine_results(engine_deductions)
            else:
                logger.info("Using fallback deduction calculation")
                return self._apply_deductions_fallback(gross_pay)

        except Exception as e:
            logger.warning("Dynamic deduction engine failed, using fallback: %s", e)
            return self._apply_deductions_fallback(gross_pay)
    
    def _convert_engine_results(self, engine_deductions):
        """Convert dynamic engine results to expected format"""
        deductions_by_phase = {
            'before_tax': Decimal('0'),
            'after_tax': Decimal('0'),
            'after_paye': Decimal('0'),
            'final': Decimal('0')
        }
        
        component_values = {
            'tier_1_nssf': Decimal('0'),
            'tier_2_nssf': Decimal('0'),
            'nssf_employer_contribution': Decimal('0'),
            'nhif_employee_contribution': Decimal('0'),
            'nhif_employer_contribution': Decimal('0'),
            'shif_employee_contribution': Decimal('0'),
            'shif_employer_contribution': Decimal('0'),
            'hslevy_employee_contribution': Decimal('0'),
            'hslevy_employer_contribution': Decimal('0')
        }
        
        for phase, phase_deductions in engine_deductions.items():
            if isinstance(phase_deductions, dict):
                for component_name, component_data in phase_deductions.items():
                    if isinstance(component_data, dict):
                        amount = component_data.get('amount', Decimal('0'))
                        # PAYE is represented separately (paye field + paye_after_relief in net pay),
                        # so it is not folded into the phase deduction totals to avoid double counting.
                        if component_name != 'paye':
                            deductions_by_phase[phase] += amount

                        if component_name == 'nssf':
                            component_values['tier_1_nssf'] = component_data.get('tier_1_employee', Decimal('0'))
                            component_values['tier_2_nssf'] = component_data.get('tier_2_employee', Decimal('0'))
                            component_values['nssf_employer_contribution'] = component_data.get('employer_contribution', Decimal('0'))
                        elif component_name == 'nhif':
                            component_values['nhif_employee_contribution'] = component_data.get('employee_contribution', Decimal('0'))
                            component_values['nhif_employer_contribution'] = component_data.get('employer_contribution', Decimal('0'))
                        elif component_name == 'shif':
                            component_values['shif_employee_contribution'] = component_data.get('employee_contribution', Decimal('0'))
                            component_values['shif_employer_contribution'] = component_data.get('employer_contribution', Decimal('0'))
                        elif component_name == 'housing_levy':
                            component_values['hslevy_employee_contribution'] = component_data.get('employee_contribution', Decimal('0'))
                            component_values['hslevy_employer_contribution'] = component_data.get('employer_contribution', Decimal('0'))
        
        return deductions_by_phase, component_values
    
    def _apply_deductions_fallback(self, gross_pay):
        """Fallback deduction calculation using centralized engine"""
        deductions_by_phase = {
            'before_tax': Decimal('0'),
            'after_tax': Decimal('0'),
            'after_paye': Decimal('0'),
            'final': Decimal('0')
        }
        
        component_values = {
            'tier_1_nssf': Decimal('0'),
            'tier_2_nssf': Decimal('0'),
            'nssf_employer_contribution': Decimal('0'),
            'nhif_employee_contribution': Decimal('0'),
            'nhif_employer_contribution': Decimal('0'),
            'shif_employee_contribution': Decimal('0'),
            'shif_employer_contribution': Decimal('0'),
            'hslevy_employee_contribution': Decimal('0'),
            'hslevy_employer_contribution': Decimal('0')
        }
        
        # Calculate NSSF
        if self.deduct_nssf:
            nssf_data = self.calculation_engine.calculate_nssf_contribution(gross_pay)
            component_values['tier_1_nssf'] = nssf_data['tier_1_employee']
            component_values['tier_2_nssf'] = nssf_data['tier_2_employee']
            component_values['nssf_employer_contribution'] = nssf_data['total_employer']
            deductions_by_phase['before_tax'] += nssf_data['total_employee']
        
        # Calculate SHIF/NHIF
        if self.deduct_shif_or_nhif:
            if self.should_use_nhif():
                nhif_data = self.calculation_engine.calculate_nhif_contribution(gross_pay)
                component_values['nhif_employee_contribution'] = nhif_data['employee_contribution']
                component_values['nhif_employer_contribution'] = nhif_data['employer_contribution']
                deductions_by_phase['before_tax'] += nhif_data['employee_contribution']
            else:
                shif_data = self.calculation_engine.calculate_shif_contribution(gross_pay)
                component_values['shif_employee_contribution'] = shif_data['employee_contribution']
                component_values['shif_employer_contribution'] = shif_data['employer_contribution']
                deductions_by_phase['before_tax'] += shif_data['employee_contribution']
        
        # Calculate Housing Levy
        levy_data = self.calculation_engine.calculate_housing_levy(gross_pay)
        component_values['hslevy_employee_contribution'] = levy_data['employee_contribution']
        component_values['hslevy_employer_contribution'] = levy_data['employer_contribution']
        deductions_by_phase['before_tax'] += levy_data['employee_contribution']

        # Personal recoverables (loans, salary advances, loss/damages) and non-cash benefits —
        # parity with the dynamic engine so they actually reduce net pay in the fallback path too.
        emp_deductions = self.calculation_engine.calculate_employee_deductions(
            self.employee_instance or self.employee, gross_pay, recover_advances=self.recover_advances)
        deductions_by_phase['after_paye'] += (
            emp_deductions['loans'] + emp_deductions['advances'] + emp_deductions['loss_damages'])
        deductions_by_phase['final'] += emp_deductions['non_cash_benefits']

        return deductions_by_phase, component_values
    
    def _sum_active_earnings(self):
        """Sum the employee's recurring earnings/allowances effective for the period."""
        emp = self.employee_instance or self.employee
        qs = Earnings.objects.filter(employee=emp, is_active=True)
        qs = qs.filter(Q(effective_date__lte=self.payment_period) | Q(effective_date__isnull=True))
        qs = qs.filter(Q(end_date__gte=self.payment_period) | Q(end_date__isnull=True))
        return sum((e.amount or Decimal('0') for e in qs), Decimal('0'))

    def _sum_scheduled_expense_claims(self):
        """Sum approved, unpaid expense claims flagged to be paid through payroll."""
        emp = self.employee_instance or self.employee
        qs = ExpenseClaims.objects.filter(
            employee=emp, schedule_to_payroll=True, approved=True,
            is_paid=False, delete_status=False,
        )
        return sum((c.amount or Decimal('0') for c in qs), Decimal('0'))

    def _statutory_net_for_gross(self, gross):
        """Net pay considering only statutory deductions + PAYE for a candidate gross (gross-up helper)."""
        nssf = self.calculation_engine.calculate_nssf_contribution(gross)['total_employee'] if self.deduct_nssf else Decimal('0')
        statutory_health = Decimal('0')
        if self.deduct_shif_or_nhif:
            if self.should_use_nhif():
                statutory_health = self.calculation_engine.calculate_nhif_contribution(gross)['employee_contribution']
            else:
                statutory_health = self.calculation_engine.calculate_shif_contribution(gross)['employee_contribution']
        levy = self.calculation_engine.calculate_housing_levy(gross)['employee_contribution']
        before_tax = nssf + statutory_health + levy
        taxable = gross - before_tax
        category = getattr(self.salary_details, 'income_tax', 'primary') or 'primary'
        if category == 'secondary':
            paye = taxable
        else:
            paye = self.calculation_engine.calculate_income_tax(taxable, category)
        relief = self.calculation_engine.resolve_personal_relief(category)
        paye_after = max(Decimal('0'), paye - relief)
        return gross - before_tax - paye_after

    def _gross_up_from_net(self, net_target):
        """Solve for the gross salary whose statutory+PAYE net equals ``net_target`` (bisection)."""
        net_target = Decimal(net_target or 0)
        if net_target <= 0:
            return Decimal('0')
        low = net_target
        high = net_target * Decimal('3')
        # Expand the upper bound until it brackets the target.
        for _ in range(20):
            if self._statutory_net_for_gross(high) >= net_target:
                break
            high *= Decimal('2')
        mid = high
        for _ in range(80):
            mid = (low + high) / Decimal('2')
            net = self._statutory_net_for_gross(mid)
            if abs(net - net_target) <= Decimal('0.01'):
                break
            if net < net_target:
                low = mid
            else:
                high = mid
        return mid.quantize(Decimal('0.01'))

    def _calculate_gross_pay(self):
        """Calculate gross pay and total earnings for regular employees.

        ``monthly_salary`` is interpreted per ``pay_type``: as the gross basic for "gross_pay"
        (default), or as a take-home target for "net_pay" (grossed up over statutory + PAYE).
        Recurring earnings/allowances and payroll-scheduled expense claims are added on top.
        """
        try:
            base = self.salary_details.monthly_salary or Decimal('0')
            total_earnings = self._sum_active_earnings() + self._sum_scheduled_expense_claims()

            pay_type = getattr(self.salary_details, 'pay_type', 'gross_pay')
            base_gross = self._gross_up_from_net(base) if pay_type == 'net_pay' else base

            gross_pay = base_gross + total_earnings
            return gross_pay, total_earnings
        except Exception as e:
            print(f"Error calculating gross pay: {e}")
            return Decimal('0'), Decimal('0')
    
    def _calculate_consultant_gross_pay(self):
        """Calculate gross pay for consultants"""
        try:
            base_payment = self.salary_details.monthly_salary
            additional_payments = self._calculate_consultant_additional_payments()
            return base_payment + additional_payments
        except Exception as e:
            print(f"Error calculating consultant gross pay: {e}")
            return Decimal('0')
    
    def _calculate_casual_gross_pay(self):
        """Calculate gross pay for casual employees"""
        try:
            attendance_records = AttendanceRecord.objects.filter(
                employee=self.employee_instance or self.employee,
                date__year=self.payment_period.year,
                date__month=self.payment_period.month,
                status='present'
            )
            
            total_days = attendance_records.count()
            daily_rate = self.salary_details.daily_rate or Decimal('0')
            base_payment = daily_rate * total_days
            
            casual_allowances = self._calculate_casual_allowances()
            return base_payment + casual_allowances
        except Exception as e:
            print(f"Error calculating casual gross pay: {e}")
            return Decimal('0')
    
    def _calculate_paye(self, taxable_income):
        """Calculate PAYE using centralized engine"""
        try:
            if self.salary_details.income_tax == "primary":
                paye = self.calculation_engine.calculate_income_tax(taxable_income, "primary")
                tax_relief = self.calculation_engine.resolve_personal_relief("primary")
            elif self.salary_details.income_tax == "secondary":
                paye = taxable_income
                tax_relief = Decimal('0')
            else:
                paye = Decimal('0')
                tax_relief = Decimal('0')
            
            return {
                'paye': paye,
                'tax_relief': tax_relief,
                'reliefs': tax_relief
            }
        except Exception as e:
            print(f"Error calculating PAYE: {e}")
            return {
                'paye': Decimal('0'),
                'tax_relief': Decimal('0'),
                'reliefs': Decimal('0')
            }
    
    def _calculate_net_pay(self, gross_pay, deductions_by_phase, paye_data):
        """Calculate net pay according to PNA.co.ke methodology"""
        try:
            # Calculate PAYE after relief
            paye_after_reliefs = max(Decimal('0'), paye_data['paye'] - paye_data['reliefs'])

            # Net Pay = Gross - before-tax statutory (NSSF/SHIF/Housing) - PAYE(after relief)
            #           - after-PAYE recoverables (loans, salary advances, loss/damages).
            # PAYE represents the `after_tax` phase, so it is not subtracted twice. Non-cash
            # benefits (`final`) raise taxable income but are not a cash deduction, so they are
            # intentionally excluded from cash net pay.
            net_pay = (
                gross_pay
                - deductions_by_phase['before_tax']
                - paye_after_reliefs
                - deductions_by_phase['after_paye']
            )

            # Guard: deductions must never produce a negative payable. Floor at 0 and flag the
            # shortfall so it is visible (and excluded from disbursement, which only pays net > 0).
            if net_pay < 0:
                logger.warning(
                    "Negative net pay floored to 0 for employee=%s period=%s (computed=%s)",
                    getattr(self, 'employee', None), self.payment_period, net_pay,
                )
                net_pay = Decimal('0')

            return net_pay
        except Exception as e:
            print(f"Error calculating net pay: {e}")
            return gross_pay
    
    def _create_payslip(self, gross_pay, total_earnings, net_pay, taxable_income, deductions_by_phase, component_values, paye_data):
        """Create payslip record"""
        try:
            payslip_defaults = {
                "gross_pay": round(gross_pay),
                "total_earnings": total_earnings,
                "net_pay": round(net_pay),
                "taxable_pay": taxable_income,
                "paye": paye_data['paye'],
                "tax_relief": paye_data['tax_relief'],
                "reliefs": paye_data['reliefs'],
                "gross_pay_after_tax": gross_pay - deductions_by_phase['before_tax'] - max(Decimal('0'), paye_data['paye'] - paye_data['reliefs']),
                "shif_or_nhif_contribution": component_values['nhif_employee_contribution'] if self.should_use_nhif() else component_values['shif_employee_contribution'],
                "housing_levy": component_values['hslevy_employee_contribution'],
                "nssf_employee_tier_1": component_values['tier_1_nssf'],
                "nssf_employee_tier_2": component_values['tier_2_nssf'],
                "nssf_employer_contribution": component_values['nssf_employer_contribution'],
                "deductions_before_tax": deductions_by_phase['before_tax'],
                "deductions_after_tax": deductions_by_phase['after_tax'],
                "deductions_after_paye": deductions_by_phase['after_paye'],
                "deductions_final": deductions_by_phase['final'],
                "approval_status": "pending",
                "payroll_status": "complete",
                "period_start": self.payment_period,
                "period_end": self._get_period_end()
            }
            
            employee_instance = self._resolve_employee()
            if employee_instance is None:
                raise ValueError("Employee context is required to generate a payslip.")

            created_by_user = getattr(self.request, 'user', None)
            payslip_defaults["created_by"] = created_by_user

            # Idempotency: a payslip is uniquely identified by (employee, period). Keying on
            # created_by too let different users create duplicate payslips for the same period.
            payslip, created = Payslip.objects.update_or_create(
                employee=employee_instance,
                payment_period=self.payment_period,
                delete_status=False,
                defaults=payslip_defaults
            )

            return payslip
        except Exception as e:
            print(f"Error creating payslip: {e}")
            raise
    
    def _calculate_consultant_additional_payments(self):
        """Additional consultant payments = their active earnings/allowances for the period."""
        try:
            return self._sum_active_earnings()
        except Exception as e:
            print(f"Error calculating consultant additional payments: {e}")
            return Decimal('0')

    def _calculate_casual_allowances(self):
        """Casual allowances = their active earnings/allowances for the period (on top of day-rate pay)."""
        try:
            return self._sum_active_earnings()
        except Exception as e:
            print(f"Error calculating casual allowances: {e}")
            return Decimal('0')
    
    def _check_existing_payroll(self):
        """Check for existing payroll"""
        try:
            employee = self.employee_instance or self.employee
            if not employee:
                return None

            existing_payslip = Payslip.objects.filter(
                employee=employee,
                payment_period=self.payment_period
            ).first()
            
            if existing_payslip:
                return {
                    "success": True,
                    "payslip_id": existing_payslip.id,
                    "payslip": existing_payslip,
                    "message": "Payroll already exists for this period"
                }
            return None
        except Exception as e:
            print(f"Error checking existing payroll: {e}")
            return None
    
    def _queue_payroll(self):
        """Queue payroll for later processing"""
        try:
            payslip_defaults = {
                "gross_pay": Decimal('0'),
                "total_earnings": Decimal('0'),
                "net_pay": Decimal('0'),
                "approval_status": "draft",
                "payroll_status": "queued",
                "period_start": self.payment_period,
                "period_end": self._get_period_end()
            }
            
            employee_instance = self.employee_instance or self._resolve_employee()
            if employee_instance is None:
                raise ValueError("Employee context is required to queue payroll.")

            created_by_user = getattr(self.request, 'user', None)
            payslip_defaults["created_by"] = created_by_user

            # Idempotency: key on (employee, period) only — see _create_payslip.
            payslip, created = Payslip.objects.update_or_create(
                employee=employee_instance,
                payment_period=self.payment_period,
                delete_status=False,
                defaults=payslip_defaults
            )

            return {
                "success": True,
                "payslip_id": payslip.id,
                "payslip": payslip,
                "message": "Payroll queued for processing"
            }
        except Exception as e:
            return {"detail": f"Error queuing payroll: {str(e)}", "success": False}
    
    def _get_period_end(self):
        """Get period end date"""
        try:
            if self.payment_period.day == 1:
                if self.payment_period.month == 1:
                    return date(self.payment_period.year - 1, 12, 31)
                else:
                    return date(self.payment_period.year, self.payment_period.month - 1, 
                              calendar.monthrange(self.payment_period.year, self.payment_period.month - 1)[1])
            else:
                return date(self.payment_period.year, self.payment_period.month,
                          calendar.monthrange(self.payment_period.year, self.payment_period.month)[1])
        except Exception:
            return self.payment_period
class PayrollUtilities:
    """
    Utility functions for payroll operations
    Provides helper methods for common payroll tasks
    """
    
    def __init__(self, payment_period: date, formula_overrides: dict = None):
        self.payment_period = payment_period
        self.formula_overrides = formula_overrides or {}
        self.calculation_engine = PayrollCalculationEngine(payment_period, formula_overrides)
    
    def calculate_employee_benefits(self, employee):
        """Calculate total employee benefits"""
        try:
            benefits = Benefits.objects.filter(
                employee=employee,
                is_active=True,
                effective_from__lte=self.payment_period
            )
            
            total_benefits = sum(benefit.amount for benefit in benefits)
            
            return {
                'total_benefits': total_benefits,
                'benefits_list': [
                    {
                        'name': benefit.benefit.title,
                        'amount': benefit.amount,
                        'type': benefit.benefit.category
                    } for benefit in benefits
                ]
            }
        except Exception as e:
            print(f"Error calculating employee benefits: {e}")
            return {'total_benefits': Decimal('0'), 'benefits_list': []}
    
    def calculate_employee_deductions(self, employee):
        """Calculate employee-specific deductions (loans, advances, etc.)"""
        try:
            from ..models import EmployeLoans, Advances, LossesAndDamages
            
            total_loans = Decimal('0')
            total_advances = Decimal('0')
            total_loss_damages = Decimal('0')
            
            # Calculate loans
            active_loans = EmployeLoans.objects.filter(
                employee=employee,
                is_active=True,
                status='active'
            )
            for loan in active_loans:
                if loan.monthly_deduction:
                    total_loans += loan.monthly_deduction
            
            # Calculate advances
            active_advances = Advances.objects.filter(
                employee=employee,
                is_active=True,
                status='active'
            )
            for advance in active_advances:
                if advance.monthly_deduction:
                    total_advances += advance.monthly_deduction
            
            # Calculate loss/damages
            active_loss_damages = LossesAndDamages.objects.filter(
                employee=employee,
                is_active=True,
                status='active'
            )
            for loss_damage in active_loss_damages:
                if loss_damage.monthly_deduction:
                    total_loss_damages += loss_damage.monthly_deduction
            
            return {
                'loans': total_loans,
                'advances': total_advances,
                'loss_damages': total_loss_damages,
                'total': total_loans + total_advances + total_loss_damages
            }
        except Exception as e:
            print(f"Error calculating employee deductions: {e}")
            return {
                'loans': Decimal('0'),
                'advances': Decimal('0'),
                'loss_damages': Decimal('0'),
                'total': Decimal('0')
            }
    
    def calculate_attendance_pay(self, employee, daily_rate):
        """Calculate pay based on attendance records"""
        try:
            attendance_records = AttendanceRecord.objects.filter(
                employee=employee,
                date__year=self.payment_period.year,
                date__month=self.payment_period.month,
                status='present'
            )
            
            total_days = attendance_records.count()
            total_pay = daily_rate * total_days
            
            return {
                'total_days': total_days,
                'daily_rate': daily_rate,
                'total_pay': total_pay
            }
        except Exception as e:
            print(f"Error calculating attendance pay: {e}")
            return {
                'total_days': 0,
                'daily_rate': daily_rate,
                'total_pay': Decimal('0')
            }
    
    def validate_payment_period(self, employee):
        """Validate if payment period is valid for employee"""
        try:
            if self.payment_period > date.today():
                return False, "Payment period cannot be in the future"
            
            active_contracts = employee.contracts.filter(
                status='active',
                contract_start_date__lte=self.payment_period,
                contract_end_date__gte=self.payment_period
            )
            
            if not active_contracts.exists():
                return False, "No active contract for this period"
            
            return True, "Valid payment period"
        except Exception as e:
            return False, f"Error validating payment period: {e}"
    
    def get_period_dates(self, payment_period):
        """Get period start and end dates"""
        try:
            if payment_period.day == 1:
                if payment_period.month == 1:
                    period_end = date(payment_period.year - 1, 12, 31)
                else:
                    period_end = date(
                        payment_period.year, 
                        payment_period.month - 1, 
                        calendar.monthrange(payment_period.year, payment_period.month - 1)[1]
                    )
            else:
                period_end = date(
                    payment_period.year, 
                    payment_period.month,
                    calendar.monthrange(payment_period.year, payment_period.month)[1]
                )
            
            return payment_period, period_end
        except Exception as e:
            print(f"Error calculating period dates: {e}")
            return payment_period, payment_period
    
    def format_currency(self, amount):
        """Format currency amount for display"""
        try:
            return f"KES {amount:,.2f}"
        except Exception:
            return f"KES {amount}"
    
    def calculate_employer_contributions(self, gross_pay):
        """Calculate total employer contributions"""
        try:
            nssf_data = self.calculation_engine.calculate_nssf_contribution(gross_pay)
            
            if self.payment_period < date(2025, 1, 1):
                nhif_data = self.calculation_engine.calculate_nhif_contribution(gross_pay)
            else:
                nhif_data = self.calculation_engine.calculate_shif_contribution(gross_pay)
            
            levy_data = self.calculation_engine.calculate_housing_levy(gross_pay)
            
            total_employer = (
                nssf_data['total_employer'] + 
                nhif_data['employer_contribution'] + 
                levy_data['employer_contribution']
            )
            
            return {
                'nssf_employer': nssf_data['total_employer'],
                'nhif_employer': nhif_data['employer_contribution'],
                'levy_employer': levy_data['employer_contribution'],
                'total_employer': total_employer
            }
        except Exception as e:
            print(f"Error calculating employer contributions: {e}")
            return {
                'nssf_employer': Decimal('0'),
                'nhif_employer': Decimal('0'),
                'levy_employer': Decimal('0'),
                'total_employer': Decimal('0')
            }
    
    def generate_payslip_summary(self, payslip):
        """Generate a summary of payslip data"""
        try:
            return {
                'employee_name': f"{payslip.employee.user.first_name} {payslip.employee.user.last_name}",
                'period': payslip.payment_period.strftime('%B %Y'),
                'gross_pay': self.format_currency(payslip.gross_pay),
                'net_pay': self.format_currency(payslip.net_pay),
                'total_deductions': self.format_currency(payslip.gross_pay - payslip.net_pay),
                'status': payslip.payroll_status
            }
        except Exception as e:
            print(f"Error generating payslip summary: {e}")
            return {}
    
    def check_payslip_exists(self, employee, payment_period):
        """Check if payslip already exists for employee and period"""
        try:
            existing_payslip = Payslip.objects.filter(
                employee=employee,
                payment_period=payment_period
            ).first()
            
            return existing_payslip is not None, existing_payslip
        except Exception as e:
            print(f"Error checking existing payslip: {e}")
            return False, None
    
    def get_employee_salary_details(self, employee):
        """Get employee salary details with error handling"""
        try:
            return SalaryDetails.objects.get(employee=employee)
        except SalaryDetails.DoesNotExist:
            return None
        except Exception as e:
            print(f"Error getting salary details: {e}")
            return None
class PayrollValidator:
    """
    Validation utilities for payroll operations
    """
    
    @staticmethod
    def validate_employee_data(employee):
        """Validate employee data for payroll processing"""
        errors = []
        
        if not employee.user:
            errors.append("Employee must have a user account")
        
        if not hasattr(employee, 'salary_details') or not employee.salary_details.exists():
            errors.append("Employee must have salary details")
        
        if not employee.contracts.filter(status='active').exists():
            errors.append("Employee must have an active contract")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_payment_period(payment_period):
        """Validate payment period"""
        errors = []
        
        if payment_period > date.today():
            errors.append("Payment period cannot be in the future")
        
        if payment_period.year < 2020:
            errors.append("Payment period too far in the past")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def validate_formula_overrides(formula_overrides):
        """Validate formula overrides"""
        errors = []
        
        if not isinstance(formula_overrides, dict):
            errors.append("Formula overrides must be a dictionary")
            return False, errors
        
        valid_types = ['income', 'nssf', 'nhif', 'shif', 'housing_levy']
        for key in formula_overrides.keys():
            if key not in valid_types:
                errors.append(f"Invalid formula type: {key}")
        
        return len(errors) == 0, errors
class PayrollFormatter:
    """
    Formatting utilities for payroll data
    """
    
    @staticmethod
    def format_payslip_data(payslip):
        """Format payslip data for display"""
        try:
            return {
                'employee': {
                    'name': f"{payslip.employee.user.first_name} {payslip.employee.user.last_name}",
                    'id': payslip.employee.id,
                    'department': payslip.employee.hr_details.department.name if hasattr(payslip.employee, 'hr_details') and payslip.employee.hr_details.department else 'N/A'
                },
                'period': {
                    'start': payslip.period_start.strftime('%Y-%m-%d'),
                    'end': payslip.period_end.strftime('%Y-%m-%d'),
                    'month': payslip.payment_period.strftime('%B %Y')
                },
                'payments': {
                    'gross_pay': f"KES {payslip.gross_pay:,.2f}",
                    'net_pay': f"KES {payslip.net_pay:,.2f}",
                    'total_earnings': f"KES {payslip.total_earnings:,.2f}"
                },
                'deductions': {
                    'nssf': f"KES {payslip.nssf_employee_tier_1 + payslip.nssf_employee_tier_2:,.2f}",
                    'nhif': f"KES {payslip.nhif_contribution:,.2f}",
                    'housing_levy': f"KES {payslip.housing_levy:,.2f}",
                    'paye': f"KES {payslip.paye:,.2f}"
                },
                'status': {
                    'payroll_status': payslip.payroll_status,
                    'approval_status': payslip.approval_status
                }
            }
        except Exception as e:
            print(f"Error formatting payslip data: {e}")
            return {}
    
    @staticmethod
    def format_currency(amount):
        """Format currency amount"""
        try:
            return f"KES {amount:,.2f}"
        except Exception:
            return f"KES {amount}"
    
    @staticmethod
    def format_percentage(value, total):
        """Format percentage value"""
        try:
            if total == 0:
                return "0.00%"
            percentage = (value / total) * 100
            return f"{percentage:.2f}%"
        except Exception:
            return "0.00%"

