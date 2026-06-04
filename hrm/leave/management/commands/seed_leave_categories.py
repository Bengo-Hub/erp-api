"""Seed standard Kenyan leave categories with accrual/carry-over defaults (idempotent)."""
from decimal import Decimal

from django.core.management.base import BaseCommand

from hrm.leave.models import LeaveCategory

# (name, annual_days, allow_carryover, max_carryover_days)
DEFAULT_CATEGORIES = [
    ("Annual Leave", Decimal("21"), True, Decimal("10")),
    ("Sick Leave", Decimal("14"), False, Decimal("0")),
    ("Maternity Leave", Decimal("90"), False, Decimal("0")),
    ("Paternity Leave", Decimal("14"), False, Decimal("0")),
    ("Compassionate Leave", Decimal("3"), False, Decimal("0")),
]


class Command(BaseCommand):
    help = "Seed standard Kenyan leave categories (idempotent)."

    def handle(self, *args, **opts):
        for name, days, carry, cap in DEFAULT_CATEGORIES:
            obj, created = LeaveCategory.objects.update_or_create(
                name=name,
                defaults={
                    "default_annual_days": days,
                    "allow_carryover": carry,
                    "max_carryover_days": cap,
                    "is_active": True,
                },
            )
            self.stdout.write(("Created " if created else "Updated ") + name)
        self.stdout.write(self.style.SUCCESS("Leave categories seeded."))
