"""
Django management command to seed all payroll formulas
"""

from django.core.management.base import BaseCommand
from hrm.payroll_settings.services.formula_seeder import FormulaSeederService


class Command(BaseCommand):
    help = 'Seed all payroll formulas from 2018 to current'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force reseeding even if formulas exist',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be seeded without actually doing it',
        )

    def handle(self, *args, **options):
        force = options['force']
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No changes will be made')
            )
        
        self.stdout.write(
            self.style.SUCCESS('🌱 Starting payroll formula seeding...')
        )
        
        try:
            seeder = FormulaSeederService()
            
            if dry_run:
                self.stdout.write(
                    self.style.SUCCESS('✅ Dry run completed - formulas would be seeded')
                )
                return
            
            success = seeder.seed_all_formulas()
            
            if success:
                self.stdout.write(
                    self.style.SUCCESS('✅ All payroll formulas seeded successfully!')
                )
            else:
                self.stdout.write(
                    self.style.ERROR('❌ Error seeding payroll formulas')
                )
                
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error: {str(e)}')
            )
