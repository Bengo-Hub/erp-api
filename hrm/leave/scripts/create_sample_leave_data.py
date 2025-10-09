from decimal import ROUND_HALF_UP, Decimal
import random
from datetime import datetime, timedelta
from django.utils import timezone
from hrm.employees.models import Employee
from hrm.leave.models import LeaveCategory, LeaveEntitlement, LeaveRequest, LeaveBalance

def create_sample_leave_data():
    # Clear existing data (optional)
    LeaveRequest.objects.all().delete()
    LeaveBalance.objects.all().delete()
    LeaveEntitlement.objects.all().delete()
    LeaveCategory.objects.all().delete()

    # Create Leave Categories
    categories = [
        {"name": "Annual Leave", "description": "Paid time off for vacation"},
        {"name": "Sick Leave", "description": "Paid time off for illness"},
        {"name": "Maternity Leave", "description": "Leave for new mothers"},
        {"name": "Paternity Leave", "description": "Leave for new fathers"},
        {"name": "Study Leave", "description": "Leave for educational purposes"},
    ]
    
    created_categories = []
    for category in categories:
        cat, created = LeaveCategory.objects.get_or_create(
            name=category["name"],
            defaults={"description": category["description"]}
        )
        created_categories.append(cat)

    # Get all active employees
    employees = Employee.objects.filter(user__is_active=True)
    if not employees.exists():
        raise Exception("No active employees found. Please create some employees first.")
    
    current_year = datetime.now().year

    # Create Leave Entitlements
    for employee in employees:
        for category in created_categories:
            if category.name == "Annual Leave":
                days = min(Decimal(random.randint(21, 30)), Decimal('999.99'))
            elif category.name == "Sick Leave":
                days = min(Decimal(random.randint(10, 15)), Decimal('999.99'))
            else:
                days = min(Decimal(random.randint(5, 10)), Decimal('999.99'))
                
            entitlement, created = LeaveEntitlement.objects.get_or_create(
                employee=employee,
                category=category,
                year=current_year,
                defaults={"days_entitled": days}
            )

    # Create Leave Balances
    for entitlement in LeaveEntitlement.objects.all():
        days_taken = Decimal(random.uniform(0, float(entitlement.days_entitled) * 0.5)).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
        days_remaining = (entitlement.days_entitled - days_taken).quantize(Decimal('0.00'), rounding=ROUND_HALF_UP)
        
        balance, created = LeaveBalance.objects.get_or_create(
            employee=entitlement.employee,
            category=entitlement.category,
            year=current_year,
            defaults={
                "days_entitled": entitlement.days_entitled,
                "days_taken": days_taken,
                "days_remaining": days_remaining
            }
        )

    # Create Leave Requests
    status_choices = ['pending', 'approved', 'rejected', 'cancelled']
    for i in range(20):
        employee = random.choice(employees)
        category = random.choice(created_categories)
        
        balance = LeaveBalance.objects.filter(
            employee=employee,
            category=category,
            year=current_year
        ).first()
        
        if not balance:
            continue
            
        start_date = datetime(current_year, random.randint(1, 12), random.randint(1, 28)).date()
        max_days = min(14, float(balance.days_remaining))
        end_date = start_date + timedelta(days=random.randint(1, int(max_days)))
        days_requested = Decimal((end_date - start_date).days).quantize(Decimal('0.00'))
        
        if days_requested > balance.days_remaining:
            days_requested = balance.days_remaining.quantize(Decimal('0.00'))
            end_date = start_date + timedelta(days=float(days_requested))
        
        status = random.choice(status_choices)
        approved_by = None
        approved_at = None
        rejection_reason = ""
        
        if status == 'approved':
            approved_by = random.choice(employees.exclude(id=employee.id))
            approved_at = timezone.now() - timedelta(days=random.randint(1, 30))
        elif status == 'rejected':
            rejection_reason = random.choice([
                "Insufficient staff coverage",
                "Peak business period",
                "Insufficient leave balance",
                "Documentation required",
            ])
        
        request = LeaveRequest.objects.create(
            employee=employee,
            category=category,
            start_date=start_date,
            end_date=end_date,
            days_requested=days_requested,
            reason=random.choice([
                "Vacation with family",
                "Medical appointment",
                "Personal matters",
                "Mental health break",
                "Family emergency",
            ]),
            status=status,
            approved_by=approved_by,
            approved_at=approved_at,
            rejection_reason=rejection_reason,
        )
        print(f"Created leave request: {request}")

if __name__ == "__main__":
    create_sample_leave_data()