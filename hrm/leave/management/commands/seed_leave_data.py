from django.core.management.base import BaseCommand
from hrm.leave.scripts.create_sample_leave_data import create_sample_leave_data

class Command(BaseCommand):
    help = 'Generates sample leave data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minimal',
            action='store_true',
            help='Seed a minimal set of leave data (1 request)',
        )

    def handle(self, *args, **options):
        minimal = options.get('minimal')
        create_sample_leave_data(minimal=minimal)
        self.stdout.write(self.style.SUCCESS('Successfully created sample leave data'))