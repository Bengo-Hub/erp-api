from django.db import transaction
from procurement.requisitions.models import PurchaseRequisition, RequisitionItem
from procurement.purchases.models import  Purchase, PurchaseItems
from core_orders.models import BaseOrder
from approvals.models import Approval

class PurchaseWorkflow:
    """Business logic for handling procurement workflow"""
    
    @classmethod
    def initiate_requisition(cls, user, items_data):
        """Manufacturing creates a new requisition"""
        with transaction.atomic():
            requisition = PurchaseRequisition.objects.create(
                requester=user,
                status='draft'
            )
            for item in items_data:
                RequisitionItem.objects.create(
                    requisition=requisition,
                    **item
                )
            return requisition

    @classmethod
    def submit_for_approval(cls, requisition_id):
        """Manufacturing submits requisition to procurement"""
        requisition = PurchaseRequisition.objects.get(id=requisition_id)
        requisition.status = 'procurement_review'
        requisition.save()
        # Send notification to procurement team
        return requisition

    @classmethod
    def process_procurement_review(cls, requisition_id, approver, decision, notes=None):
        """Procurement department reviews/approves requisition"""
        with transaction.atomic():
            requisition = PurchaseRequisition.objects.get(id=requisition_id)
            
            if decision == 'approved':
                requisition.status = 'approved'
                # Create purchase order
                po = BaseOrder.objects.create(
                    requisition=requisition,
                    status='draft',
                    procurement_approver=approver
                )
                # Copy approved items to purchase order
                for item in requisition.items.all():
                    Purchase.objects.create(
                        order=po,
                        stock_item=item.stock_item,
                        quantity=item.approved_quantity or item.quantity,
                        unit_price=item.stock_item.buying_price
                    )
            else:
                requisition.status = 'rejected'
                
            requisition.procurement_notes = notes
            requisition.save()
            return requisition

    @classmethod
    def process_finance_approval(cls, order_id, approver, decision, notes=None):
        """Finance department approves/rejects order"""
        with transaction.atomic():
            order = BaseOrder.objects.get(id=order_id)
            approval = Approval.objects.create(
                order=order,
                approver=approver,
                approval_type='finance',
                decision=decision,
                notes=notes
            )
            
            if decision == 'approved':
                order.status = 'finance_approved'
                order.finance_approver = approver
                order.save()
                # Create actual purchase record
                purchase = Purchase.objects.create(
                    supplier=order.supplier,
                    grand_total=order.approved_budget,
                    purchase_status='ordered',
                    payment_status='pending'
                )
                # Add purchase items
                for item in order.items.all():
                    PurchaseItems.objects.create(
                        purchase=purchase,
                        stock_item=item.stock_item,
                        qty=item.quantity,
                        unit_price=item.unit_price
                    )
                order.status = 'ordered'
                order.save()
            else:
                order.status = 'rejected'
                order.save()
            
            return order


