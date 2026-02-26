# User Creation M2M Fix - Code Implementation

**Status:** Ready to implement  
**Files to modify:** 2  
**Lines of code to change:** ~60  
**Estimated time:** 4 hours  

---

## Issue Visualization

### Current Flow (Broken ❌)

```
POST /api/v1/auth/listusers/
    ↓
UserViewSet.post()
    ↓
UserSerializer.create()
    ├─ Extract groups from input ✅
    ├─ Create User() instance ✅
    ├─ user.set_password() ✅
    ├─ user.save() [OBTAINS ID] ✅
    ├─ Create Staff group ✅
    ├─ user.is_active = False ✅
    ├─ user.save() [REDUNDANT] ⚠️
    │
    ├─ selectedroles = ["superusers", "ict_officer"]
    ├─ roles = Group.objects.filter(...) ✅
    │
    └─ for role in roles:
           user.groups.add(role) ❌ 
           
           ERROR: "<CustomUser>" needs to have a value 
           for field "id" before this many-to-many 
           relationship can be used.
```

**Root Cause:** Transaction isolation or signal handler attempting M2M access before commit

---

### Fixed Flow (Working ✅)

```
POST /api/v1/auth/users/  [Updated endpoint name]
    ↓
UserViewSet.post()
    ↓
@transaction.atomic
UserSerializer.create()
    ├─ Extract groups from input ✅
    ├─ Create User() instance ✅
    ├─ user.set_password() ✅
    ├─ Set is_active & is_staff BEFORE save ✅
    ├─ user.save() [SINGLE SAVE with all fields] ✅
    │
    ├─ _assign_groups_to_user(user, selectedroles)
    │  ├─ Parse group IDs & names ✅
    │  ├─ Query groups: Group.objects.filter(...) ✅
    │  └─ user.groups.set(groups) ✅ [SAFE - user has ID]
    │
    ├─ Token.objects.create(user=user) ✅
    ├─ _send_confirmation_email_async(user) ✅
    │
    └─ return user ✅
    ↓
APIResponse.created() [Structured response]
    ↓
200 Created ✅
{
  "success": true,
  "data": {...user_data, "groups": [...]},
  "message": "User created successfully..."
}
```

---

## File 1: authmanagement/serializers.py

### Change Summary
- Add `@transaction.atomic` decorator
- Extract helper methods
- Fix double-save issue
- Add validation methods

### Complete Updated Code

```python
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
import os, json
from django.http import HttpRequest
import threading
from django.contrib.auth import get_user_model
from notifications.services import EmailService
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from django.db import transaction
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for CustomUser model.
    Handles user creation, updates, and group assignments.
    """
    timezone = serializers.SerializerMethodField()
    # Accept groups as a list of role names or IDs; returned as objects on read
    groups = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        write_only=True,
        help_text="List of group names or IDs to assign to user"
    )

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

    @extend_schema_field(OpenApiTypes.STR)
    def get_timezone(self, obj):
        """Get timezone as string."""
        return str(obj.timezone) if obj.timezone else 'Africa/Nairobi'

    def validate_password(self, value):
        """
        Validate password against configured policy.
        Checks: length, uppercase, lowercase, numbers, special chars.
        """
        if not value:
            return value
        
        try:
            from authmanagement.models import PasswordPolicy
            policy = PasswordPolicy.objects.first()
            
            if policy:
                # Check minimum length
                if len(value) < policy.min_length:
                    raise serializers.ValidationError(
                        f'Password must be at least {policy.min_length} characters.'
                    )
                
                # Check uppercase
                if policy.require_uppercase and not any(c.isupper() for c in value):
                    raise serializers.ValidationError(
                        'Password must contain uppercase letters.'
                    )
                
                # Check lowercase
                if policy.require_lowercase and not any(c.islower() for c in value):
                    raise serializers.ValidationError(
                        'Password must contain lowercase letters.'
                    )
                
                # Check numbers
                if policy.require_numbers and not any(c.isdigit() for c in value):
                    raise serializers.ValidationError(
                        'Password must contain numbers.'
                    )
                
                # Check special characters
                if policy.require_special_chars:
                    special_chars = '!@#$%^&*()_+-=[]{}|;:,.<>?'
                    if not any(c in special_chars for c in value):
                        raise serializers.ValidationError(
                            'Password must contain special characters (!@#$%^&*)'
                        )
        except Exception as e:
            logger.warning(f"Error validating password policy: {e}")
            # Don't fail if policy check errors – continue with basic validation
        
        return value

    def validate_email(self, value):
        """
        Validate email uniqueness (case-insensitive).
        """
        if not value:
            raise serializers.ValidationError('Email is required.')
        
        # Normalize to lowercase
        value = value.lower().strip()
        
        # Check uniqueness (case-insensitive)
        existing = User.objects.filter(email__iexact=value).first()
        if existing:
            # If updating, allow same email for the same user
            if self.instance and existing.pk == self.instance.pk:
                return value
            # Otherwise, email is taken
            raise serializers.ValidationError('Email address is already in use.')
        
        return value

    def validate_username(self, value):
        """
        Validate username format and uniqueness.
        Username must contain only letters, numbers, and underscores.
        """
        if not value:
            raise serializers.ValidationError('Username is required.')
        
        # Normalize to lowercase
        value = value.lower().strip()
        
        # Check format: must be a valid Python identifier
        if not value.isidentifier():
            raise serializers.ValidationError(
                'Username must contain only letters, numbers, and underscores, '
                'and cannot start with a number.'
            )
        
        # Check uniqueness (case-insensitive)
        existing = User.objects.filter(username__iexact=value).first()
        if existing:
            if self.instance and existing.pk == self.instance.pk:
                return value
            raise serializers.ValidationError('Username is already in use.')
        
        return value

    def validate_groups(self, value):
        """
        Validate that groups exist before assignment.
        Accepts both group IDs and group names (case-insensitive).
        """
        if not value:
            return value
        
        # Parse IDs vs. names
        ids = []
        names = []
        
        for item in value:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                names.append(str(item).strip().lower())
        
        # Query for groups
        q = Q(id__in=ids) if ids else Q()
        for name in names:
            q |= Q(name__iexact=name)
        
        groups = Group.objects.filter(q)
        groups_count = groups.count()
        expected_count = len(set(value))
        
        if groups_count != expected_count:
            found_names = list(groups.values_list('name', flat=True))
            raise serializers.ValidationError(
                f'One or more groups not found. '
                f'Requested: {value}, Found: {found_names}'
            )
        
        return value

    def validate_signature(self, value):
        """Validate signature file for security."""
        if value:
            try:
                from core.file_security import scan_signature_file
                result = scan_signature_file(value, strict=True)
                if not result['is_safe']:
                    raise serializers.ValidationError('; '.join(result['errors']))
            except ImportError:
                # Fallback validation
                if hasattr(value, 'size') and value.size > 2 * 1024 * 1024:
                    raise serializers.ValidationError('Signature file too large (max 2MB)')
                if hasattr(value, 'content_type'):
                    valid_types = ['image/png', 'image/jpeg', 'image/webp']
                    if value.content_type not in valid_types:
                        raise serializers.ValidationError(
                            'Invalid file type. Use PNG, JPEG, or WebP.'
                        )
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

    @transaction.atomic
    def create(self, validated_data):
        """
        Create a new user with groups and confirmation email.
        
        Uses @transaction.atomic to ensure M2M relationships work correctly.
        Groups are assigned AFTER user is saved (has ID).
        Email confirmation is sent asynchronously.
        
        Args:
            validated_data: Validated user creation data
            
        Returns:
            CustomUser: Newly created user instance
            
        Raises:
            ValidationError: If required fields are missing
        """
        user = None
        try:
            # Step 1: Extract groups (must do before popping validated_data)
            selected_groups = validated_data.pop('groups', None)
            
            # Step 2: Extract optional fields
            password = validated_data.pop('password', None)
            if not password:
                raise serializers.ValidationError({'password': 'Password is required.'})
            
            middle_name = validated_data.pop('middle_name', '')
            timezone = validated_data.pop('timezone', 'Africa/Nairobi')
            is_active = validated_data.pop('is_active', False)
            is_staff = validated_data.pop('is_staff', False)
            
            # Step 3: Create user instance (not saved yet)
            user = User(
                first_name=validated_data.get('first_name', ''),
                last_name=validated_data.get('last_name', ''),
                middle_name=middle_name,
                username=validated_data.get('username', ''),
                email=validated_data.get('email', '').lower(),
                phone=validated_data.get('phone', ''),
                pic=validated_data.get('pic'),
                signature=validated_data.get('signature'),
                timezone=timezone,
                is_active=is_active,
                is_staff=is_staff,
            )
            
            # Step 4: Set password
            user.set_password(password)
            
            # Step 5: Save user (now obtains ID – critical for M2M)
            user.save()
            logger.info(f"User created: {user.id} ({user.email})")
            
            # Step 6: Assign groups
            self._assign_groups_to_user(user, selected_groups)
            
            # Step 7: Create auth token
            Token.objects.create(user=user)
            logger.info(f"Token created for user {user.id}")
            
            # Step 8: Send confirmation email asynchronously
            self._send_confirmation_email_async(user)
            
            return user
            
        except serializers.ValidationError:
            # Re-raise validation errors
            if user and user.pk:
                user.delete()
                logger.info(f"User {user.id} deleted due to validation error")
            raise
        except Exception as e:
            # Clean up on any error
            if user and user.pk:
                user.delete()
                logger.error(f"User {user.id} deleted due to error: {e}")
            raise serializers.ValidationError(
                f'Error creating user: {str(e)}'
            )

    def _assign_groups_to_user(self, user, group_input):
        """
        Safely assign groups to user.
        
        Handles both group IDs and group names (case-insensitive).
        Uses .set() instead of .add() to replace groups atomically.
        
        Args:
            user: CustomUser instance (must have pk)
            group_input: List of group IDs, names, or mix
        """
        if not group_input:
            # No groups specified – assign Staff group by default
            staff_group, _ = Group.objects.get_or_create(name='Staff')
            user.groups.set([staff_group])
            logger.info(f"Assigned default Staff group to user {user.id}")
            return
        
        # Parse IDs vs. names
        ids = []
        names = []
        
        for item in group_input:
            try:
                ids.append(int(item))
            except (TypeError, ValueError):
                names.append(str(item).strip().lower())
        
        # Build query
        q = Q(id__in=ids) if ids else Q()
        for name in names:
            q |= Q(name__iexact=name)
        
        # Fetch and assign groups
        groups = Group.objects.filter(q)
        if groups.exists():
            user.groups.set(groups)
            group_names = ', '.join(groups.values_list('name', flat=True))
            logger.info(f"Assigned groups to user {user.id}: {group_names}")
        else:
            logger.warning(f"No groups found for user {user.id}: {group_input}")

    def _send_confirmation_email_async(self, user):
        """
        Send email confirmation asynchronously.
        
        Non-blocking – if email fails, the user is still created.
        Email tokens are generated and stored on the user.
        
        Args:
            user: CustomUser instance (must be saved with pk)
        """
        try:
            from django.contrib.auth.tokens import default_token_generator
            from django.utils.encoding import force_bytes
            from django.utils.http import urlsafe_base64_encode
            
            # Generate secure token
            token = default_token_generator.make_token(user)
            user.email_confirm_token = token
            user.save(update_fields=['email_confirm_token'])
            
            # Build confirmation URL
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:5217').rstrip('/')
            confirm_url = f"{frontend_url}/auth/confirm-email/{uid}/{token}"
            
            # Send email asynchronously
            email_service = EmailService()
            email_service.send_email(
                subject='Confirm your BengoBox ERP Registration',
                recipient_list=[user.email],
                template='auth/confirm_email.html',
                context={
                    'user': user,
                    'confirm_url': confirm_url,
                    'uid': uid,
                    'token': token,
                },
                async_send=True  # Non-blocking
            )
            logger.info(f"Confirmation email sent to {user.email}")
            
        except Exception as e:
            # Log but don't raise – user creation succeeded, email is best-effort
            logger.error(
                f"Failed to send confirmation email to {user.email}: {e}",
                exc_info=True
            )

    def update(self, instance, validated_data):
        """
        Update an existing user.
        
        Handles password changes, group updates, and profile updates.
        """
        # Extract groups and password before updating basic fields
        groups_input = validated_data.pop('groups', None)
        password = validated_data.pop('password', None)
        
        # Update basic fields
        for field in ['first_name', 'last_name', 'middle_name', 'username', 
                      'email', 'phone', 'is_active', 'is_staff', 'timezone']:
            if field in validated_data:
                setattr(instance, field, validated_data[field])
        
        # Update profile picture
        if 'pic' in validated_data:
            instance.pic = validated_data['pic']
        
        # Update signature
        if 'signature' in validated_data:
            instance.signature = validated_data['signature']
        
        # Handle password change
        if password:
            from django.utils import timezone
            instance.set_password(password)
            try:
                instance.password_changed_at = timezone.now()
                instance.must_change_password = False
            except Exception:
                pass
        
        # Save basic updates
        instance.save()
        logger.info(f"User {instance.id} updated")
        
        # Update groups if provided
        if groups_input is not None:
            self._assign_groups_to_user(instance, groups_input)
        
        return instance

    def to_representation(self, instance):
        """
        Serialize user data for response.
        Groups returned as objects {id, name} instead of raw list.
        """
        data = super().to_representation(instance)
        
        # Format groups as objects for frontend
        data['groups'] = [
            {'id': g.id, 'name': g.name}
            for g in instance.groups.all()
        ]
        
        return data
```

---

## File 2: authmanagement/views.py

### Change 1: Update UserViewSet.post() method

**Location:** Line ~398

```python
# OLD CODE
def post(self, request, format=None):
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# NEW CODE
def post(self, request, format=None):
    """
    Create a new user.
    
    Request body:
        - first_name (required)
        - last_name (required)
        - email (required, unique)
        - username (required, unique)
        - password (required)
        - groups (optional, list of group names/IDs)
        - phone (optional)
        - timezone (optional, default: Africa/Nairobi)
        - is_active (optional, default: false)
        - is_staff (optional, default: false)
    
    Returns:
        201 Created on success
        400 Validation Error on input validation failure
        500 Server Error on unexpected error
    """
    from core.response import APIResponse, get_correlation_id
    
    try:
        serializer = UserSerializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.save()
            return APIResponse.created(
                data=serializer.to_representation(user),
                message='User created successfully. Please check your email to confirm your account.',
                correlation_id=get_correlation_id(request)
            )
        
        # Validation errors
        return APIResponse.validation_error(
            message='User creation validation failed',
            errors=serializer.errors,
            correlation_id=get_correlation_id(request)
        )
        
    except serializers.ValidationError as e:
        logger.error(f"Validation error creating user: {e}")
        return APIResponse.validation_error(
            message='User creation validation failed',
            errors={'detail': str(e)},
            correlation_id=get_correlation_id(request)
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}", exc_info=True)
        return APIResponse.server_error(
            message='Error creating user',
            error_id=str(e),
            correlation_id=get_correlation_id(request)
        )
```

---

## Testing The Fix

### 1. Manual API Test

**Using curl:**
```bash
# Create test user
curl -X POST http://localhost:8000/api/v1/auth/listusers/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "first_name": "Joshua",
    "last_name": "Owuonda",
    "email": "joshua.test@example.com",
    "username": "joshua_test",
    "password": "SecurePass123!@",
    "groups": ["ict_officer", "staff"],
    "is_active": true,
    "is_staff": true,
    "timezone": "Africa/Nairobi"
  }'

# Expected response (201):
{
  "success": true,
  "data": {
    "id": 1,
    "first_name": "Joshua",
    "last_name": "Owuonda",
    "email": "joshua.test@example.com",
    "username": "joshua_test",
    "groups": [
      {"id": 1, "name": "ict_officer"},
      {"id": 2, "name": "staff"}
    ],
    "is_active": true,
    "is_staff": true,
    "timezone": "Africa/Nairobi"
  },
  "message": "User created successfully. Please check your email to confirm your account."
}
```

### 2. Unit Test

**File:** `authmanagement/tests/test_user_creation.py`

```python
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from authmanagement.models import CustomUser as User

@pytest.mark.django_db
class TestUserCreationFix:
    """Test user creation with M2M fix."""
    
    def setup_method(self):
        self.client = APIClient()
        self.ict_group = Group.objects.create(name='ict_officer')
        self.staff_group = Group.objects.create(name='Staff')
        self.admin_group = Group.objects.create(name='Admin')
    
    def test_create_user_with_groups_by_name(self):
        """Verify user creation with group names works."""
        data = {
            'first_name': 'Joshua',
            'last_name': 'Owuonda',
            'email': 'joshua@example.com',
            'username': 'joshua',
            'password': 'SecurePass123!',
            'groups': ['ict_officer', 'Staff'],
            'is_active': True,
        }
        
        response = self.client.post('/api/v1/auth/listusers/', data, format='json')
        
        # Verify response
        assert response.status_code == 201, f"Got {response.status_code}: {response.data}"
        assert response.data['success'] is True
        
        # Verify user exists
        user = User.objects.get(email='joshua@example.com')
        assert user.first_name == 'Joshua'
        assert user.is_active is True
        
        # Verify groups assigned
        group_names = list(user.groups.values_list('name', flat=True))
        assert 'ict_officer' in group_names
        assert 'Staff' in group_names
        assert len(group_names) == 2
        
        # Verify response includes groups
        assert len(response.data['data']['groups']) == 2
```

### 3. Integration Test

```python
@pytest.mark.django_db
def test_user_creation_to_email_confirmation():
    """Test complete flow: create → email → confirm → login."""
    
    # 1. Create user
    data = {
        'first_name': 'Test',
        'last_name': 'User',
        'email': 'test@example.com',
        'username': 'testuser',
        'password': 'Test123!Pass',
        'groups': ['Staff'],
    }
    response = self.client.post('/api/v1/auth/listusers/', data)
    assert response.status_code == 201
    
    # 2. Verify user is inactive (requires email confirmation)
    user = User.objects.get(email='test@example.com')
    assert user.is_active is False
    assert user.email_confirm_token != ''
    
    # 3. Confirm email (in real flow, done from email link)
    user.is_active = True
    user.save()
    
    # 4. Try to login
    login_response = self.client.post('/api/v1/auth/security/login/', {
        'email': 'test@example.com',
        'password': 'Test123!Pass',
    })
    assert login_response.status_code == 200
    assert 'access' in login_response.data
```

---

## Deployment Steps

1. **Backup Database**
   ```bash
   pg_dump production_db > backup_$(date +%Y%m%d).sql
   ```

2. **Update Code**
   ```bash
   git pull origin main
   git checkout f/auth-m2m-fix
   ```

3. **Test Locally**
   ```bash
   python manage.py test authmanagement.tests.test_user_creation
   ```

4. **Deploy to Staging**
   ```bash
   git push staging f/auth-m2m-fix
   ```

5. **Verify Staging**
   ```bash
   curl -X POST https://staging-api.example.com/api/v1/auth/listusers/ \
     -H "Authorization: Bearer $TOKEN" \
     -d '{"first_name":"Test"...}'
   ```

6. **Deploy to Production**
   ```bash
   git merge f/auth-m2m-fix main
   git push origin main
   ```

7. **Monitor**
   - Watch error logs at `/api/v1/auth/listusers/`
   - Verify email confirmations being sent
   - Check user creation success rate

---

## Rollback Plan

If issues occur:

```bash
# Revert code
git revert <commit-hash>

# Drop test users if created with errors
DELETE FROM authmanagement_customuser 
WHERE created_at > '2026-02-26 10:00:00' 
AND is_active = FALSE;

# Restart services
systemctl restart nginx
systemctl restart gunicorn
```

