from ecommerce.pos.models import Sales, POSAdvanceSaleRecord, Register, salesItems
from django.db.models import Count, Q, Sum
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from hrm.payroll.models import Advances, RepayOption
from hrm.employees.models import Employee
from ecommerce.stockinventory.models import StockInventory
from crm.contacts.models import Contact
import uuid
from django.contrib.auth import get_user_model

User = get_user_model()

class POSReportService:
    @staticmethod
    def get_sales_summary(request):
        start_date = request.query_params.get('start_date', None)
        end_date = request.query_params.get('end_date', None)
        report_type = request.query_params.get('report_type', 'daily')

        if not start_date:
            start_date = timezone.now().date()
        if not end_date:
            end_date = timezone.now().date()

        if report_type == 'daily':
            sales_data = Sales.objects.filter(date_added__date=start_date)
        elif report_type == 'weekly':
            week_start = start_date - timedelta(days=start_date.weekday())
            week_end = week_start + timedelta(days=6)
            sales_data = Sales.objects.filter(date_added__date__range=[week_start, week_end])
        elif report_type == 'monthly':
            sales_data = Sales.objects.filter(date_added__year=start_date.year, date_added__month=start_date.month)
        elif report_type == 'yearly':
            sales_data = Sales.objects.filter(date_added__year=start_date.year)
        elif report_type == 'custom':
            sales_data = Sales.objects.filter(date_added__date__range=[start_date, end_date])
        else:
            return {'error': 'Invalid report_type parameter'}

        sales_summary = sales_data.values('date_added__date').annotate(
            sales_count=Count('id'),
            online_customer_count=Count('id', filter=Q(sales_type='online')),
            walk_in_customer_count=Count('id', filter=Q(sales_type='walk-in')),
            completed_count=Count('id', filter=Q(status='completed')),
            mpesa_count=Count('id', filter=Q(paymethod='mpesa') | Q(paymethod='mpesa_on_delivery')),
            cash_count=Count('id', filter=Q(paymethod='cash')),
            pending_count=Count('id', filter=Q(status='pending')),
            total=Sum('grand_total') or 0,
        )
        return {
            'sales_summary': list(sales_summary),
            'total_sales': sales_data.aggregate(Sum('grand_total'))['grand_total__sum'] or 0
        }


class StaffAdvanceService:
    @staticmethod
    def create_staff_advance_sale(staff_id, cart_items, amount, advance_type, installments=1, note=None, user=None):
        """
        Process a staff advance sale by creating both the POS sales record
        and linking it to the payroll advance system.
        
        Args:
            staff_id: ID of the staff/employee
            cart_items: List of items purchased
            amount: Total amount of the sale
            advance_type: Type of advance (salary_advance or loan_repayment)
            installments: Number of installments for repayment (default: 1)
            note: Optional note about the transaction
            user: User processing the transaction
            
        Returns:
            POSAdvanceSaleRecord instance
        """
        # Ensure database transaction
        with transaction.atomic(): 
            # Get the employee
            employee = Employee.objects.get(id=staff_id)
            
            # Create the sale record
            from .functions import generate_sale_id

            ## active register
            register = Register.objects.filter(is_open=True).first()

            ## create customer - Fix the location field issue
            employee_customer = Contact.objects.get_or_create(
                user=employee.user, 
                defaults={
                    'contact_id': str(uuid.uuid4().hex[:6]).upper(), 
                    'designation': 'Other', 
                    'account_type': 'Individual', 
                    'contact_type': 'Customers', 
                    'branch': register.branch if register else None,  # Use branch instead of location
                    'phone': employee.contacts.first().mobile_phone if employee.contacts.exists() else '+2547xxxxxxx', 
                    'is_deleted': False
                }
            )[0]
            employee_customer.accounts.get_or_create(account_balance=0, advance_balance=0, total_sale_due=0, total_sale_return_due=0)
            sale_id = generate_sale_id() or str(uuid.uuid4().hex[:6]).upper() # limit to 6 characters
            sale = Sales(
                register=register,
                customer=employee_customer,
                attendant=user,
                sale_id=sale_id,
                sub_total=amount,
                grand_total=amount,
                status='Final',
                payment_status='Paid',
                paymethod='Advance',
                sale_source='pos'
            )
            sale.save()
            
            # Process cart items
            for item in cart_items:
                # Get stock item by SKU if id is not present
                if 'id' in item:
                    stock_item = StockInventory.objects.get(id=item['id'])
                else:
                    # Try to find by SKU
                    stock_item = StockInventory.objects.get(product__sku=item['sku'])
                    
                salesItems.objects.create(
                    sale=sale,
                    stock_item=stock_item,
                    qty=item['quantity'],
                    unit_price=item['selling_price'],
                    sub_total=item['quantity'] * item['selling_price']
                )
                
                # Update stock quantity
                stock_item.stock_level -= item['quantity']
                stock_item.save()
            
            # Create or update payroll advance
            # First create a repay option for the advance
            installment_amount = amount / installments if installments > 0 else amount
            repay_option = RepayOption.objects.create(
                amount=amount,
                no_of_installments=installments,
                installment_amount=installment_amount
            )
            
            # Create the advance record
            advance = Advances.objects.create(
                employee=employee,
                approver=user,
                approved=True,
                issue_date=timezone.now().date(),
                repay_option=repay_option,
                next_payment_date=timezone.now().date() + timezone.timedelta(days=30),  # Default to 30 days
                is_active=True
            )
            
            # Create the POS advance sale record to link everything
            reference_id = f"ADV-{uuid.uuid4().hex[:8].upper()}"
            pos_record = POSAdvanceSaleRecord.objects.create(
                sale=sale,
                advance=advance,
                reference_id=reference_id,
                created_by=user
            )
            
            return pos_record 