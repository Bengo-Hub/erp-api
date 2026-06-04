"""
POST /api/v1/hrm/payroll/disburse/ — finalise an approved payroll period: post the GL
journal (via erp.payroll.processed) and disburse net pay through treasury.

Body: { "period": "2026-06", "outlet_id": "<uuid?>", "payslip_ids": [<id>...]? }
Selects approved, complete, non-deleted payslips for the period (optionally scoped to
an outlet via the employee's outlet_id, or an explicit payslip_ids list).
"""
from __future__ import annotations

from django.utils import timezone

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status

from .models import Payslip, ExpenseClaims
from .treasury_integration import publish_and_disburse


class PayrollDisburseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        period = (request.data.get("period") or "").strip()
        outlet_id = request.data.get("outlet_id") or getattr(request, "outlet_id", "") or ""
        payslip_ids = request.data.get("payslip_ids") or []
        if not period and not payslip_ids:
            return Response({"error": "period or payslip_ids is required"}, status=status.HTTP_400_BAD_REQUEST)

        tenant_id = getattr(request, "tenant_id", "") or ""

        qs = Payslip.objects.filter(approval_status="approved", payroll_status="complete", delete_status=False)
        # Tenant isolation: only ever disburse the requesting tenant's payslips. Guarded so legacy
        # single-tenant deployments (no tenant_id on the request) keep working unchanged.
        if tenant_id:
            qs = qs.filter(employee__organisation__tenant_id=tenant_id)
        if payslip_ids:
            qs = qs.filter(id__in=payslip_ids)
        if period:
            qs = qs.filter(payment_period__startswith=period[:7])
        if outlet_id:
            qs = qs.filter(employee__outlet_id=outlet_id)
        qs = qs.select_related("employee", "employee__user")

        payslips = list(qs)
        result = publish_and_disburse(payslips, tenant_id, outlet_id, period, request=request)

        # Once disbursed, mark the payroll-scheduled expense claims that fed these payslips as paid,
        # so a subsequent payroll run does not add them to gross again (idempotency for scheduled claims).
        if result.get("published"):
            employee_ids = [p.employee_id for p in payslips]
            if employee_ids:
                ExpenseClaims.objects.filter(
                    employee_id__in=employee_ids, schedule_to_payroll=True,
                    approved=True, is_paid=False, delete_status=False,
                ).update(is_paid=True, payment_date=timezone.now().date())

        code = status.HTTP_200_OK if result.get("published") else status.HTTP_400_BAD_REQUEST
        return Response(result, status=code)
