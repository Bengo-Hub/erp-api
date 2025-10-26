from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from authmanagement.models import CustomUser
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

class Command(BaseCommand):
    help = 'Creates the admin user for the system'

    def handle(self, *args, **options):
        self.stdout.write('Creating admin user...')
        
        try:
            # Check if admin user already exists
            if CustomUser.objects.filter(username='admin').exists():
                self.stdout.write(self.style.WARNING('Admin user already exists'))
                admin_user = CustomUser.objects.get(username='admin')
            elif CustomUser.objects.filter(email='admin@codevertexitsolutions.com').exists():
                self.stdout.write(self.style.WARNING('Admin user with email already exists'))
                admin_user = CustomUser.objects.get(email='admin@codevertexitsolutions.com')
            else:
                # Create new admin user
                admin_user = CustomUser.objects.create(
                    username='admin',
                    email='admin@codevertexitsolutions.com',
                    password=make_password('Demo@2020!'),
                    first_name='Super',
                    middle_name='',
                    last_name='User',
                    is_active=True,
                    is_staff=True,
                    is_superuser=True
                )
                self.stdout.write(self.style.SUCCESS(f'Created admin user: {admin_user.username}'))
            
            # Ensure superusers group exists
            superusers_group, created = Group.objects.get_or_create(name='superusers')
            if created:
                self.stdout.write(self.style.SUCCESS('Created superusers group'))
            
            # Add admin user to superusers group
            if not admin_user.groups.filter(name='superusers').exists():
                admin_user.groups.add(superusers_group)
                self.stdout.write(self.style.SUCCESS(f'Added admin user to superusers group'))
            
            # Assign all permissions to superusers group
            if not superusers_group.permissions.exists():
                content_types = ContentType.objects.all()
                permissions = Permission.objects.filter(content_type__in=content_types)
                superusers_group.permissions.set(permissions)
                self.stdout.write(self.style.SUCCESS(f'Assigned {permissions.count()} permissions to superusers group'))
            
            self.stdout.write(self.style.SUCCESS('Admin user setup completed successfully!'))
            self.stdout.write(f'Username: admin')
            self.stdout.write(f'Password: Demo@2020!')
            self.stdout.write(f'Email: admin@codevertexitsolutions.com')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating admin user: {str(e)}'))
            raise
