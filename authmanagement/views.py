from django.contrib.auth import authenticate,login,logout
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.db import models

from business.models import BusinessLocation, Bussiness
from addresses.models import AddressBook
from rest_framework.authtoken.models import Token
from rest_framework import generics
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework import permissions, authentication
from .serializers import *
from .models import *
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string
from django.utils.http import urlsafe_base64_decode,urlsafe_base64_encode
from rest_framework import status
from rest_framework.response import Response
from django.conf import settings
from notifications.services import EmailService
from django.http import Http404
#from django.contrib.sites.models import Site
from django.shortcuts import redirect,render
from django.contrib.auth import get_user_model
from rest_framework.generics import UpdateAPIView
from django.contrib.auth import update_session_auth_hash
from django.shortcuts import get_object_or_404
from django.utils.encoding import force_bytes
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, Permission
from django.utils import timezone
from django.db import transaction
import os
import subprocess
from datetime import datetime
import threading
from rest_framework import viewsets
from .serializers import UserSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

logger = logging.getLogger(__name__)

User = get_user_model()


class GroupViewSet(BaseModelViewSet):
    """ViewSet for managing user groups/roles"""
    queryset = Group.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    
    def list(self, request, *args, **kwargs):
        """List all groups"""
        groups = self.queryset.all()
        data = [{'id': g.id, 'name': g.name} for g in groups]
        return Response({
            'success': True,
            'results': data,
            'count': len(data)
        })
    
    def retrieve(self, request, pk=None, *args, **kwargs):
        """Get single group"""
        group = get_object_or_404(Group, pk=pk)
        return Response({
            'success': True,
            'data': {'id': group.id, 'name': group.name}
        })


class HODUserViewSet(BaseModelViewSet):
    queryset = User.objects.all().select_related('employee')
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

class RegistrationView(generics.CreateAPIView):
    permission_classes = ()
    serializer_class = UserSerializer
    
    # Exempt from CSRF for API registration
    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

class EmailConfirmView(APIView):
    permission_classes = ()
    authentication_classes=[]
    user = None
    
    # Exempt from CSRF for API email confirmation
    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, uidb64, token):
        try:
            id = urlsafe_base64_decode(uidb64)
            print(id)
            user = User.objects.get(pk=id)
            print(token, '\n', user.email_confirm_token)
        except User.DoesNotExist:
            return Response({'error': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)
        if user != None and token == user.email_confirm_token:
            user.is_active = True
            print(user)
            user.save()
            return redirect('email_confirm_success')
        return Response({'error': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)
    
def email_confirm_success(request):
    site_url = ''#Site.objects.filter(name='procurepro.co.ke').first()
    return render(request,'auth/email_confirm_success.html',{'site_url':site_url.domain,'site_name':site_url.name})

class ForgotPasswordView(generics.CreateAPIView):
    """
    Production-ready password reset request endpoint.
    Sends a secure password reset email with proper branding and URL configuration.
    """
    permission_classes = ()
    authentication_classes = []
    serializer_class = ForgotPasswordSerializer

    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            email = serializer.data.get("email")
            user = User.objects.filter(email=email).first()

            if user:
                try:
                    # Generate secure token
                    token = default_token_generator.make_token(user)
                    uid = urlsafe_base64_encode(force_bytes(user.id))

                    # Build reset URL using frontend URL from settings
                    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5217').rstrip('/')
                    reset_url = f"{frontend_url}/auth/reset-password/{uid}/{token}"

                    # Get company branding if available
                    company_name = "BengoBox ERP"
                    company_logo = None
                    primary_color = "#7c3aed"
                    support_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@bengobox.com')

                    try:
                        from business.models import Bussiness
                        business = Bussiness.objects.first()
                        if business:
                            company_name = business.name or company_name
                            company_logo = business.logo.url if business.logo else None
                            primary_color = business.primary_color or primary_color
                    except Exception:
                        pass

                    # Get user's display name
                    user_name = user.first_name or user.username or "User"

                    # Prepare email context
                    context = {
                        'user_name': user_name,
                        'user_email': user.email,
                        'reset_url': reset_url,
                        'expiry_hours': 24,
                        'company_name': company_name,
                        'company_logo': company_logo,
                        'primary_color': primary_color,
                        'primary_color_dark': primary_color,
                        'support_email': support_email,
                        'year': timezone.now().year,
                    }

                    # Send email using the new template
                    email_service = EmailService()
                    email_service.send_django_template_email(
                        template_name='notifications/email/password_reset_request.html',
                        context=context,
                        subject=f'Reset Your Password - {company_name}',
                        recipient_list=[user.email],
                        async_send=True
                    )

                    logger.info(f"Password reset email sent to {user.email}")

                except Exception as e:
                    logger.error(f"Failed to send password reset email: {str(e)}")
                    # Still return success to not reveal user existence

            # Always return success to prevent email enumeration
            return Response({
                "detail": "If an account with that email exists, you will receive a password reset link shortly.",
                "success": True
            }, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class PasswordResetConfirmView(APIView):
    """
    Production-ready password reset confirmation endpoint.
    Validates token, updates password, and sends confirmation email.
    """
    permission_classes = ()
    authentication_classes = []
    serializer_class = SetPasswordSerializer

    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, uidb64, token):
        try:
            uid = urlsafe_base64_decode(uidb64)
            user = get_object_or_404(User, pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None

        if user is not None and default_token_generator.check_token(user, token):
            serializer = SetPasswordSerializer(data=request.data)
            if serializer.is_valid():
                new_password = request.data.get("new_password")
                if not new_password:
                    return Response({
                        "detail": "New password cannot be empty.",
                        "success": False
                    }, status=status.HTTP_400_BAD_REQUEST)

                # Update password
                user.set_password(new_password)

                # Track password lifecycle
                try:
                    user.password_changed_at = timezone.now()
                    user.must_change_password = False
                except Exception:
                    pass

                user.save()

                # Send password change confirmation email
                try:
                    # Get company branding
                    company_name = "BengoBox ERP"
                    company_logo = None
                    primary_color = "#7c3aed"
                    support_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'support@bengobox.com')

                    try:
                        from business.models import Bussiness
                        business = Bussiness.objects.first()
                        if business:
                            company_name = business.name or company_name
                            company_logo = business.logo.url if business.logo else None
                            primary_color = business.primary_color or primary_color
                    except Exception:
                        pass

                    frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5217').rstrip('/')
                    login_url = f"{frontend_url}/auth/login"

                    # Get client IP
                    ip_address = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', 'Unknown')

                    context = {
                        'user_name': user.first_name or user.username or "User",
                        'user_email': user.email,
                        'changed_at': timezone.now().strftime('%B %d, %Y at %I:%M %p'),
                        'ip_address': ip_address,
                        'login_url': login_url,
                        'company_name': company_name,
                        'company_logo': company_logo,
                        'primary_color': primary_color,
                        'primary_color_dark': primary_color,
                        'support_email': support_email,
                        'year': timezone.now().year,
                    }

                    email_service = EmailService()
                    email_service.send_django_template_email(
                        template_name='notifications/email/password_reset_success.html',
                        context=context,
                        subject=f'Password Changed - {company_name}',
                        recipient_list=[user.email],
                        async_send=True
                    )

                    logger.info(f"Password reset confirmation email sent to {user.email}")

                except Exception as e:
                    logger.error(f"Failed to send password change confirmation: {str(e)}")

                return Response({
                    "detail": "Password has been reset successfully. You can now log in with your new password.",
                    "success": True
                }, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "detail": "Invalid or expired reset link. Please request a new password reset.",
            "success": False
        }, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(UpdateAPIView):
    serializer_class = ChangePasswordSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_object(self, queryset=None):
        return self.request.user

    def update(self, request, *args, **kwargs):
        self.object = self.get_object()
        serializer = self.get_serializer(data=request.data)

        if serializer.is_valid():
            old_password = serializer.data.get("old_password")
            new_password = serializer.data.get("new_password")
            
            if not self.object.check_password(old_password):
                return Response({"old_password": ["Wrong password."]}, status=status.HTTP_400_BAD_REQUEST)

            self.object.set_password(new_password)
            # Track password lifecycle
            try:
                self.object.password_changed_at = timezone.now()
                self.object.must_change_password = False
            except Exception:
                pass
            self.object.save()
            update_session_auth_hash(request, self.object)  # Important to keep the user logged in

            return Response({"detail": "Password changed successfully."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class LogOutApiView(APIView):
    permission_classes = ()
    authentication_classes=[]
    
    # Exempt from CSRF for API logout
    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)
    
    def post(self, request,):
        logout(request)
        return Response({"Logout Success!"}, status=status.HTTP_200_OK)

        
class UserViewSet(APIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated,]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self, pk):
        try:
            return User.objects.get(pk=pk)
        except User.DoesNotExist:
            raise Http404

    def get(self, request, pk=None, format=None):
        # Return a single user when pk is provided
        if pk is not None:
            user = self.get_object(pk)
            serializer = UserSerializer(user)
            return Response(serializer.data)

        # Otherwise list users
        if request.user.is_superuser:
            users = User.objects.all().select_related()
            serializer = UserSerializer(users, many=True)
            return Response(serializer.data)
        else:
            biz = Bussiness.objects.filter(owner=request.user).first()
            if biz:
                # Load users linked to this business' employees
                from hrm.employees.models import Employee
                employee_user_ids = Employee.objects.filter(organisation=biz).values_list('user_id', flat=True)
                users = User.objects.filter(id__in=list(employee_user_ids))
                serializer = UserSerializer(users, many=True)
                return Response(serializer.data)
            # If user doesn't own a business, return empty list
            return Response([])

    def post(self, request, format=None):

        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk, format=None):
        user = self.get_object(pk)
        serializer = UserSerializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk, format=None):
        user = self.get_object(pk)
        serializer = UserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk, format=None):
        user = self.get_object(pk)
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class PasswordPolicyView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        policy = PasswordPolicy.objects.first()
        if not policy:
            policy = PasswordPolicy.objects.create()
        serializer = PasswordPolicySerializer(policy)
        return Response(serializer.data)
    
    def put(self, request):
        policy = PasswordPolicy.objects.first()
        if not policy:
            policy = PasswordPolicy.objects.create()
        serializer = PasswordPolicySerializer(policy, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class BackupView(APIView):
    """
    Production-ready backup management API.
    Supports local and S3 storage with download URLs.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """List all backups with download URLs."""
        from authmanagement.services.backup_service import backup_service

        backups = Backup.objects.all().order_by('-created_at')
        serializer = BackupSerializer(backups, many=True)
        data = serializer.data

        # Add download URLs for completed backups
        for backup_data in data:
            if backup_data.get('status') == 'completed':
                try:
                    backup_id = backup_data.get('id')
                    backup_data['download_url'] = backup_service.get_download_url(backup_id)
                except Exception as e:
                    backup_data['download_url'] = None
                    logger.error(f"Failed to get download URL for backup {backup_id}: {e}")

        return Response({
            'success': True,
            'results': data,
            'count': len(data)
        })

    def post(self, request):
        """Create a new backup (async via Celery or sync fallback)."""
        from authmanagement.services.backup_service import backup_service

        backup_type = request.data.get('type', 'full')

        # Try async first, fallback to sync
        try:
            from core.background_jobs import submit_background_job

            job_id = submit_background_job(
                'system_maintenance',
                {
                    'operation': 'backup',
                    'backup_type': backup_type,
                    'user_id': request.user.id if request.user.is_authenticated else None
                },
                user_id=request.user.id if request.user.is_authenticated else None
            )

            return Response({
                'success': True,
                'message': 'Backup process started in background',
                'job_id': job_id
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.warning(f"Background job failed, running sync: {e}")

            # Fallback to sync backup
            try:
                backup = backup_service.create_backup(
                    backup_type=backup_type,
                    user_id=request.user.id if request.user.is_authenticated else None
                )
                serializer = BackupSerializer(backup)
                return Response({
                    'success': True,
                    'message': 'Backup created successfully',
                    'data': serializer.data
                }, status=status.HTTP_201_CREATED)
            except Exception as backup_error:
                return Response({
                    'success': False,
                    'message': f'Backup failed: {str(backup_error)}'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BackupDetailView(APIView):
    """
    Backup detail operations: download, restore, delete.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        """Get backup details or download backup file."""
        from authmanagement.services.backup_service import backup_service
        from django.http import HttpResponse

        action = request.query_params.get('action', 'detail')

        try:
            backup = Backup.objects.get(pk=pk)

            if action == 'download':
                # Download backup file
                content, filename, content_type = backup_service.download_backup(pk)
                response = HttpResponse(content, content_type=content_type)
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                response['Content-Length'] = len(content)
                return response

            elif action == 'url':
                # Get presigned download URL (for S3)
                url = backup_service.get_download_url(pk)
                return Response({
                    'success': True,
                    'download_url': url
                })

            else:
                # Return backup details
                serializer = BackupSerializer(backup)
                data = serializer.data
                if backup.status == 'completed':
                    try:
                        data['download_url'] = backup_service.get_download_url(pk)
                    except Exception:
                        data['download_url'] = None
                return Response({
                    'success': True,
                    'data': data
                })

        except Backup.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Backup not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Backup detail error: {e}")
            return Response({
                'success': False,
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, pk):
        """Restore from backup."""
        from authmanagement.services.backup_service import backup_service

        try:
            backup = Backup.objects.get(pk=pk)

            if backup.status != 'completed':
                return Response({
                    'success': False,
                    'message': 'Cannot restore from incomplete backup'
                }, status=status.HTTP_400_BAD_REQUEST)

            # Restore is a dangerous operation - require confirmation
            confirm = request.data.get('confirm', False)
            if not confirm:
                return Response({
                    'success': False,
                    'message': 'Restore requires confirmation. Set confirm=true to proceed.',
                    'warning': 'This will overwrite all current data!'
                }, status=status.HTTP_400_BAD_REQUEST)

            success = backup_service.restore_backup(pk)

            if success:
                return Response({
                    'success': True,
                    'message': 'Backup restored successfully'
                })
            else:
                return Response({
                    'success': False,
                    'message': 'Restore failed'
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Backup.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Backup not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Restore error: {e}")
            return Response({
                'success': False,
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete a backup."""
        from authmanagement.services.backup_service import backup_service

        try:
            backup_service.delete_backup(pk)
            return Response({
                'success': True,
                'message': 'Backup deleted successfully'
            }, status=status.HTTP_204_NO_CONTENT)
        except Backup.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Backup not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Delete error: {e}")
            return Response({
                'success': False,
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BackupConfigView(APIView):
    """Backup configuration management."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        config = BackupConfig.objects.first()
        if not config:
            config = BackupConfig.objects.create()
        serializer = BackupConfigSerializer(config)
        return Response({
            'success': True,
            'data': serializer.data
        })

    def put(self, request):
        config = BackupConfig.objects.first()
        if not config:
            config = BackupConfig.objects.create()
        serializer = BackupConfigSerializer(config, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'data': serializer.data
            })
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class BackupScheduleView(APIView):
    """Backup schedule management."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        schedule = BackupSchedule.objects.first()
        if not schedule:
            schedule = BackupSchedule.objects.create(frequency='daily')
        serializer = BackupScheduleSerializer(schedule)
        return Response({
            'success': True,
            'data': serializer.data
        })

    def put(self, request):
        schedule = BackupSchedule.objects.first()
        if not schedule:
            schedule = BackupSchedule.objects.create(frequency='daily')

        serializer = BackupScheduleSerializer(schedule, data=request.data, partial=True)
        if serializer.is_valid():
            schedule = serializer.save()

            # Calculate next run time based on frequency
            from datetime import timedelta
            now = timezone.now()

            if schedule.frequency == 'daily':
                schedule.next_run = now + timedelta(days=1)
            elif schedule.frequency == 'weekly':
                schedule.next_run = now + timedelta(weeks=1)
            elif schedule.frequency == 'monthly':
                schedule.next_run = now + timedelta(days=30)

            schedule.save(update_fields=['next_run'])

            return Response({
                'success': True,
                'data': BackupScheduleSerializer(schedule).data
            })
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

class RoleView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        roles = Group.objects.all()
        serializer = RoleSerializer(roles, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        serializer = RoleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def put(self, request, pk):
        role = get_object_or_404(Group, pk=pk)
        serializer = RoleSerializer(role, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        role = get_object_or_404(Group, pk=pk)
        role.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class PermissionView(APIView):
    """
    Permission management view with pagination and filtering support.
    Optimized for large permission sets (1000+) with efficient queryset handling.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk=None):
        """
        List permissions with pagination and filtering.
        Supports:
          - ?search=<term> - Filter by name or codename
          - ?content_type=<id> - Filter by content type
          - ?module=<name> - Filter by content type app label (e.g., 'hrm', 'finance')
          - ?role=<id> - Filter by role (permissions assigned to this role)
          - ?action=<type> - Filter by action type (add, change, delete, view)
          - ?page=<n> - Pagination page number
          - ?page_size=<n> - Items per page (default 100, max 500)
        """
        if pk:
            # Detail view
            permission = get_object_or_404(Permission, pk=pk)
            serializer = PermissionSerializer(permission)
            return Response(serializer.data)

        # List view with filtering
        queryset = Permission.objects.select_related('content_type').order_by('content_type__app_label', 'codename')

        # Search filter
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) |
                models.Q(codename__icontains=search)
            )

        # Content type filter
        content_type_id = request.query_params.get('content_type')
        if content_type_id:
            queryset = queryset.filter(content_type_id=content_type_id)

        # Module/app label filter
        module = request.query_params.get('module', '').strip()
        if module:
            queryset = queryset.filter(content_type__app_label__icontains=module)

        # Role filter - filter permissions assigned to a specific role
        role_id = request.query_params.get('role', '').strip()
        if role_id:
            try:
                role = Group.objects.get(pk=int(role_id))
                queryset = queryset.filter(group=role)
            except (Group.DoesNotExist, ValueError):
                pass

        # Action type filter (add, change, delete, view)
        action = request.query_params.get('action', '').strip().lower()
        if action in ['add', 'change', 'delete', 'view']:
            queryset = queryset.filter(codename__startswith=f'{action}_')

        # Pagination
        page = int(request.query_params.get('page', 1))
        page_size = min(int(request.query_params.get('page_size', 100)), 500)
        total_count = queryset.count()
        total_pages = (total_count + page_size - 1) // page_size

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        permissions_page = queryset[start_idx:end_idx]

        serializer = PermissionSerializer(permissions_page, many=True)

        return Response({
            'count': total_count,
            'page': page,
            'page_size': page_size,
            'total_pages': total_pages,
            'next': page < total_pages,
            'previous': page > 1,
            'results': serializer.data
        })

    def post(self, request):
        serializer = PermissionSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        permission = get_object_or_404(Permission, pk=pk)
        serializer = PermissionSerializer(permission, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        permission = get_object_or_404(Permission, pk=pk)
        permission.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserPreferencesView(APIView):
    """
    View for managing user preferences including theme settings
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, pk):
        """Get user preferences"""
        user = get_object_or_404(User, pk=pk)
        
        # Create preferences if they don't exist
        preferences, created = UserPreferences.objects.get_or_create(user=user)
        
        serializer = UserPreferencesSerializer(preferences)
        return Response(serializer.data)
    
    def put(self, request, pk):
        """Update user preferences"""
        user = get_object_or_404(User, pk=pk)
        
        # Ensure the user can only update their own preferences
        if request.user.id != user.id and not request.user.is_staff:
            return Response(
                {'error': 'You can only update your own preferences'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get or create preferences
        preferences, created = UserPreferences.objects.get_or_create(user=user)
        
        serializer = UserPreferencesSerializer(preferences, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)