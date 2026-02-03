from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from rest_framework.authtoken.models import Token
from .models import *
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from rest_framework import status
from rest_framework.response import Response
from django.conf import settings
import os,json
from django.http import HttpRequest
import threading
from django.contrib.auth import get_user_model
from notifications.services import EmailService
from django.contrib.auth.models import Group, Permission
from django.db.models import Q

User = get_user_model()

class SetPasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, required=True)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, data):
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not match.")
        print('data',data)
        return data
    
class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True)

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

class UserSerializer(serializers.ModelSerializer):
    timezone=serializers.SerializerMethodField()
    # Accept groups as a list of role names for writes; we'll format nicely on reads
    groups = serializers.ListField(child=serializers.CharField(), required=False, write_only=True)
    class Meta:
        model = User
        fields = (
            'id',
            'groups',
            'first_name',
            'middle_name',
            'last_name',
            'timezone',
            'username',
            'email',
            'password',
            'phone',
            'pic',
            'signature',
            'is_active',
            'is_staff',
        )
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
            'pic': {'required': False},
            'signature': {'required': False},
            'phone': {'required': False},
            'is_active': {'required': False},
            'is_staff': {'required': False},
        }
    
    def validate_signature(self, value):
        """Validate signature file for security."""
        if value:
            try:
                from core.file_security import scan_signature_file
                result = scan_signature_file(value, strict=True)
                if not result['is_safe']:
                    raise serializers.ValidationError('; '.join(result['errors']))
            except ImportError:
                # Fallback validation if file_security module not available
                if hasattr(value, 'size') and value.size > 2 * 1024 * 1024:
                    raise serializers.ValidationError('Signature file too large (max 2MB)')
                if hasattr(value, 'content_type'):
                    valid_types = ['image/png', 'image/jpeg', 'image/webp']
                    if value.content_type not in valid_types:
                        raise serializers.ValidationError('Invalid file type. Use PNG, JPEG, or WebP.')
        return value
    
    def validate_pic(self, value):
        """Validate profile picture for security."""
        if value:
            try:
                from core.file_security import scan_profile_image
                result = scan_profile_image(value, strict=True)
                if not result['is_safe']:
                    raise serializers.ValidationError('; '.join(result['errors']))
            except ImportError:
                # Fallback validation
                if hasattr(value, 'size') and value.size > 5 * 1024 * 1024:
                    raise serializers.ValidationError('Profile picture too large (max 5MB)')
        return value
        
    @extend_schema_field(OpenApiTypes.STR)
    def get_timezone(self, obj):
        return str(obj.timezone) if obj.timezone else 'Africa/Nairobi'

    def create(self, validated_data):
        try:
            # Extract and remove groups from validated_data (we handle assignment manually)
            selectedroles = validated_data.pop('groups', None)
            user = User(
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                middle_name=validated_data['middle_name'],
                username=validated_data['username'],
                email=validated_data['email'],
                phone=validated_data.get('phone'),
                pic=validated_data.get('pic'),
            )
            if validated_data.get('password'):
                user.set_password(validated_data['password'])
            else:
                raise serializers.ValidationError({'password': 'This field is required.'})
            user.is_staff = True
            user.save()
            
            # Get or create staff group (case-insensitive to prevent duplicates)
            staff_group = Group.objects.filter(name__iexact='staff').first()
            if not staff_group:
                staff_group = Group.objects.create(name='Staff')
            
            user.is_active = False
            user.save()
            
            # Assign roles
            if selectedroles:
                # User-specified roles (accept ids or names, case-insensitive for names)
                ids, names = [], []
                for r in selectedroles:
                    try:
                        ids.append(int(r))
                    except (TypeError, ValueError):
                        names.append(str(r))
                name_q = Q()
                for nm in names:
                    name_q |= Q(name__iexact=nm)
                roles = Group.objects.filter(Q(id__in=ids) | name_q)
                for role in roles:
                    user.groups.add(role)
                
                # Also assign Staff role if not admin/superuser role selected
                admin_roles = ['superusers', 'admin', 'superuser']
                if not any(role.lower() in admin_roles for role in selectedroles):
                    # Add staff role in addition to specified roles
                    user.groups.add(staff_group)
            else:
                # No roles specified - assign Staff role by default
                user.groups.add(staff_group)
            
            user.save()
            Token.objects.create(user=user)
            # Send confirmation email
            token = default_token_generator.make_token(user)
            user.email_confirm_token=token
            user.save()
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            print(uid,'\n',token)
            request=HttpRequest()
            reqdata=os.environ.get('REQUEST_DATA',{})
            print(reqdata)
            jsondata = json.loads(reqdata)
            request.META=jsondata
            subject = 'Confirm your registration'
            host = request.META['REQUEST_URL']
            message = render_to_string('auth/confirm_email.html', {
                'host':host,
                'user': user,
                'uid': uid,
                'token': token,
            })
            # Send email using centralized service
            email_service = EmailService()
            email_service.send_email(
                subject=subject,
                message=message,
                recipient_list=[user.email],
                async_send=True
            )
            print("Email sent successfully!")
        except Exception as e:
            user.delete()
            print("send mail error:{}".format(e))
        return user

    def update(self, instance, validated_data):
        # Extract write-only groups
        groups_input = validated_data.pop('groups', None)

        # Update basic fields if provided
        for field in ['first_name', 'last_name', 'middle_name', 'username', 'email', 'phone', 'is_active', 'is_staff']:
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        # Handle password change if provided
        password = validated_data.pop('password', None)
        if password:
            from django.utils import timezone
            instance.set_password(password)
            try:
                instance.password_changed_at = timezone.now()
                instance.must_change_password = False
            except Exception:
                pass

        # Handle profile picture if provided
        if 'pic' in validated_data:
            instance.pic = validated_data['pic']

        # Handle signature if provided
        if 'signature' in validated_data:
            instance.signature = validated_data['signature']

        instance.save()

        # Update groups if provided - accept names or ids
        if groups_input is not None:
            # Normalize to list
            if not isinstance(groups_input, (list, tuple)):
                groups_input = [groups_input]
            # Split int-like vs name-like
            ids, names = [], []
            for g in groups_input:
                try:
                    ids.append(int(g))
                except (TypeError, ValueError):
                    names.append(str(g))
            name_q = Q()
            for nm in names:
                name_q |= Q(name__iexact=nm)
            roles = Group.objects.filter(Q(id__in=ids) | name_q)
            instance.groups.set(roles)

        return instance

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Present groups as objects {id, name} for the frontend
        data['groups'] = [{'id': g.id, 'name': g.name} for g in instance.groups.all()]
        # Add a few helpful read-only fields often used by UI
        data['is_superuser'] = getattr(instance, 'is_superuser', False)
        data['date_joined'] = getattr(instance, 'date_joined', None)
        data['last_login'] = getattr(instance, 'last_login', None)
        # Include signature URL if available
        if instance.signature:
            data['signature'] = instance.signature.url if instance.signature else None
        # Include employee mapping for consistent frontend checks
        try:
            from hrm.employees.models import Employee
            emp_id = Employee.objects.filter(user=instance).values_list('id', flat=True).first()
        except Exception:
            emp_id = None
        data['employee_id'] = emp_id
        return data

# New serializers for additional functionality
class PasswordPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PasswordPolicy
        fields = '__all__'

class BackupScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupSchedule
        fields = '__all__'


class BackupSerializer(serializers.ModelSerializer):
    """Serializer for Backup model with computed fields."""
    filename = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Backup
        fields = [
            'id', 'type', 'status', 'path', 'size', 'error_message',
            'created_at', 'completed_at', 'storage_type', 'filename', 'download_url'
        ]
        read_only_fields = ['id', 'path', 'size', 'status', 'error_message', 'created_at', 'completed_at', 'storage_type']

    def get_filename(self, obj):
        return obj.filename

    def get_download_url(self, obj):
        # Download URL is added dynamically in the view
        return getattr(obj, '_download_url', None)


class BackupConfigSerializer(serializers.ModelSerializer):
    """Serializer for BackupConfig model."""

    class Meta:
        model = BackupConfig
        fields = [
            'id', 'storage_type', 'local_path', 's3_bucket', 's3_region',
            's3_access_key', 's3_secret_key', 'retention_days', 'created_at', 'updated_at'
        ]
        extra_kwargs = {
            's3_access_key': {'write_only': True},
            's3_secret_key': {'write_only': True},
        }

    def to_representation(self, instance):
        """Hide sensitive data on read, show masked versions."""
        data = super().to_representation(instance)
        # Show masked versions of sensitive fields
        if instance.s3_access_key:
            data['s3_access_key_set'] = True
        if instance.s3_secret_key:
            data['s3_secret_key_set'] = True
        return data

class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ('id', 'name', 'permissions')

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ('id', 'name', 'codename', 'content_type')


class UserPreferencesSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreferences
        fields = ('id', 'user', 'theme_settings', 'notification_settings', 'dashboard_layout', 'language', 'created_at', 'updated_at')
        read_only_fields = ('id', 'user', 'created_at', 'updated_at')