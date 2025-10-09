from django.core.management.base import BaseCommand
from hrm.leave.scripts.create_sample_leave_data import create_sample_leave_data

class Command(BaseCommand):
    help = 'Generates sample leave data'

    def handle(self, *args, **options):
        create_sample_leave_data()
        self.stdout.write(self.style.SUCCESS('Successfully created sample leave data'))