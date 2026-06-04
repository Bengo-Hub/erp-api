"""
Link an ERP Bussiness to its auth-api tenant UUID (so SSO tenant context + scoping resolve).

The mss/Masterspace business was created with tenant_id=None. Resolve the auth tenant UUID from
auth-api (`GET /api/v1/tenants/by-slug/mss`) and pass it here.

    python manage.py link_business_tenant --name Masterspace --tenant-id <uuid>
"""
from django.core.management.base import BaseCommand, CommandError

from business.models import Bussiness


class Command(BaseCommand):
    help = "Set Bussiness.tenant_id for businesses matching a name (auth tenant linkage)."

    def add_arguments(self, parser):
        parser.add_argument("--name", required=True, help="Business name substring (icontains).")
        parser.add_argument("--tenant-id", required=True, help="Auth-api tenant UUID.")

    def handle(self, *args, **opts):
        qs = Bussiness.objects.filter(name__icontains=opts["name"])
        if not qs.exists():
            raise CommandError(f"No business matching name~='{opts['name']}'")
        updated = qs.update(tenant_id=opts["tenant_id"])
        for b in qs:
            self.stdout.write(self.style.SUCCESS(f"Linked '{b.name}' -> tenant {opts['tenant_id']}"))
        self.stdout.write(self.style.SUCCESS(f"Updated {updated} business row(s)."))
