"""
Seed a demo business account for the CodeVertex ERP platform.
Creates:
  - Demo business: "CodeVertex Demo" with CodeVertex branding
  - Demo branch: "Demo HQ" branch
  - Demo user: demo@codevertexitsolutions.com / Demo@2025!
  - Platform owner org: "codevertex it solutions" (if not exists)

This is idempotent — safe to run multiple times.
Usage: python manage.py seed_demo_business
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Seed demo business and demo user for CodeVertex ERP"

    def handle(self, *args, **options):
        from business.models import Bussiness, Branch, BusinessLocation, BrandingSettings

        self.stdout.write("=== Seeding Demo Business ===")

        # 1. Ensure platform owner exists (codevertex it solutions)
        codevertex_owner = User.objects.filter(email="admin@codevertexitsolutions.com").first()
        if not codevertex_owner:
            codevertex_owner = User.objects.create_superuser(
                email="admin@codevertexitsolutions.com",
                password="Admin@2025!",
                first_name="Platform",
                last_name="Admin",
            )
            self.stdout.write(self.style.SUCCESS("  Created platform admin: admin@codevertexitsolutions.com"))

        codevertex_biz = Bussiness.objects.filter(name__iexact="codevertex it solutions").first()
        if not codevertex_biz:
            cv_location = BusinessLocation.objects.create(
                city="Nairobi", country="KE", county="Nairobi",
            )
            codevertex_biz = Bussiness.objects.create(
                owner=codevertex_owner,
                name="codevertex it solutions",
                location=cv_location,
                currency="KES",
                business_primary_color="#5B1C4D",
                business_secondary_color="#ea8022",
            )
            Branch.objects.create(
                business=codevertex_biz,
                name="CodeVertex HQ",
                branch_code="CV-HQ",
                location=cv_location,
                is_main_branch=True,
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS("  Created platform org: codevertex it solutions"))
        else:
            # Update brand colors if missing
            if not codevertex_biz.business_primary_color or codevertex_biz.business_primary_color == '#1976D2':
                codevertex_biz.business_primary_color = "#5B1C4D"
                codevertex_biz.business_secondary_color = "#ea8022"
                codevertex_biz.save(update_fields=["business_primary_color", "business_secondary_color"])

        # 2. Create demo business
        demo_biz = Bussiness.objects.filter(name__iexact="CodeVertex Demo").first()
        if not demo_biz:
            demo_location = BusinessLocation.objects.create(
                city="Nairobi", country="KE", county="Nairobi",
                street_name="Demo Street",
            )
            # Create demo owner user
            demo_user = User.objects.filter(email="demo@codevertexitsolutions.com").first()
            if not demo_user:
                demo_user = User.objects.create_user(
                    email="demo@codevertexitsolutions.com",
                    password="Demo@2025!",
                    first_name="Demo",
                    last_name="User",
                )
                self.stdout.write(self.style.SUCCESS("  Created demo user: demo@codevertexitsolutions.com / Demo@2025!"))

            demo_biz = Bussiness.objects.create(
                owner=demo_user,
                name="CodeVertex Demo",
                location=demo_location,
                currency="KES",
                business_primary_color="#5B1C4D",
                business_secondary_color="#ea8022",
            )
            demo_branch = Branch.objects.create(
                business=demo_biz,
                name="Demo Branch",
                branch_code="DEMO-HQ",
                location=demo_location,
                is_main_branch=True,
                is_active=True,
            )
            # Create branding settings
            BrandingSettings.objects.get_or_create(
                business=demo_biz,
                defaults={
                    "primary_color_name": "purple",
                    "surface_name": "slate",
                }
            )
            self.stdout.write(self.style.SUCCESS(f"  Created demo business: {demo_biz.name} (branch: {demo_branch.branch_code})"))
        else:
            self.stdout.write(f"  Demo business already exists: {demo_biz.name}")

        # 3. Ensure Masterspace Solutions business exists (for mss domain)
        mss_biz = Bussiness.objects.filter(name__icontains="masterspace").first()
        if not mss_biz:
            mss_owner = User.objects.filter(email="admin@masterspace.co.ke").first()
            if not mss_owner:
                mss_owner = User.objects.create_user(
                    email="admin@masterspace.co.ke",
                    password="Admin@2025!",
                    first_name="MSS",
                    last_name="Admin",
                )
            mss_location = BusinessLocation.objects.create(
                city="Nairobi", country="KE", county="Nairobi",
            )
            mss_biz = Bussiness.objects.create(
                owner=mss_owner,
                name="Masterspace Solutions Ltd",
                location=mss_location,
                currency="KES",
                business_primary_color="#1e3a5f",
                business_secondary_color="#f97316",
            )
            Branch.objects.create(
                business=mss_biz,
                name="MSS HQ",
                branch_code="MSS-HQ",
                location=mss_location,
                is_main_branch=True,
                is_active=True,
            )
            self.stdout.write(self.style.SUCCESS("  Created MSS business: Masterspace Solutions Ltd"))

        self.stdout.write(self.style.SUCCESS("=== Demo Business Seeding Complete ==="))
