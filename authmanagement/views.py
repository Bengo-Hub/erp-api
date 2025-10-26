from django.contrib.auth import authenticate,login,logout
from django.views import View
from django.views.decorators.csrf import csrf_exempt

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
    queryset = User.objects.all().select_related('profile')
    #queryset = queryset.filter(employee__hr_details__head_of__isnull=False)
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
    permission_classes = ()
    authentication_classes=[]
    serializer_class = ForgotPasswordSerializer
    site_url = ''#Site.objects.filter(name='frontend_url').first()
    
    # Exempt from CSRF for API password reset
    @csrf_exempt
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        
        if serializer.is_valid():
            email = serializer.data.get("email")
            user = User.objects.filter(email=email).first()

            if user:
                # Generate and send password reset email
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.id))
                reset_url = f"{self.site_url}/password-reset-confirm/{uid}/{token}/"
                subject = 'Reset your password'
                message = render_to_string('auth/forgot_password_email.html', {
                    'reset_url':reset_url,
                })
                # schedule in a thread
                email_service = EmailService()
                email_service.send_email(
                    subject=subject,
                    message=message,
                    recipient_list=[user.email],
                    async_send=True
                )
                print("Email sent successfully!")
                return Response({"detail": "Password reset email sent successfully."}, status=status.HTTP_200_OK)
            
            # If the user is not found, don't reveal that the email is not registered.
            return Response({"detail": "Password reset email sent successfully. If the email is registered, you will receive a reset link shortly."}, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class PasswordResetConfirmView(APIView):
    permission_classes = ()
    authentication_classes=[]
    serializer_class = SetPasswordSerializer
    
    # Exempt from CSRF for API password reset confirmation
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
                print(serializer.data)
                new_password = request.data["new_password"]
                if new_password !=None:
                    user.set_password(new_password)
                    print('password->',new_password,user.password)
                    user.save()
                else:
                    return Response({"detail":"New password cannot be null!"}, status=status.HTTP_400_BAD_REQUEST)
                return Response({"detail": "Password reset successfully."}, status=status.HTTP_200_OK)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Invalid reset link."}, status=status.HTTP_400_BAD_REQUEST)

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

    def get_object(self, pk):
        try:
            return User.objects.get(pk=pk)
        except User.DoesNotExist:
            raise Http404

    def get(self, request, format=None):
        context = None
        if request.user.is_superuser:
            context = User.objects.values("username", "first_name", "last_name",
                                          "email", "phone", "groups__name", "pic", "is_active")
            # print(request.user.is_superuser)
        else:
            biz = Bussiness.objects.filter(owner=request.user).first()
            # print(vendor)
            if biz:
                context = biz.employees.values(
                    "user__username", "user__first_name", "user__last_name",
                    "user__email", "user__phone", "user__groups__name", "user__pic",
                    "user__is_active", "national_id", "gender", "passport_photo"
                )
            else:
                # If user doesn't own a business, return empty list
                context = []
        context = list(context)
        return Response(context)

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
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        backups = Backup.objects.all().order_by('-created_at')
        serializer = BackupSerializer(backups, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        backup_type = request.data.get('type', 'full')
        
        # Use enhanced background job system instead of basic threading
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
            'message': 'Backup process started',
            'job_id': job_id
        }, status=status.HTTP_202_ACCEPTED)
    
    def create_backup(self, backup_type):
        try:
            # Create backup using appropriate database command
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'backup_{backup_type}_{timestamp}.sql'
            path = os.path.join(settings.BACKUP_ROOT, filename)
            
            if settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
                cmd = f'pg_dump -U {settings.DATABASES["default"]["USER"]} -h {settings.DATABASES["default"]["HOST"]} {settings.DATABASES["default"]["NAME"]} > {path}'
            else:  # MySQL
                cmd = f'mysqldump -u {settings.DATABASES["default"]["USER"]} -p{settings.DATABASES["default"]["PASSWORD"]} -h {settings.DATABASES["default"]["HOST"]} {settings.DATABASES["default"]["NAME"]} > {path}'
            
            subprocess.run(cmd, shell=True, check=True)
            
            # Create backup record
            Backup.objects.create(
                type=backup_type,
                path=path,
                size=os.path.getsize(path),
                status='completed'
            )
        except Exception as e:
            Backup.objects.create(
                type=backup_type,
                path=path,
                status='failed',
                error_message=str(e)
            )

class BackupConfigView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        config = BackupConfig.objects.first()
        if not config:
            config = BackupConfig.objects.create()
        serializer = BackupConfigSerializer(config)
        return Response(serializer.data)
    
    def put(self, request):
        config = BackupConfig.objects.first()
        if not config:
            config = BackupConfig.objects.create()
        serializer = BackupConfigSerializer(config, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

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
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        permissions = Permission.objects.all()
        serializer = PermissionSerializer(permissions, many=True)
        return Response(serializer.data)
    
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