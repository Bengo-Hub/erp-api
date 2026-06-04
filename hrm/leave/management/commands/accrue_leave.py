"""
Establish/refresh leave balances for a year with year-end carry-over.

For each active employee × active category, the year's entitlement is the category's
default_annual_days (or an explicit LeaveEntitlement override) PLUS carry-over from the prior
year's remaining balance (capped by max_carryover_days when allow_carryover is set).

    python manage.py accrue_leave --year 2026
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from hrm.employees.models import Employee
from hrm.leave.models import LeaveCategory, LeaveEntitlement, LeaveBalance


class Command(BaseCommand):
    help = "Create/refresh leave balances for a year, applying carry-over from the prior year."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, default=timezone.now().year)

    def handle(self, *args, **opts):
        year = opts["year"]
        prev = year - 1
        employees = Employee.objects.filter(deleted=False, terminated=False)
        categories = LeaveCategory.objects.filter(is_active=True)
        processed = 0

        for emp in employees:
            for cat in categories:
                entitlement = (LeaveEntitlement.objects
                               .filter(employee=emp, category=cat, year=year)
                               .values_list("days_entitled", flat=True).first())
                base = Decimal(entitlement) if entitlement is not None else Decimal(cat.default_annual_days or 0)

                carry = Decimal("0")
                if cat.allow_carryover:
                    prev_remaining = (LeaveBalance.objects
                                      .filter(employee=emp, category=cat, year=prev)
                                      .values_list("days_remaining", flat=True).first())
                    if prev_remaining:
                        carry = Decimal(prev_remaining)
                        if cat.max_carryover_days and cat.max_carryover_days > 0:
                            carry = min(carry, Decimal(cat.max_carryover_days))

                entitled = base + carry
                bal, _ = LeaveBalance.objects.get_or_create(
                    employee=emp, category=cat, year=year,
                    defaults={"days_entitled": entitled, "days_taken": Decimal("0"), "days_remaining": entitled},
                )
                # Refresh entitlement/remaining without clobbering already-taken days.
                bal.days_entitled = entitled
                bal.days_remaining = max(Decimal("0"), entitled - (bal.days_taken or Decimal("0")))
                bal.save(update_fields=["days_entitled", "days_remaining", "updated_at"])
                processed += 1

        self.stdout.write(self.style.SUCCESS(f"Accrued leave balances for {year}: {processed} rows."))
