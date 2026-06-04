"""
Seed tailored permission sets onto the ERP management roles (Django groups).

Root cause this fixes: only `staff` + `superusers` groups had permissions; roles like
`ceo, cto, finance_manager, procurement_manager, ict_officer` existed as EMPTY groups, so users
holding them resolved to zero permissions and were denied access in the UI despite "having the role".

ERP owns HR/payroll only (finance/procurement/etc. decomposed to other services), so titles map to
ERP-relevant permission sets. Idempotent and ADDITIVE — never strips existing perms.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# HR/payroll apps the ERP owns.
HR_APPS = [
    "employees", "payroll", "payroll_settings", "leave", "attendance",
    "training", "appraisals", "performance", "recruitment",
]
# System / settings / admin apps.
SYS_APPS = ["core", "business", "approvals", "authmanagement"]

VIEW = ["view"]
VAC = ["view", "add", "change"]
ALL = ["view", "add", "change", "delete"]

# role -> { app_label: [actions] }  (actions applied to every model in that app)
ROLE_SPECS = {
    # Self-service baseline.
    "staff": {
        "employees": VIEW, "payroll": VIEW, "leave": VAC, "attendance": VAC,
        "training": ["view", "add"], "appraisals": ["view", "add", "change"],
        "performance": VIEW, "recruitment": VIEW,
    },
    # Full HR operators.
    "hr_assistant": {a: VAC for a in HR_APPS},
    "hr_manager": {**{a: ALL for a in HR_APPS}, "approvals": VAC},
    # Payroll / finance (ERP finance == payroll).
    "payroll_manager": {"payroll": ALL, "payroll_settings": ALL, "approvals": VAC,
                        **{a: VIEW for a in HR_APPS if a not in ("payroll", "payroll_settings")}},
    "finance_manager": {"payroll": ["view", "change"], "payroll_settings": VIEW, "approvals": VAC,
                        **{a: VIEW for a in HR_APPS if a != "payroll"}},
    # Operations.
    "operations_manager": {**{a: VIEW for a in HR_APPS}, "attendance": ALL, "approvals": VAC},
    # ICT / system admins.
    "ict_manager": {**{a: VIEW for a in HR_APPS}, "authmanagement": ALL, "core": ALL,
                    "business": ALL, "approvals": ALL},
    "ict_officer": {**{a: VIEW for a in HR_APPS}, "authmanagement": VAC, "core": VIEW,
                    "business": VIEW, "approvals": VIEW},
    # Executives — broad read + approve.
    "ceo": {**{a: VIEW for a in HR_APPS}, "payroll": ["view", "change"], "approvals": VAC},
    "cto": {**{a: VIEW for a in HR_APPS}, "payroll": ["view", "change"], "approvals": VAC,
            "authmanagement": VIEW, "core": VIEW},
    # Directory / reporting roles.
    "procurement_manager": {a: VIEW for a in HR_APPS},
    "sales_manager": {a: VIEW for a in HR_APPS},
    "receptionist": {"employees": VIEW, "leave": VIEW, "attendance": VIEW},
    "secretary": {"employees": VIEW, "leave": VIEW, "attendance": VIEW},
}


class Command(BaseCommand):
    help = "Seed tailored permission sets onto ERP management roles (idempotent, additive)."

    def _grant(self, group, app_actions):
        granted = 0
        for app_label, actions in app_actions.items():
            cts = ContentType.objects.filter(app_label=app_label)
            for ct in cts:
                for action in actions:
                    perm = Permission.objects.filter(
                        content_type=ct, codename=f"{action}_{ct.model}"
                    ).first()
                    if perm:
                        group.permissions.add(perm)
                        granted += 1
        return granted

    def handle(self, *args, **opts):
        # Merge any duplicate case-variant 'Staff' group into 'staff'.
        staff, _ = Group.objects.get_or_create(name="staff")
        for dup in Group.objects.filter(name__iexact="staff").exclude(pk=staff.pk):
            for u in dup.user_set.all():
                u.groups.add(staff)
            dup.delete()
            self.stdout.write(self.style.WARNING(f"Merged duplicate group '{dup.name}' into 'staff'"))

        for role, spec in ROLE_SPECS.items():
            group, created = Group.objects.get_or_create(name=role)
            n = self._grant(group, spec)
            total = group.permissions.count()
            tag = "created" if created else "updated"
            self.stdout.write(self.style.SUCCESS(
                f"{role}: {tag}, +{n} resolved, {total} total permissions"))

        self.stdout.write(self.style.SUCCESS("RBAC role seeding complete."))
