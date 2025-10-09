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
    class Meta:
        model = User
        fields = ('id','groups', 'first_name','middle_name','last_name','timezone',
                  'username', 'email','password')
        
    @extend_schema_field(OpenApiTypes.STR)
    def get_timezone(self, obj):
        return str(obj.timezone) if obj.timezone else 'Africa/Nairobi'

    def create(self, validated_data):
        try:
            user = User(
                first_name=validated_data['first_name'],
                last_name=validated_data['last_name'],
                middle_name=validated_data['middle_name'],
                username=validated_data['username'],
                email=validated_data['email'],
                )
            selectedroles = validated_data['groups'] if 'groups' in validated_data else None
            user.set_password(validated_data['password'])
            user.is_staff = True
            user.save()
            group,created=Group.objects.get_or_create(name='staff')
            print(group.id)
            user.is_active = False
            user.save()
            if selectedroles:
                roles = Group.objects.filter(name__in=selectedroles)
                for role in roles:
                    user.groups.add(role)
            else:
                user.groups.add(group)
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

# New serializers for additional functionality
class PasswordPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PasswordPolicy
        fields = '__all__'

class BackupScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupSchedule
        fields = '__all__'


class BackupSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    type = serializers.ChoiceField(choices=['full', 'incremental'])
    size = serializers.IntegerField(read_only=True)
    status = serializers.CharField(read_only=True)
    path = serializers.CharField(read_only=True)

class BackupConfigSerializer(serializers.Serializer):
    storage_type = serializers.ChoiceField(choices=['local', 's3'])
    path = serializers.CharField(required=False)
    bucket = serializers.CharField(required=False)
    region = serializers.CharField(required=False)
    access_key = serializers.CharField(required=False)
    secret_key = serializers.CharField(required=False)

class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Group
        fields = ('id', 'name', 'permissions')

class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ('id', 'name', 'codename', 'content_type')
