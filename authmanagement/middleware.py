from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from authmanagement.models import CustomUser
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError
import logging

from business.models import BusinessLocation, Branch
from crm.contacts.models import Contact

logger = logging.getLogger(__name__)

class SiteWideConfigs:
    def __init__(self, get_response):
        self.get_response = get_response
        # Class-level flags to track initialization status
        self._roles_initialized = False
        self._admin_user_initialized = False
        self._walkin_users_initialized = False

    def __call__(self, request):
        # Only run initialization logic once per server startup
        if not self._roles_initialized:
            self._initialize_roles_and_permissions()
        
        if not self._admin_user_initialized:
            self._initialize_admin_user()
        
        # Always check if admin user exists, even if marked as initialized
        if self._admin_user_initialized:
            self._ensure_admin_user_exists()
        
        if not self._walkin_users_initialized:
            self._initialize_walkin_users()
        
        response = self.get_response(request)
        return response

    def _initialize_roles_and_permissions(self):
        """Initialize roles and permissions only if they don't exist"""
        try:
            # Check if roles already exist
            if Group.objects.exists():
                self._roles_initialized = True
                return
            
            # Create basic roles
            roles = ['admin', 'staff', 'procurement manager', 'HR Manager']
            for role in roles:
                Group.objects.get_or_create(name=role)
                logger.info(f"Created role: {role}")
            
            # Ensure 'superusers' group exists
            superusers_group, created = Group.objects.get_or_create(name='superusers')
            if created:
                logger.info("Created superusers group")
            
            # Assign all permissions to 'superusers' group
            if created or not superusers_group.permissions.exists():
                # Retrieve all permissions from all models
                content_types = ContentType.objects.all()
                permissions = Permission.objects.filter(content_type__in=content_types)
                superusers_group.permissions.set(permissions)
                logger.info(f"Assigned {permissions.count()} permissions to superusers group")
            
            self._roles_initialized = True
            logger.info("Roles and permissions initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing roles and permissions: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._roles_initialized = True

    def _initialize_admin_user(self):
        """Initialize admin user only if it doesn't exist"""
        try:
            # Check if admin user already exists
            if CustomUser.objects.filter(username='admin').exists() or CustomUser.objects.filter(email='admin@bengohub.co.ke').exists():
                self._admin_user_initialized = True
                return
            
            # Create new admin user
            admin_user = CustomUser.objects.create(
                username='admin',
                email='admin@bengohub.co.ke',
                password=make_password('@Super123'),
                first_name='Procure',
                middle_name='',
                last_name='Pro',
                is_active=True,
                is_staff=True,
                is_superuser=True
            )
            logger.info(f"Created new admin user: {admin_user.username}")
            
            # Add admin user to superusers group
            superusers_group = Group.objects.get(name='superusers')
            admin_user.groups.add(superusers_group)
            logger.info(f"Added admin user to superusers group: {admin_user.username}")
            
            self._admin_user_initialized = True
            logger.info("Admin user initialization completed successfully")
            
        except IntegrityError as e:
            logger.error(f"Error creating admin user: {str(e)}")
            # Try to get existing admin user
            admin_user = CustomUser.objects.filter(username='admin').first()
            if not admin_user:
                admin_user = CustomUser.objects.filter(email='admin@bengohub.co.ke').first()
            
            if admin_user:
                # Ensure admin user is in superusers group
                superusers_group = Group.objects.get(name='superusers')
                if not admin_user.groups.filter(name='superusers').exists():
                    admin_user.groups.add(superusers_group)
                    logger.info(f"Added existing admin user to superusers group: {admin_user.username}")
            
            # Mark as initialized to prevent repeated attempts
            self._admin_user_initialized = True
            
        except Exception as e:
            logger.error(f"Error initializing admin user: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._admin_user_initialized = True

    def _ensure_admin_user_exists(self):
        """Ensure admin user exists, reset flag if not"""
        try:
            if not CustomUser.objects.filter(username='admin').exists() and not CustomUser.objects.filter(email='admin@bengohub.co.ke').exists():
                logger.warning("Admin user not found despite being marked as initialized. Resetting flag.")
                self._admin_user_initialized = False
        except Exception as e:
            logger.error(f"Error checking admin user existence: {str(e)}")
            self._admin_user_initialized = False

    def _initialize_walkin_users(self):
        """Initialize walk-in users only if they don't exist"""
        try:
            # Check if walk-in users already exist
            if CustomUser.objects.filter(email__icontains='walkin').exists():
                self._walkin_users_initialized = True
                return
            
            # Process business branches and create walk-in users
            for branch in Branch.objects.select_related('business', 'location').all():
                try:
                    if branch.business and branch.location:
                        business_name = branch.business.name
                        # Create walk in customer
                        email = f'walkin{business_name.replace(" ","_").lower()}'
                        user = CustomUser.objects.filter(email__icontains=email).first()
                        if user is None:
                            try:
                                walk_in_user, created = CustomUser.objects.update_or_create(
                                    email=f'walkin{business_name.replace(" ","_").lower()}{branch.id}@gmail.com',
                                    defaults={
                                        "username": f'walkin{business_name.replace(" ","_").lower()}',
                                        "first_name": 'Walk-In',
                                        "last_name": business_name.replace(" ","_").lower(),
                                        "phone": '07000000000',
                                        "password": make_password("@User123"),
                                        "is_active": True
                                    }
                                )
                                walk_in_user.save()
                                walk_in_user.groups.add(Group.objects.get(name='admin'))
                                walk_in_user.save()
                                
                                # Create contact for walk-in user
                                Contact.objects.update_or_create(
                                    user=walk_in_user,
                                    contact_id=f'C{branch.id}000001',
                                    defaults={
                                        "branch": branch,  # Use the branch object directly
                                        "contact_type": 'Customers',
                                        "account_type": 'Individual',
                                        "designation": 'Other',
                                        "credit_limit": 0,
                                    }
                                )
                                logger.info(f"Created walk-in user for business: {business_name}")
                            except IntegrityError as e:
                                logger.error(f"Error creating walk-in user for business {business_name}: {str(e)}")
                                continue
                except Exception as e:
                    # Log the error but continue processing other locations
                    logger.error(f"Error processing business branch {branch.id}: {str(e)}")
                    continue
            
            self._walkin_users_initialized = True
            logger.info("Walk-in users initialization completed successfully")
            
        except Exception as e:
            logger.error(f"Error initializing walk-in users: {str(e)}")
            # Mark as initialized to prevent repeated attempts
            self._walkin_users_initialized = True
