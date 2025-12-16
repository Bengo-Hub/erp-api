"""
Centralized payment orchestration service for the entire application.
This module harmonizes payment processing across all modules including:
- ecommerce orders
- billing documents
- POS sales
- expense payments
"""
import logging
import uuid
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.conf import settings

from finance.accounts.models import Transaction, PaymentAccounts, TransactionPayment
from integrations.payments.card_payment import CardPaymentService
from integrations.payments.mpesa_payment import MpesaPaymentService
from finance.payment.models import Payment as BillingPayment
from ecommerce.pos.models import Sales, MpesaTransaction

logger = logging.getLogger(__name__)

class PaymentOrchestrationService:
    """
    Centralized payment orchestration that coordinates all payment operations
    across the system. This ensures payments are properly recorded in the finance
    module while still allowing module-specific payment records.
    """
    
    PAYMENT_METHODS = {
        'cash': 'Cash',
        'mpesa': 'Mpesa',
        'bank': 'Bank Transfer',
        'card': 'Card',
        'credit': 'Credit',
        'cheque': 'Cheque',
        'voucher': 'Voucher',
        'other': 'Other',
    }
    
    def __init__(self, payment_account=None):
        """Initialize with optional payment account"""
        self.payment_account = payment_account
    
    @transaction.atomic
    def process_order_payment(self, order, amount, payment_method, 
                             transaction_id=None, transaction_details=None,
                             created_by=None, payment_date=None):
        """
        Process a payment for an Order
        
        Args:
            order: Order instance
            amount: Decimal amount to pay
            payment_method: String payment method code (cash, mpesa, card, etc.)
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, payment_object)
        """
        # Dynamic import to avoid circular imports
        from ecommerce.order.models import Order
        from core_orders.models import OrderPayment
        from finance.payment.models import Payment as FinancePayment
        
        if not isinstance(order, Order):
            return False, "Invalid order object", None
            
        if amount <= 0:
            return False, "Payment amount must be positive", None
            
        if payment_method not in self.PAYMENT_METHODS:
            return False, f"Unsupported payment method: {payment_method}", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"{payment_method.upper()}-{uuid.uuid4().hex[:8]}"
                
            # 1. Create Finance Payment record and link via OrderPayment
            finance_payment = FinancePayment.objects.create(
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                status='completed',
                reference_number=transaction_id,
                transaction_id=transaction_id,
                processor_response=transaction_details or {},
                payment_date=payment_date,
                verified_by=created_by,
                branch=getattr(order, 'branch', None) if getattr(order, 'branch', None) else None,
            )
            order_payment = OrderPayment.objects.create(
                order=order,
                payment=finance_payment,
                amount_applied=Decimal(str(amount)),
                notes=f"Payment processed via central orchestration service",
            )
            
            # 2. Record financial transaction if payment account is specified
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='income',
                    description=f"Payment for order {order.order_id}",
                    reference_type="order_payment",
                    reference_id=str(transaction_id),
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Sale',
                    ref_no=order.order_id,
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Payment for order {order.order_id}",
                    paid_by=created_by,
                    paid_to=order.created_by or created_by,
                    payment_date=payment_date
                )
            
            # 3. If order has a related billing document, update it too
            from finance.payment.models import BillingDocument
            related_invoice = BillingDocument.objects.filter(
                related_order=order,
                document_type=BillingDocument.INVOICE
            ).first()
            
            if related_invoice:
                # Update billing amounts inline
                related_invoice.add_payment(Decimal(str(amount)))
            
            # 4. Update order status based on payment
            self._update_order_status_after_payment(order)
            
            return True, "Payment processed successfully", order_payment
            
        except Exception as e:
            logger.error(f"Error processing order payment: {str(e)}")
            return False, str(e), None

    def initialize_payment_for_order(self, order, payment_method, payment_data=None):
        """
        Initialize a payment intent for an order via the centralized service.
        Returns a dict: { success, message, payment_id, method, redirect_url }
        """
        from finance.payment.models import Payment as FinancePayment

        payment_data = payment_data or {}
        if payment_method not in self.PAYMENT_METHODS:
            return { 'success': False, 'message': f"Unsupported payment method: {payment_method}" }

        try:
            init_txn_id = payment_data.get('transaction_id') or f"INIT-{uuid.uuid4().hex[:10]}"
            amount = Decimal(str(getattr(order, 'order_amount', 0) or 0))
            finance_payment = FinancePayment.objects.create(
                amount=amount,
                payment_method=payment_method,
                status='pending',
                reference_number=init_txn_id,
                transaction_id=init_txn_id,
                processor_response=payment_data,
                payment_date=timezone.now(),
                branch=getattr(order, 'branch', None) if order and getattr(order, 'branch', None) else None,
            )
            return {
                'success': True,
                'message': 'Payment initiated',
                'method': payment_method,
                'reference_number': finance_payment.reference_number,
                'redirect_url': payment_data.get('redirect_url'),
            }
        except Exception as e:
            logger.error(f"Failed to initialize payment: {str(e)}")
            return { 'success': False, 'message': f"Payment initialization failed: {str(e)}" }

    def get_available_payment_methods(self, order=None):
        """Return available payment methods (can be filtered per order later)."""
        return list(self.PAYMENT_METHODS.keys())

    # --- Gateway abstraction & reconciliation ---
    def _get_gateway(self, method: str):
        gateways = {
            'card': CardPaymentGateway(),
            'mpesa': MpesaPaymentGateway(),
        }
        return gateways.get(method)

    def reconcile_payment(self, payment: 'BillingPayment'):
        """Attempt to reconcile a payment by querying provider status if supported."""
        try:
            if not payment or not payment.payment_method:
                return False, 'Invalid payment', None
            gateway = self._get_gateway(payment.payment_method)
            if not gateway:
                return False, 'No gateway available for method', None
            status = gateway.reconcile(payment)
            if status and status.get('success'):
                # Optionally update raw response onto transaction record instead of JSONField if type constrained
                try:
                    payment.processor_response = status  # if JSONField
                except Exception:
                    pass
                if status.get('status') == 'succeeded':
                    payment.status = 'completed'
                payment.save()
                return True, 'Payment reconciled', status
            return False, status.get('error') if status else 'Reconcile failed', status
        except Exception as e:
            logger.error(f"Reconcile error: {str(e)}")
            return False, str(e), None

    def reconcile_payment_by_id(self, payment_id: int):
        from finance.payment.models import Payment as FinancePayment
        payment = FinancePayment.objects.filter(id=payment_id).first()
        if not payment:
            return False, 'Payment not found', None
        return self.reconcile_payment(payment)
    
    @transaction.atomic
    def process_pos_payment(self, sale, amount, payment_method, 
                           transaction_id=None, transaction_details=None,
                           created_by=None, payment_date=None):
        """
        Process a payment for a POS sale
        
        Args:
            sale: Sales instance
            amount: Decimal amount to pay
            payment_method: String payment method code
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, updated_sale)
        """
        if not isinstance(sale, Sales):
            return False, "Invalid sale object", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Update sale with payment information
            prev_amount_paid = sale.amount_paid
            sale.amount_paid = prev_amount_paid + Decimal(str(amount))
            sale.paymethod = payment_method
            
            # Update payment status
            if sale.amount_paid >= sale.grand_total:
                sale.payment_status = "Paid"
            elif sale.amount_paid > 0:
                sale.payment_status = "Partial"
            
            sale.save()
            
            # If M-Pesa, create transaction record
            # POS specific provider bookkeeping can be handled via integrations if required
            
            # Record financial transaction
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='income',
                    description=f"Payment for POS sale {sale.sale_id}",
                    reference_type="pos_sale",
                    reference_id=sale.sale_id or "",
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Sale',
                    ref_no=sale.sale_id or "",
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Payment for POS sale {sale.sale_id}",
                    paid_by=created_by or sale.attendant,
                    paid_to=sale.attendant or created_by,
                    payment_date=payment_date
                )
            
            return True, "Payment processed successfully", sale
            
        except Exception as e:
            logger.error(f"Error processing POS payment: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def process_purchase_payment(self, purchase, amount, payment_method, 
                               transaction_id=None, transaction_details=None,
                               created_by=None, payment_date=None):
        """
        Process a payment for a Purchase
        
        Args:
            purchase: Purchase instance
            amount: Decimal amount to pay
            payment_method: String payment method code
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, payment_object)
        """
        # Dynamic import to avoid circular imports
        from procurement.purchases.models import Purchase
        from finance.payment.models import Payment as FinancePayment
        
        if not isinstance(purchase, Purchase):
            return False, "Invalid purchase object", None
            
        if amount <= 0:
            return False, "Payment amount must be positive", None
            
        if payment_method not in self.PAYMENT_METHODS:
            return False, f"Unsupported payment method: {payment_method}", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"PUR-{payment_method.upper()}-{uuid.uuid4().hex[:8]}"
                
            # 1. Create Finance Payment record
            finance_payment = FinancePayment.objects.create(
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                status='completed',
                reference_number=transaction_id,
                transaction_id=transaction_id,
                processor_response=transaction_details or {},
                payment_date=payment_date,
                verified_by=created_by,
                branch=getattr(purchase, 'branch', None) if getattr(purchase, 'branch', None) else None,
            )
            
            # 2. Update purchase payment amounts
            prev_amount_paid = purchase.purchase_ammount or Decimal('0.00')
            purchase.purchase_ammount = prev_amount_paid + Decimal(str(amount))
            purchase.paymethod = payment_method
            
            # Update payment status
            if purchase.purchase_ammount >= purchase.grand_total:
                purchase.payment_status = "paid"
            elif purchase.purchase_ammount > 0:
                purchase.payment_status = "partial"
            
            purchase.save()
            
            # 3. Record financial transaction if payment account is specified
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='expense',  # Purchase payments are expenses
                    description=f"Payment for purchase {purchase.purchase_id}",
                    reference_type="purchase_payment",
                    reference_id=purchase.purchase_id or str(purchase.id),
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Purchase',
                    ref_no=purchase.purchase_id or str(purchase.id),
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Payment for purchase {purchase.purchase_id}",
                    paid_by=created_by,
                    paid_to=purchase.supplier.user if purchase.supplier else created_by,
                    payment_date=payment_date
                )
            
            return True, "Payment processed successfully", finance_payment
            
        except Exception as e:
            logger.error(f"Error processing purchase payment: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def process_employee_advance_payment(self, advance, amount, payment_method, 
                                       transaction_id=None, transaction_details=None,
                                       created_by=None, payment_date=None):
        """
        Process payment for employee advance repayment
        
        Args:
            advance: Advances instance
            amount: Decimal amount being repaid
            payment_method: String payment method code
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, payment_object)
        """
        # Dynamic import to avoid circular imports
        from hrm.payroll.models import Advances
        from finance.payment.models import Payment as FinancePayment
        
        if not isinstance(advance, Advances):
            return False, "Invalid advance object", None
            
        if amount <= 0:
            return False, "Payment amount must be positive", None
            
        if payment_method not in self.PAYMENT_METHODS:
            return False, f"Unsupported payment method: {payment_method}", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"ADV-{payment_method.upper()}-{uuid.uuid4().hex[:8]}"
                
            # 1. Create Finance Payment record
            finance_payment = FinancePayment.objects.create(
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                status='completed',
                reference_number=transaction_id,
                transaction_id=transaction_id,
                processor_response=transaction_details or {},
                payment_date=payment_date,
                verified_by=created_by,
            )
            
            # 2. Update advance repayment amount
            prev_amount_repaid = advance.amount_repaid or Decimal('0.00')
            advance.amount_repaid = prev_amount_repaid + Decimal(str(amount))
            
            # Update advance status
            if advance.amount_repaid >= advance.amount_issued:
                advance.is_active = False  # Advance fully repaid
            
            advance.save()
            
            # 3. Record financial transaction (income - employee repaying advance)
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='income',
                    description=f"Employee advance repayment - {advance.employee.user.get_full_name()}",
                    reference_type="employee_advance_repayment",
                    reference_id=str(advance.id),
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Employee Advance Repayment',
                    ref_no=str(advance.id),
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Advance repayment for {advance.employee.user.get_full_name()}",
                    paid_by=created_by,
                    paid_to=advance.employee.user,
                    payment_date=payment_date
                )
            
            return True, "Advance repayment processed successfully", finance_payment
            
        except Exception as e:
            logger.error(f"Error processing employee advance repayment: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def process_employee_loan_repayment(self, loan, amount, payment_method, 
                                      transaction_id=None, transaction_details=None,
                                      created_by=None, payment_date=None):
        """
        Process payment for employee loan repayment
        
        Args:
            loan: EmployeLoans instance
            amount: Decimal amount being repaid
            payment_method: String payment method code
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, payment_object)
        """
        # Dynamic import to avoid circular imports
        from hrm.payroll.models import EmployeLoans
        from finance.payment.models import Payment as FinancePayment
        
        if not isinstance(loan, EmployeLoans):
            return False, "Invalid loan object", None
            
        if amount <= 0:
            return False, "Payment amount must be positive", None
            
        if payment_method not in self.PAYMENT_METHODS:
            return False, f"Unsupported payment method: {payment_method}", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"LOAN-{payment_method.upper()}-{uuid.uuid4().hex[:8]}"
                
            # 1. Create Finance Payment record
            finance_payment = FinancePayment.objects.create(
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                status='completed',
                reference_number=transaction_id,
                transaction_id=transaction_id,
                processor_response=transaction_details or {},
                payment_date=payment_date,
                verified_by=created_by,
            )
            
            # 2. Update loan repayment amounts
            prev_principal_repaid = loan.amount_repaid or Decimal('0.00')
            prev_interest_paid = loan.interest_paid or Decimal('0.00')
            
            # Calculate principal vs interest (simple allocation for now)
            remaining_principal = loan.principal_amount - prev_principal_repaid
            if amount <= remaining_principal:
                loan.amount_repaid = prev_principal_repaid + Decimal(str(amount))
            else:
                # Amount covers remaining principal + interest
                loan.amount_repaid = loan.principal_amount
                excess_for_interest = amount - remaining_principal
                loan.interest_paid = prev_interest_paid + Decimal(str(excess_for_interest))
            
            # Update installment count
            monthly_installment = loan.monthly_installment or Decimal('1.00')
            if monthly_installment > 0:
                loan.no_of_installments_paid = int((loan.amount_repaid + loan.interest_paid) / monthly_installment)
            
            # Check if loan is fully paid
            total_paid = loan.amount_repaid + loan.interest_paid
            total_owed = loan.principal_amount + (loan.principal_amount * loan.interest_rate / 100)
            if total_paid >= total_owed:
                loan.is_active = False
            
            loan.save()
            
            # 3. Record financial transaction (income - employee repaying loan)
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='income',
                    description=f"Employee loan repayment - {loan.employee.user.get_full_name()}",
                    reference_type="employee_loan_repayment",
                    reference_id=str(loan.id),
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Employee Loan Repayment',
                    ref_no=str(loan.id),
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Loan repayment for {loan.employee.user.get_full_name()}",
                    paid_by=created_by,
                    paid_to=loan.employee.user,
                    payment_date=payment_date
                )
            
            return True, "Loan repayment processed successfully", finance_payment
            
        except Exception as e:
            logger.error(f"Error processing employee loan repayment: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def process_employee_expense_payment(self, expense_claim, amount, payment_method, 
                                       transaction_id=None, transaction_details=None,
                                       created_by=None, payment_date=None):
        """
        Process payment for employee expense claim
        
        Args:
            expense_claim: ExpenseClaims instance
            amount: Decimal amount being paid
            payment_method: String payment method code
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, payment_object)
        """
        # Dynamic import to avoid circular imports
        from hrm.payroll.models import ExpenseClaims
        from finance.payment.models import Payment as FinancePayment
        
        if not isinstance(expense_claim, ExpenseClaims):
            return False, "Invalid expense claim object", None
            
        if amount <= 0:
            return False, "Payment amount must be positive", None
            
        if payment_method not in self.PAYMENT_METHODS:
            return False, f"Unsupported payment method: {payment_method}", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"EXP-{payment_method.upper()}-{uuid.uuid4().hex[:8]}"
                
            # 1. Create Finance Payment record
            finance_payment = FinancePayment.objects.create(
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                status='completed',
                reference_number=transaction_id,
                transaction_id=transaction_id,
                processor_response=transaction_details or {},
                payment_date=payment_date,
                verified_by=created_by,
            )
            
            # 2. Update expense claim payment status
            expense_claim.is_paid = True
            expense_claim.payment_date = payment_date.date()
            expense_claim.save()
            
            # 3. Record financial transaction (expense - reimbursing employee)
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='expense',
                    description=f"Employee expense reimbursement - {expense_claim.employee.user.get_full_name()}",
                    reference_type="employee_expense_reimbursement",
                    reference_id=str(expense_claim.id),
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Employee Expense',
                    ref_no=str(expense_claim.id),
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Expense reimbursement for {expense_claim.employee.user.get_full_name()}",
                    paid_by=created_by,
                    paid_to=expense_claim.employee.user,
                    payment_date=payment_date
                )
            
            return True, "Expense reimbursement processed successfully", finance_payment
            
        except Exception as e:
            logger.error(f"Error processing employee expense reimbursement: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def record_employee_salary_payment(self, payslip, payment_method='bank',
                                     transaction_id=None, transaction_details=None,
                                     created_by=None, payment_date=None):
        """
        Record salary payment in finance system
        
        Args:
            payslip: Payslip instance
            payment_method: String payment method code
            transaction_id: Optional external transaction ID
            transaction_details: Optional dict with additional details
            created_by: User who recorded the payment
            payment_date: Optional date, defaults to now
            
        Returns:
            (success, message, payment_object)
        """
        # Dynamic import to avoid circular imports
        from hrm.payroll.models import Payslip
        from finance.payment.models import Payment as FinancePayment
        
        if not isinstance(payslip, Payslip):
            return False, "Invalid payslip object", None
            
        amount = payslip.net_pay
        if amount <= 0:
            return False, "Payslip net pay must be positive", None
            
        if payment_method not in self.PAYMENT_METHODS:
            return False, f"Unsupported payment method: {payment_method}", None
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"SAL-{payment_method.upper()}-{uuid.uuid4().hex[:8]}"
                
            # 1. Create Finance Payment record
            finance_payment = FinancePayment.objects.create(
                amount=amount,
                payment_method=payment_method,
                status='completed',
                reference_number=transaction_id,
                transaction_id=transaction_id,
                processor_response=transaction_details or {},
                payment_date=payment_date,
                verified_by=created_by,
            )
            
            # 2. Update payslip status (mark as paid)
            payslip.payroll_status = 'complete'
            payslip.save()
            
            # 3. Record financial transaction (expense - salary payment)
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=amount,
                    transaction_type='expense',
                    description=f"Salary payment - {payslip.employee.user.get_full_name()} ({payslip.payment_period.strftime('%B %Y')})",
                    reference_type="employee_salary_payment",
                    reference_id=str(payslip.id),
                    created_by=created_by
                )
                
                # Create TransactionPayment record for accounting
                trans_payment = TransactionPayment.objects.create(
                    transaction_type='Employee Salary',
                    ref_no=str(payslip.id),
                    amount_paid=amount,
                    payment_method=payment_method,
                    payment_account=self.payment_account,
                    payment_note=f"Salary payment for {payslip.employee.user.get_full_name()}",
                    paid_by=created_by,
                    paid_to=payslip.employee.user,
                    payment_date=payment_date
                )
            
            return True, "Salary payment recorded successfully", finance_payment
            
        except Exception as e:
            logger.error(f"Error recording employee salary payment: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def record_payroll_deduction_income(self, employee, deduction_components, 
                                      transaction_id=None, payment_date=None, created_by=None):
        """
        Record only company deductions as income in finance system
        
        This should be called during payroll processing when deductions are calculated.
        Only records deductions that represent money coming back to the company
        (advances, loans, losses) - NOT statutory deductions (PAYE, NHIF, NSSF, etc.)
        
        Args:
            employee: Employee instance
            deduction_components: List of deduction dictionaries with 'component' and 'amount'
            transaction_id: Optional external transaction ID
            payment_date: Optional date, defaults to now
            created_by: User who recorded the transaction
            
        Returns:
            (success, message, total_company_income_recorded)
        """
        # Statutory deductions that should NOT be recorded as company income
        STATUTORY_DEDUCTIONS = {
            'P.A.Y.E', 'PAYE', 'Income Tax', 'Tax',
            'N.H.I.F', 'NHIF', 'SHIF', 'Health Insurance',
            'N.S.S.F', 'NSSF', 'Social Security',
            'Housing Levy', 'Housing Fund',
            'N.I.T.A', 'NITA', 'Training Levy'
        }
        
        # Company deductions that SHOULD be recorded as income
        COMPANY_DEDUCTIONS = {
            'Advance Pay', 'Advance', 'Salary Advance',
            'Losses/Damages', 'Losses', 'Damages', 'Company Losses',
            'P.A.Y.E Arrears', 'PAYE Arrears', 'Tax Arrears',
            'Rent Recovered', 'Rent Recovery',
            'Loan Repayment', 'Company Loan'
        }
        
        total_company_income = Decimal('0.00')
        
        for deduction in deduction_components:
            component_title = deduction.get('component', '').strip()
            amount = Decimal(str(deduction.get('amount', '0')))
            
            if amount <= 0:
                continue
                
            # Skip statutory deductions (money going to government/external entities)
            if any(statutory in component_title.upper() for statutory in STATUTORY_DEDUCTIONS):
                continue
                
            # Only record company deductions as income
            if any(company in component_title for company in COMPANY_DEDUCTIONS):
                total_company_income += amount
        
        # If no company deductions, return early
        if total_company_income <= 0:
            return True, "No company deductions to record as income", Decimal('0.00')
            
        try:
            # Set payment date if not provided
            if not payment_date:
                payment_date = timezone.now()
                
            # Generate transaction ID if not provided
            if not transaction_id:
                transaction_id = f"PCD-{uuid.uuid4().hex[:8]}"
                
            # Record financial transaction (income - company deductions only)
            if self.payment_account:
                transaction = Transaction.objects.create(
                    account=self.payment_account,
                    transaction_date=payment_date,
                    amount=total_company_income,
                    transaction_type='income',
                    description=f"Company deductions - {employee.user.get_full_name()}",
                    reference_type="payroll_company_deductions_income",
                    reference_id=f"{employee.id}-{payment_date.strftime('%Y%m%d')}",
                    created_by=created_by
                )
                
                return True, f"Company deductions income recorded: KES {total_company_income}", total_company_income
            else:
                return False, "No payment account configured", Decimal('0.00')
            
        except Exception as e:
            logger.error(f"Error recording payroll company deductions income: {str(e)}")
            return False, str(e), Decimal('0.00')
    
    @transaction.atomic
    def process_bill_payment(self, document, amount, payment_method,
                            reference=None, notes=None, created_by=None, 
                            payment_date=None, account=None):
        try:
            from finance.payment.models import BillingDocument
            
            if not isinstance(document, BillingDocument):
                return False, "Invalid document object", None
                
            # Use orchestration service's account if none provided
            account = account or self.payment_account
            
            # Register the payment
            payment = document.register_payment(
                amount=Decimal(str(amount)),
                payment_method=payment_method,
                payment_date=payment_date or timezone.now(),
                reference=reference,
                notes=notes or "Payment processed via central orchestration",
                account=account,
                created_by=created_by
            )
            
            return True, "Payment processed successfully", payment
            
        except Exception as e:
            logger.error(f"Error processing bill payment: {str(e)}")
            return False, str(e), None
    
    @transaction.atomic
    def process_mpesa_payment(self, phone_number, amount, reference_id,
                             mpesa_receipt=None, entity_type=None, entity_id=None, 
                             created_by=None):
        """
        Process an M-Pesa payment for any entity type
        
        Args:
            phone_number: Customer phone number
            amount: Decimal amount paid
            reference_id: Reference ID (order_id, invoice_number, etc.)
            mpesa_receipt: M-Pesa receipt number (optional)
            entity_type: Type of entity ('order', 'invoice', 'pos_sale')
            entity_id: ID of the entity
            created_by: User who processed payment
            
        Returns:
            (success, message, payment_object)
        """
        try:
            # Generate M-Pesa receipt if not provided
            if not mpesa_receipt:
                mpesa_receipt = f"MPR{uuid.uuid4().hex[:8].upper()}"
                
            payment_date = timezone.now()
            transaction_details = {
                'phone_number': phone_number,
                'mpesa_receipt': mpesa_receipt,
                'processed_at': payment_date.isoformat()
            }
            
            # Process based on entity type
            if entity_type == 'order':
                # Dynamic import to avoid circular imports
                from ecommerce.order.models import Order
                try:
                    order = Order.objects.get(order_id=entity_id or reference_id)
                    return self.process_order_payment(
                        order=order,
                        amount=amount,
                        payment_method='mpesa',
                        transaction_id=mpesa_receipt,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except Order.DoesNotExist:
                    return False, f"Order not found: {entity_id or reference_id}", None
                    
            elif entity_type == 'invoice':
                from finance.payment.models import BillingDocument
                try:
                    invoice = BillingDocument.objects.get(document_number=entity_id or reference_id)
                    return self.process_bill_payment(
                        document=invoice,
                        amount=amount,
                        payment_method='mpesa',
                        reference=mpesa_receipt,
                        notes=f"M-Pesa payment from {phone_number}",
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except BillingDocument.DoesNotExist:
                    return False, f"Invoice not found: {entity_id or reference_id}", None
                    
            elif entity_type == 'pos_sale':
                try:
                    sale = Sales.objects.get(sale_id=entity_id or reference_id)
                    return self.process_pos_payment(
                        sale=sale,
                        amount=amount,
                        payment_method='mpesa',
                        transaction_id=mpesa_receipt,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except Sales.DoesNotExist:
                    return False, f"Sale not found: {entity_id or reference_id}", None
            
            elif entity_type == 'purchase':
                try:
                    from procurement.purchases.models import Purchase
                    purchase = Purchase.objects.get(purchase_id=entity_id or reference_id)
                    return self.process_purchase_payment(
                        purchase=purchase,
                        amount=amount,
                        payment_method='mpesa',
                        transaction_id=mpesa_receipt,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except Purchase.DoesNotExist:
                    return False, f"Purchase not found: {entity_id or reference_id}", None
                    
            elif entity_type == 'employee_advance':
                try:
                    from hrm.payroll.models import Advances
                    advance = Advances.objects.get(id=entity_id or reference_id)
                    return self.process_employee_advance_payment(
                        advance=advance,
                        amount=amount,
                        payment_method='mpesa',
                        transaction_id=mpesa_receipt,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except Advances.DoesNotExist:
                    return False, f"Employee advance not found: {entity_id or reference_id}", None
                    
            elif entity_type == 'employee_loan':
                try:
                    from hrm.payroll.models import EmployeLoans
                    loan = EmployeLoans.objects.get(id=entity_id or reference_id)
                    return self.process_employee_loan_repayment(
                        loan=loan,
                        amount=amount,
                        payment_method='mpesa',
                        transaction_id=mpesa_receipt,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except EmployeLoans.DoesNotExist:
                    return False, f"Employee loan not found: {entity_id or reference_id}", None
                    
            elif entity_type == 'employee_expense':
                try:
                    from hrm.payroll.models import ExpenseClaims
                    expense = ExpenseClaims.objects.get(id=entity_id or reference_id)
                    return self.process_employee_expense_payment(
                        expense_claim=expense,
                        amount=amount,
                        payment_method='mpesa',
                        transaction_id=mpesa_receipt,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                except ExpenseClaims.DoesNotExist:
                    return False, f"Employee expense not found: {entity_id or reference_id}", None
            
            # No matching entity found
            return False, f"Unsupported entity type: {entity_type}", None
                
        except Exception as e:
            logger.error(f"Error processing M-Pesa payment: {str(e)}")
            return False, str(e), None

    @transaction.atomic
    # Airtel Money support removed per business requirements (only M-Pesa allowed)

    # --- Mobile Money initiation (centralized) ---
    def initiate_mpesa_stk_push(self, order, phone_number, amount=None, description=None):
        """Initiate M-Pesa STK push using centralized integrations settings."""
        try:
            from integrations.payments.mpesa_payment import MpesaPaymentService
            if amount is None:
                # default to order balance
                amount = getattr(order, 'balance_due', None) or getattr(order, 'order_amount', None)
            ok, msg, data = MpesaPaymentService.initiate_stk_push(
                phone=phone_number,
                amount=Decimal(str(amount)),
                account_reference=getattr(order, 'order_id', None) or getattr(order, 'order_number', ''),
                description=description or f"Payment for order {getattr(order, 'order_id', '')}"
            )
            return ok, msg, data
        except Exception as e:
            logger.error(f"Failed to initiate M-Pesa STK push: {str(e)}")
            return False, str(e), None

    def query_mpesa_stk_status(self, checkout_id, password, timestamp):
        """Query M-Pesa STK push status via integrations service."""
        try:
            from integrations.payments.mpesa_payment import MpesaPaymentService
            ok, msg, data = MpesaPaymentService.query_stk_status(
                checkout_id=checkout_id,
                password=password,
                timestamp=timestamp,
            )
            return ok, msg, data
        except Exception as e:
            logger.error(f"Failed to query M-Pesa STK status: {str(e)}")
            return False, str(e), None
    
    def _update_order_status_after_payment(self, order):
        """Update order status based on payment amount"""
        # Refresh order from database to get updated payment amounts
        order.refresh_from_db()
        
        # Check if fully paid
        if order.balance_due <= 0:
            if order.status == 'pending':
                order.status = 'confirmed'
                order.confirmed_at = timezone.now()
            order.payment_status = 'paid'
        elif order.amount_paid > 0:
            order.payment_status = 'partial'
        
        order.save()
        
    def verify_mpesa_callback(self, callback_data):
        """
        Process M-Pesa callback data
        
        Args:
            callback_data: Dict containing callback data from M-Pesa
            
        Returns:
            (success, message, entity_updated)
        """
        try:
            # For Safaricom M-Pesa
            result_code = callback_data.get("ResultCode", 1)
            mpesa_receipt = callback_data.get("MpesaReceiptNumber", "")
            amount = Decimal(str(callback_data.get("Amount", 0)))
            phone = callback_data.get("PhoneNumber", "")
            bill_ref_number = callback_data.get("BillRefNumber", "")
            
            # If successful payment
            if result_code == 0:
                # Try to match with an order first
                # Dynamic import to avoid circular imports
                from ecommerce.order.models import Order
                order = Order.objects.filter(order_id=bill_ref_number).first()
                if order:
                    return self.process_mpesa_payment(
                        phone_number=phone,
                        amount=amount,
                        reference_id=bill_ref_number,
                        mpesa_receipt=mpesa_receipt,
                        entity_type='order',
                        entity_id=bill_ref_number,
                        created_by=None
                    )
                
                # Try to match with a sale
                sale = Sales.objects.filter(sale_id=bill_ref_number).first()
                if sale:
                    return self.process_mpesa_payment(
                        phone_number=phone,
                        amount=amount,
                        reference_id=bill_ref_number,
                        mpesa_receipt=mpesa_receipt,
                        entity_type='pos_sale',
                        entity_id=bill_ref_number,
                        created_by=None
                    )
                
                # Try to match with an invoice
                from finance.payment.models import BillingDocument
                invoice = BillingDocument.objects.filter(document_number=bill_ref_number).first()
                if invoice:
                    return self.process_mpesa_payment(
                        phone_number=phone,
                        amount=amount,
                        reference_id=bill_ref_number,
                        mpesa_receipt=mpesa_receipt,
                        entity_type='invoice',
                        entity_id=bill_ref_number,
                        created_by=None
                    )
                
                # Try to match with a purchase
                try:
                    from procurement.purchases.models import Purchase
                    purchase = Purchase.objects.filter(purchase_id=bill_ref_number).first()
                    if purchase:
                        return self.process_mpesa_payment(
                            phone_number=phone,
                            amount=amount,
                            reference_id=bill_ref_number,
                            mpesa_receipt=mpesa_receipt,
                            entity_type='purchase',
                            entity_id=bill_ref_number,
                            created_by=None
                        )
                except:
                    pass
                
                # Try to match with employee entities
                # Employee Advance
                try:
                    from hrm.payroll.models import Advances
                    advance = Advances.objects.filter(id=bill_ref_number).first()
                    if advance:
                        return self.process_mpesa_payment(
                            phone_number=phone,
                            amount=amount,
                            reference_id=bill_ref_number,
                            mpesa_receipt=mpesa_receipt,
                            entity_type='employee_advance',
                            entity_id=bill_ref_number,
                            created_by=None
                        )
                except:
                    pass
                    
                # Employee Loan
                try:
                    from hrm.payroll.models import EmployeLoans
                    loan = EmployeLoans.objects.filter(id=bill_ref_number).first()
                    if loan:
                        return self.process_mpesa_payment(
                            phone_number=phone,
                            amount=amount,
                            reference_id=bill_ref_number,
                            mpesa_receipt=mpesa_receipt,
                            entity_type='employee_loan',
                            entity_id=bill_ref_number,
                            created_by=None
                        )
                except:
                    pass
                    
                # Employee Expense
                try:
                    from hrm.payroll.models import ExpenseClaims
                    expense = ExpenseClaims.objects.filter(id=bill_ref_number).first()
                    if expense:
                        return self.process_mpesa_payment(
                            phone_number=phone,
                            amount=amount,
                            reference_id=bill_ref_number,
                            mpesa_receipt=mpesa_receipt,
                            entity_type='employee_expense',
                            entity_id=bill_ref_number,
                            created_by=None
                        )
                except:
                    pass
                
                # No matching entity found
                return False, f"No matching order, sale, invoice, purchase, or employee entity found for reference: {bill_ref_number}", None
                
            else:
                return False, f"M-Pesa payment failed with code: {result_code}", None
                
        except Exception as e:
            logger.error(f"Error processing M-Pesa callback: {str(e)}")
            return False, str(e), None


    @transaction.atomic
    def process_split_payment(self, entity_type, entity_id, payments, created_by=None, payment_date=None):
        """
        Process multiple payment methods for a single entity (split payment)
        
        Args:
            entity_type: Type of entity ('order', 'invoice', 'pos_sale')
            entity_id: ID of the entity
            payments: List of payment dictionaries, each containing:
                - amount: Payment amount
                - payment_method: Payment method code
                - transaction_id: Optional transaction ID
                - transaction_details: Optional additional details
                - payment_account_id: Optional specific payment account to use
            created_by: User who created the payment
            payment_date: Optional payment date (defaults to now)
            
        Returns:
            (success, message, [payment_records])
        """
        if not payments or not isinstance(payments, list):
            return False, "No payment records provided or invalid format", None
            
        if not payment_date:
            payment_date = timezone.now()
            
        # Validate total payment amount against entity balance
        total_payment = sum(Decimal(str(p.get('amount', 0))) for p in payments)
        
        # Get the entity based on the entity type
        entity = None
        if entity_type == 'order':
            try:
                from ecommerce.order.models import Order as _Order
                entity = _Order.objects.get(order_id=entity_id)
                if total_payment > entity.balance_due:
                    return False, f"Total payment amount (${total_payment}) exceeds order balance (${entity.balance_due})", None
            except Exception:
                return False, f"Order with ID {entity_id} not found", None
                
        elif entity_type == 'invoice':
            try:
                from finance.payment.models import BillingDocument as _BillingDocument
                entity = _BillingDocument.objects.get(document_number=entity_id)
                if total_payment > entity.balance_due:
                    return False, f"Total payment amount (${total_payment}) exceeds invoice balance (${entity.balance_due})", None
            except Exception:
                return False, f"Invoice with number {entity_id} not found", None
                
        elif entity_type == 'pos_sale':
            try:
                from ecommerce.pos.models import Sales as _Sales
                entity = _Sales.objects.get(sale_id=entity_id)
                balance = entity.grand_total - entity.amount_paid
                if total_payment > balance:
                    return False, f"Total payment amount (${total_payment}) exceeds sale balance (${balance})", None
            except Exception:
                return False, f"Sale with ID {entity_id} not found", None
                
        elif entity_type == 'purchase':
            try:
                from procurement.purchases.models import Purchase as _Purchase
                entity = _Purchase.objects.get(purchase_id=entity_id)
                balance = entity.grand_total - (entity.purchase_ammount or Decimal('0.00'))
                if total_payment > balance:
                    return False, f"Total payment amount (${total_payment}) exceeds purchase balance (${balance})", None
            except Exception:
                return False, f"Purchase with ID {entity_id} not found", None
                
        elif entity_type == 'employee_advance':
            try:
                from hrm.payroll.models import Advances as _Advances
                entity = _Advances.objects.get(id=entity_id)
                balance = entity.amount_issued - (entity.amount_repaid or Decimal('0.00'))
                if total_payment > balance:
                    return False, f"Total payment amount (${total_payment}) exceeds advance balance (${balance})", None
            except Exception:
                return False, f"Employee advance with ID {entity_id} not found", None
                
        elif entity_type == 'employee_loan':
            try:
                from hrm.payroll.models import EmployeLoans as _EmployeLoans
                entity = _EmployeLoans.objects.get(id=entity_id)
                total_owed = entity.principal_amount + (entity.principal_amount * entity.interest_rate / 100)
                total_paid = (entity.amount_repaid or Decimal('0.00')) + (entity.interest_paid or Decimal('0.00'))
                balance = total_owed - total_paid
                if total_payment > balance:
                    return False, f"Total payment amount (${total_payment}) exceeds loan balance (${balance})", None
            except Exception:
                return False, f"Employee loan with ID {entity_id} not found", None
                
        elif entity_type == 'employee_expense':
            try:
                from hrm.payroll.models import ExpenseClaims as _ExpenseClaims
                entity = _ExpenseClaims.objects.get(id=entity_id)
                if total_payment > entity.amount:
                    return False, f"Total payment amount (${total_payment}) exceeds expense amount (${entity.amount})", None
            except Exception:
                return False, f"Employee expense with ID {entity_id} not found", None
        else:
            return False, f"Unsupported entity type: {entity_type}", None
            
        # Process each payment method
        payment_records = []
        success_count = 0
        
        for payment in payments:
            amount = Decimal(str(payment.get('amount', 0)))
            if amount <= 0:
                continue  # Skip zero or negative amounts
                
            payment_method = payment.get('payment_method')
            if payment_method not in self.PAYMENT_METHODS:
                continue  # Skip invalid payment methods
                
            transaction_id = payment.get('transaction_id')
            transaction_details = payment.get('transaction_details', {})
            
            # Get payment account for this specific payment if provided
            payment_account = None
            payment_account_id = payment.get('payment_account_id')
            if payment_account_id:
                try:
                    payment_account = PaymentAccounts.objects.get(id=payment_account_id)
                except PaymentAccounts.DoesNotExist:
                    payment_account = self.payment_account
            else:
                payment_account = self.payment_account
                
            # Temporarily set the payment account for this transaction
            original_account = self.payment_account
            self.payment_account = payment_account
            
            # Process the payment based on entity type
            success = False
            payment_record = None
            
            try:
                if entity_type == 'order':
                    success, message, payment_record = self.process_order_payment(
                        order=entity,
                        amount=amount,
                        payment_method=payment_method,
                        transaction_id=transaction_id,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                elif entity_type == 'invoice':
                    success, message, payment_record = self.process_bill_payment(
                        document=entity,
                        amount=amount,
                        payment_method=payment_method,
                        reference=transaction_id,
                        notes=transaction_details.get('notes', "Split payment"),
                        created_by=created_by,
                        payment_date=payment_date
                    )
                elif entity_type == 'pos_sale':
                    success, message, payment_record = self.process_pos_payment(
                        sale=entity,
                        amount=amount,
                        payment_method=payment_method,
                        transaction_id=transaction_id,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                elif entity_type == 'purchase':
                    success, message, payment_record = self.process_purchase_payment(
                        purchase=entity,
                        amount=amount,
                        payment_method=payment_method,
                        transaction_id=transaction_id,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                elif entity_type == 'employee_advance':
                    success, message, payment_record = self.process_employee_advance_payment(
                        advance=entity,
                        amount=amount,
                        payment_method=payment_method,
                        transaction_id=transaction_id,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                elif entity_type == 'employee_loan':
                    success, message, payment_record = self.process_employee_loan_repayment(
                        loan=entity,
                        amount=amount,
                        payment_method=payment_method,
                        transaction_id=transaction_id,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
                elif entity_type == 'employee_expense':
                    success, message, payment_record = self.process_employee_expense_payment(
                        expense_claim=entity,
                        amount=amount,
                        payment_method=payment_method,
                        transaction_id=transaction_id,
                        transaction_details=transaction_details,
                        created_by=created_by,
                        payment_date=payment_date
                    )
            except Exception as e:
                success = False
                # Log error but continue with other payments
                logger.error(f"Error processing payment: {str(e)}")
                
            # Restore original payment account
            self.payment_account = original_account
            
            if success and payment_record:
                payment_records.append(payment_record)
                success_count += 1
            
        # Return based on success rate
        if success_count == len(payments):
            return True, f"All {success_count} payments processed successfully", payment_records
        elif success_count > 0:
            return True, f"{success_count} of {len(payments)} payments processed successfully", payment_records
        else:
            return False, "All payments failed to process", payment_records

    def get_order_by_reference(self, entity_id=None, reference_id=None):
        """Get order by reference ID"""
        # Dynamic import to avoid circular imports
        from ecommerce.order.models import Order
        
        try:
            order = Order.objects.get(order_id=entity_id or reference_id)
            return order
        except Order.DoesNotExist:
            return None

# Create a default instance for easy importing
default_payment_service = PaymentOrchestrationService()

def get_payment_service(payment_account=None):
    """Get a payment service instance with the specified payment account"""
    if not payment_account:
        # Try to get default payment account
        try:
            payment_account = PaymentAccounts.objects.filter(name__icontains="mpesa").first() or \
                              PaymentAccounts.objects.first()
        except Exception as e:
            logger.error(f"Error getting default payment account: {str(e)}")
            payment_account = None
    
    return PaymentOrchestrationService(payment_account=payment_account)


class CardPaymentGateway:
    def reconcile(self, payment):
        try:
            if not payment.transaction_id:
                return {'success': False, 'error': 'Missing transaction_id'}
            res = CardPaymentService.verify_payment(payment.transaction_id)
            return {
                'success': res.get('success', False),
                'status': res.get('status'),
                'amount': str(res.get('amount')) if res.get('amount') is not None else None,
                'currency': res.get('currency'),
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}


class MpesaPaymentGateway:
    def reconcile(self, payment):
        # For M-Pesa we may not have a universal verify; rely on recorded callbacks
        # Provide a basic success indicator if transaction_id exists
        if payment.transaction_id:
            return {'success': True, 'status': 'recorded'}
        return {'success': False, 'error': 'Missing mpesa receipt'}

