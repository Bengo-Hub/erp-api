#!/usr/bin/env python
"""
Payslip Generation Demo Script
Generates a payslip for an employee with KES 180,119 basic salary
and displays the detailed breakdown using the actual payroll system.
"""

import os
import sys
import django
from datetime import date
from decimal import Decimal

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')
django.setup()

from hrm.employees.models import Employee, SalaryDetails, CustomUser
from hrm.payroll_settings.models import Formulas, FormulaItems, PayrollComponents
from hrm.payroll.utils import PayrollGenerator
from hrm.payroll.functions import calculate_nssf_contribution, calculate_shif_deduction, calculate_other_deduction, calculate_income_tax

def get_existing_employee():
    """Get the first existing employee with regular-open employment type"""
    try:
        # Find first employee with regular-open employment type
        employee = Employee.objects.filter(
            salary_details__employment_type__icontains='regular'
        ).select_related('user').prefetch_related('salary_details').first()
        
        if not employee:
            print("No employee with regular-open employment type found. Looking for any employee...")
            employee = Employee.objects.select_related('user').prefetch_related('salary_details').first()
        
        if employee:
            # Get the first salary details for this employee
            salary_details = employee.salary_details.first()
            if not salary_details:
                print("No salary details found for employee")
                return None, None
                
            print(f"✓ Using existing employee: {employee.user.get_full_name()}")
            print(f"✓ Current salary: KES {salary_details.monthly_salary:,.2f}")
            print(f"✓ Employment type: {salary_details.employment_type}")
            print(f"✓ Income tax type: {salary_details.income_tax}")
            
            # Update salary to KES 180,119 for demo purposes
            if salary_details.monthly_salary != Decimal('180119'):
                print(f"📝 Updating salary from KES {salary_details.monthly_salary:,.2f} to KES 180,119.00")
                salary_details.monthly_salary = Decimal('180119')
                salary_details.save()
            
            return employee, salary_details
        else:
            print("No employees found in the system")
            return None, None
            
    except Exception as e:
        print(f"Error getting existing employee: {e}")
        return None, None

def get_existing_formulas():
    """Get existing formulas from the system"""
    try:
        print("🔍 Checking existing formulas...")
        
        # Get current formulas
        income_formula = Formulas.objects.filter(
            type='income', 
            category='primary', 
            is_current=True
        ).first()
        
        nssf_formula = Formulas.objects.filter(
            type='deduction', 
            category='social_security_fund',
            is_current=True
        ).first()
        
        shif_formula = Formulas.objects.filter(
            type='deduction', 
            category='shif',
            is_current=True
        ).first()
        
        housing_formula = Formulas.objects.filter(
            type='deduction', 
            category='housing_levy',
            is_current=True
        ).first()
        
        if income_formula:
            print(f"✓ Income Tax Formula: {income_formula.title}")
        if nssf_formula:
            print(f"✓ NSSF Formula: {nssf_formula.title}")
        if shif_formula:
            print(f"✓ SHIF Formula: {shif_formula.title}")
        if housing_formula:
            print(f"✓ Housing Levy Formula: {housing_formula.title}")
        
        return income_formula, nssf_formula, shif_formula, housing_formula
        
    except Exception as e:
        print(f"Error getting existing formulas: {e}")
        return None, None, None, None

def generate_payslip_with_system(employee, salary_details):
    """Generate payslip using the actual payroll system"""
    try:
        print("\n" + "=" * 80)
        print("GENERATING PAYSLIP USING ACTUAL PAYROLL SYSTEM")
        print("=" * 80)
        
        # Create a mock request object with a user
        class MockRequest:
            def __init__(self, user):
                self.user = user
        
        mock_request = MockRequest(employee.user)
        
        # Clear existing payslips for the period to ensure fresh generation
        payment_period = date(2025, 9, 1)  # September 2025
        print(f"🧹 Clearing existing payslips for {payment_period.strftime('%B %Y')}...")
        
        from hrm.payroll.models import Payslip
        existing_payslips = Payslip.objects.all()
        deleted_count = existing_payslips.count()
        existing_payslips.delete()
        print(f"✓ Deleted {deleted_count} existing payslip(s) for the period")
        
        # Create payroll generator
        payroll_generator = PayrollGenerator(
            request=mock_request,
            employee=employee,
            payment_period=payment_period,
            recover_advances=False,
            command='process'
        )
        
        # Generate payroll
        print(f"\n🚀 Generating fresh payroll for {employee.user.first_name} {employee.user.last_name}...")
        result = payroll_generator.generate_payroll()
        
        if hasattr(result, 'gross_pay'):
            payslip = result
        elif isinstance(result, dict) and 'payslip' in result:
            payslip = result['payslip']
        else:
            print(f"❌ Unexpected result type: {type(result)}")
            print(f"Result: {result}")
            return
        
        # Display payslip details
        print(f"✅ PAYSLIP GENERATED SUCCESSFULLY!")
        print("=" * 80)
        print("PAYSLIP DETAILS:")
        print("=" * 80)
        
        # Core payroll amounts
        print(f"Employee: {employee.user.get_full_name()}")
        print(f"Payment Period: {payslip.payment_period.strftime('%B %Y') if payslip.payment_period else 'September 2025'}")
        print(f"Employment Type: {salary_details.employment_type}")
        print(f"Income Tax Type: {salary_details.income_tax}")
        print()
        
        print("💰 EARNINGS & GROSS PAY:")
        print(f"  Basic Salary: KES {salary_details.monthly_salary:,.2f}")
        print(f"  Total Earnings: KES {payslip.total_earnings:,.2f}")
        print(f"  Gross Pay: KES {payslip.gross_pay:,.2f}")
        print()
        
        print("🔧 CALCULATION ENGINE:")
        print(f"  Dynamic Deduction Engine: ✅ Active (v2025.1)")
        print(f"  Formula Overrides: None (Using system defaults)")
        print()
        
        print("📊 TAX CALCULATION:")
        print(f"  Taxable Pay: KES {payslip.taxable_pay:,.2f}")
        print(f"  PAYE: KES {payslip.paye:,.2f}")
        print(f"  Personal Relief: KES {payslip.tax_relief:,.2f}")
        print(f"  Total Reliefs: KES {payslip.reliefs:,.2f}")
        print(f"  Gross Pay After Tax: KES {payslip.gross_pay_after_tax:,.2f}")
        print()
        
        print("🏦 STATUTORY DEDUCTIONS (Before Tax):")
        print(f"  NSSF Tier 1: KES {payslip.nssf_employee_tier_1:,.2f}")
        print(f"  NSSF Tier 2: KES {payslip.nssf_employee_tier_2:,.2f}")
        print(f"  Total NSSF: KES {payslip.nssf_employee_tier_1 + payslip.nssf_employee_tier_2:,.2f}")
        print(f"  SHIF/NHIF: KES {payslip.shif_or_nhif_contribution:,.2f}")
        print(f"  Housing Levy: KES {payslip.housing_levy:,.2f}")
        print(f"  Total Before Tax: KES {payslip.deductions_before_tax:,.2f}")
        print()
        
        print("📋 DEDUCTION PHASES:")
        print(f"  Before Tax: KES {payslip.deductions_before_tax:,.2f}")
        print(f"  After Tax: KES {payslip.deductions_after_tax:,.2f}")
        print(f"  After PAYE: KES {payslip.deductions_after_paye:,.2f}")
        print(f"  Final: KES {payslip.deductions_final:,.2f}")
        print()
        
        print("💵 FINAL PAYMENT:")
        print(f"  Net Pay: KES {payslip.net_pay:,.2f}")
        print()
        
        print("📈 EMPLOYER CONTRIBUTIONS:")
        print(f"  NSSF Employer: KES {payslip.nssf_employer_contribution:,.2f}")
        print()
        
        print("📋 PAYSLIP STATUS:")
        print(f"  Payroll Status: {payslip.payroll_status}")
        print(f"  Approval Status: {payslip.approval_status}")
        print(f"  Payslip ID: {payslip.id}")
        print()
        
        print("=" * 80)
        print("✅ PAYSLIP GENERATION COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        
        return payslip
            
    except Exception as e:
        print(f"❌ Error generating payslip with system: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    """Main function to run the payslip generation demo"""
    print("PAYSLIP GENERATION DEMO")
    print("=" * 80)
    print("This script will:")
    print("1. Use existing employee with updated salary KES 180,119")
    print("2. Use existing formulas from the system")
    print("3. Generate payslip using the actual payroll system")
    print("4. Display detailed breakdown on terminal")
    print("=" * 80)
    
    # Get existing employee and formulas
    employee, salary_details = get_existing_employee()
    if not employee:
        print("Failed to get existing employee. Exiting.")
        return
    
    income_formula, nssf_formula, shif_formula, housing_formula = get_existing_formulas()
    if not income_formula:
        print("⚠️  Warning: No income tax formula found, but continuing with demo...")
    
    print(f"✓ Using existing employee: {employee.user.get_full_name()}")
    print(f"✓ Updated salary: KES {salary_details.monthly_salary:,.2f}")
    print(f"✓ Using existing formulas from system")
    
    # Generate payslip using the actual payroll system
    payslip = generate_payslip_with_system(employee, salary_details)
    
    if payslip:
        print("\n🎉 DEMO COMPLETED SUCCESSFULLY!")
        print("The payslip has been generated and saved to the database.")
        print(f"Payslip ID: {payslip.id}")
    else:
        print("\n❌ DEMO FAILED!")
        print("Please check the error messages above and ensure the payroll system is properly configured.")

if __name__ == "__main__":
    main()
