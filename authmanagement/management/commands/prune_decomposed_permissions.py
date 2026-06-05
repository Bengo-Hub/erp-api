"""
Delete Django permissions for DECOMPOSED modules — models that were moved to other services
(treasury/finance, pos, inventory/products, procurement, manufacturing, crm, notifications,
assets, …). Those apps were removed from the ERP, but their Permission rows linger and were
granted to roles, so /auth/me returned permissions like `add_accounttypes`, `view_sales`, etc.

A permission is "stale" when its ContentType's model class no longer exists in the app registry
(`content_type.model_class() is None`). Deleting the Permission row cascades the role/user M2M
(auth_group_permissions / auth_user_user_permissions), so the perms drop off every role too.

The harmless stale ContentType rows are intentionally LEFT (they may be targets of GenericForeignKeys
e.g. approvals/audit, which we must not cascade-delete). Run with --apply to execute; default dry-run.

    python manage.py prune_decomposed_permissions            # dry run (report only)
    python manage.py prune_decomposed_permissions --apply    # delete
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission


class Command(BaseCommand):
    help = "Delete permissions for decomposed modules (stale ContentTypes). Dry-run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry run).")

    def handle(self, *args, **opts):
        stale_ct_ids = [ct.id for ct in ContentType.objects.all() if ct.model_class() is None]
        perms = Permission.objects.filter(content_type_id__in=stale_ct_ids).select_related("content_type")

        by_app = Counter(p.content_type.app_label for p in perms)
        total = perms.count()
        self.stdout.write(f"Stale ContentTypes: {len(stale_ct_ids)}  |  decomposed permissions: {total}")
        for app, n in sorted(by_app.items()):
            self.stdout.write(f"  {app}: {n}")

        if not opts["apply"]:
            self.stdout.write(self.style.WARNING("DRY RUN — re-run with --apply to delete."))
            return

        deleted, _ = perms.delete()  # cascades auth_group_permissions / auth_user_user_permissions
        remaining = Permission.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Deleted {total} decomposed permission(s) (and their role mappings). "
            f"Permissions remaining: {remaining}."))
