"""
Payroll → treasury integration (reuse treasury's centralized payment + GL).

On payroll finalisation the ERP:
  1. publishes ``erp.payroll.processed`` (treasury subscriber posts the payroll GL
     journal: DR Salaries & Wages, CR Accrued Salary Payable + statutory liabilities), and
  2. calls treasury S2S ``POST /api/v1/s2s/{tenant}/payouts/disburse`` to pay net pay
     (M-Pesa/bank), then consumes ``treasury.payroll.disbursed`` to confirm.

Treasury is the single source of truth for money movement + GL — the ERP never posts
ledgers or moves cash itself (CROSS-SERVICE-DATA-OWNERSHIP.md: erp.payroll.processed → Treasury).
"""
from __future__ import annotations

import logging
from decimal import Decimal

from integrations.events import publish_event
from integrations.service_client import ServiceError, get_client

logger = logging.getLogger(__name__)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _line(p) -> dict:
    statutory = {
        "paye": _f(p.paye),
        "nhif": _f(p.shif_or_nhif_contribution),
        "nssf": _f(p.nssf_employee_tier_1) + _f(p.nssf_employee_tier_2),
        "housing": _f(p.housing_levy),
    }
    emp = p.employee
    return {
        "employee_id": str(getattr(getattr(emp, "user", None), "external_id", "") or emp.pk),
        "employee_ref": str(emp),
        "gross": _f(p.gross_pay),
        "net_pay": _f(p.net_pay),
        "statutory": statutory,
    }


def build_payroll_event(payslips, tenant_id: str, outlet_id: str, period: str) -> dict:
    lines = [_line(p) for p in payslips]
    gross = sum(l["gross"] for l in lines)
    net = sum(l["net_pay"] for l in lines)
    deductions = gross - net
    return {
        "tenant_id": str(tenant_id or ""),
        "outlet_id": str(outlet_id or ""),
        "period": period,
        "currency": "KES",
        "totals": {"gross": round(gross, 2), "deductions": round(deductions, 2), "net": round(net, 2)},
        "lines": lines,
        "cost_center": "",
        "batch_ref": f"payroll-{tenant_id or 'erp'}-{period}-{outlet_id or 'all'}",
    }


def publish_and_disburse(payslips, tenant_id: str, outlet_id: str, period: str, request=None) -> dict:
    """Publish erp.payroll.processed (GL) + request net-pay disbursement via treasury.

    Returns a summary dict. Best-effort on the S2S disburse call: a transport failure
    does not roll back the GL event (treasury reconciles), it is reported instead.
    """
    payslips = list(payslips)
    if not payslips:
        return {"published": False, "disbursed": False, "reason": "no payslips"}

    event = build_payroll_event(payslips, tenant_id, outlet_id, period)
    publish_event("payroll.processed", event, aggregate_type="erp",
                  aggregate_id=event["batch_ref"], tenant_id=tenant_id)

    payouts = [
        {
            "recipient_id": l["employee_id"],
            "amount": l["net_pay"],
            "currency": "KES",
            "payment_method": "bank_transfer",
            "reference_id": f"{event['batch_ref']}-{l['employee_id']}",
            "description": f"Salary {period} - {l['employee_ref']}",
        }
        for l in event["lines"] if l["net_pay"] > 0
    ]
    disbursed = False
    disburse_error = ""
    if tenant_id and payouts:
        try:
            client = get_client("treasury", request=request)
            client.post(f"/api/v1/s2s/{tenant_id}/payouts/disburse", json={"payouts": payouts})
            disbursed = True
        except ServiceError as exc:
            disburse_error = str(exc)
            logger.warning("payroll disburse failed (%s): %s", event["batch_ref"], exc)

    return {
        "published": True,
        "disbursed": disbursed,
        "batch_ref": event["batch_ref"],
        "count": len(payouts),
        "net_total": event["totals"]["net"],
        "disburse_error": disburse_error,
    }


def handle_payroll_disbursed(envelope: dict) -> None:
    """Consume ``treasury.payroll.disbursed`` → mark the period's payslips published/paid."""
    from .models import Payslip

    payload = (envelope or {}).get("payload", envelope) or {}
    period = payload.get("period", "")
    tenant_id = payload.get("tenant_id", "")
    if not period:
        logger.info("payroll.disbursed received without period; skipping (%s)", tenant_id)
        return
    try:
        qs = Payslip.objects.filter(payment_period__startswith=period[:7]) if len(period) >= 7 else Payslip.objects.none()
        # Tenant isolation: never mark another tenant's payslips paid from one tenant's event.
        if tenant_id:
            qs = qs.filter(employee__organisation__tenant_id=tenant_id)
        updated = qs.update(published=True)
        logger.info("payroll.disbursed: marked %s payslips published (period=%s, tenant=%s)", updated, period, tenant_id)
    except Exception as exc:  # pragma: no cover
        logger.warning("handle_payroll_disbursed error: %s", exc)
