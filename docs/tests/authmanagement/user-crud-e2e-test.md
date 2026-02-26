# Authentication & User Management - E2E Test Analysis

**Date:** February 26, 2026  
**Status:** 🔴 **CRITICAL ISSUE** – User creation endpoint broken  
**Affected Endpoint:** `POST /api/v1/auth/listusers/`

---

## Issue Report

### Error Details
```
Request: POST https://erpapi.masterspace.co.ke/api/v1/auth/listusers/
Status: 500 Internal Server Error

Payload:
{
    "first_name": "Joshua",
    "last_name": "Owuonda",
    "middle_name": "Were",
    "email": "joshuaowuonda41@gmail.com",
    "username": "joshowuonda",
    "phone": "+254799732318",
    "password": "ChnageMe123!",
    "groups": ["superusers", "ict_officer"],
    "is_active": true,
    "is_staff": true,
    "timezone": "Africa/Nairobi"
}

Response:
{
    "success": false,
    "error": {
        "type": "ValueError",
        "detail": "\"<CustomUser: Joshua Owuonda>\" needs to have a value for field \"id\" before this many-to-many relationship can be used."
    }
}
```

### Root Cause Analysis

**Primary Issue:** Many-to-many relationship (groups) assignment timing  
**Location:** `authmanagement/serializers.py` - `UserSerializer.create()` method  
**Severity:** Critical – Prevents all user creation through API

**Problem Breakdown:**

1. **Signal Handlers Triggering Too Early**
   - Django model save signals may be triggering M2M assignment before transaction commit
   - Post-save signal handlers attempting to access unsaved object's ID

2. **Serializer Validation Conflict**
   - The `UserSerializer.create()` method tries to add groups via `user.groups.add(role)`
   - However, transaction isolation or signal timing may cause the user object to not have an ID yet in the transaction context
   - The error suggests the object is being passed to a M2M operation without a persisted ID

3. **Transaction Management**
   - The `create()` method doesn't explicitly wrap group assignment in `transaction.atomic()`
   - Without proper transaction handling, the user save and M2M add may be in different transaction scopes

4. **Potential Code Execution Issue**
   - The `setattr()` or direct M2M operations may be triggering model signals that expect the object to be fully persisted
   - The `BaseModelViewSet.create()` inherited behavior might also be involved

---

## Current Auth Workflow

### 1. User Registration Flow
```
Frontend (Vue.js)
    ↓
Axios POST /auth/listusers/ or /auth/register/
    ↓
authmanagement.views.UserViewSet.post()
    ↓
UserSerializer.create()
    ├─ Validate input (email unique, password policy, etc.)
    ├─ Create CustomUser instance (not saved)
    ├─ Set password via user.set_password()
    ├─ Save user (first save – obtains ID)
    ├─ Extract groups from validated_data
    ├─ [ERROR OCCURS HERE] Try to add groups via user.groups.add()
    ├─ Create/assign Staff group
    └─ Return saved user instance
    ↓
Response: User serialized data OR error
```

### 2. Authentication Flow
```
Frontend /login
    ↓
POST /api/v1/auth/security/login/ (EnhancedLoginView)
    ↓
Email + password validation
    ↓
JWT token generation (SimpleJWT)
    ↓
Return access + refresh tokens + user data
```

### 3. User List/Retrieve Flow
```
GET /api/v1/auth/listusers/ (no pk)
    ↓
Check if superuser: return all users
    ↓
Else: filter by business ownership / employee association
    ↓
Serialize and return
```

### 4. User Update Flow
```
PUT/PATCH /api/v1/auth/listusers/<id>/
    ↓
UserViewSet.put() or .patch()
    ↓
UserSerializer.update()
    ├─ Update basic fields
    ├─ Handle password change if provided
    ├─ Handle groups via user.groups.set()
    └─ Save and return
    ↓
Response: Updated user or validation errors
```

---

## Root Cause Investigation

### Code Trace

**File:** `authmanagement/serializers.py:120-170`

```python
def create(self, validated_data):
    try:
        # STEP 1: Extract groups (write-only field)
        selectedroles = validated_data.pop('groups', None)
        
        # STEP 2: Create user instance (not yet in DB)
        user = User(
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            middle_name=validated_data['middle_name'],
            username=validated_data['username'],
            email=validated_data['email'],
            phone=validated_data.get('phone'),
            pic=validated_data.get('pic'),
        )
        
        # STEP 3: Set password
        if validated_data.get('password'):
            user.set_password(validated_data['password'])
        else:
            raise serializers.ValidationError({'password': 'This field is required.'})
        
        # STEP 4: First save (obtains ID)
        user.save()  # ← User now has ID
        
        # STEP 5: Get or create Staff group
        staff_group = Group.objects.filter(name__iexact='staff').first()
        if not staff_group:
            staff_group = Group.objects.create(name='Staff')
        
        # STEP 6: Set is_active and save again (potential issue?)
        user.is_active = False
        user.save()
        
        # STEP 7: Assign roles - CRITICAL POINT
        # ❌ ERROR OCCURS HERE: user.groups.add(role)
        if selectedroles:
            # This code tries to handle both IDs and names
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
            
            # THIS LINE THROWS ERROR:
            for role in roles:
                user.groups.add(role)  # ← ValueError on M2M relationship
        
        # ... rest of code
```

### Diagnosis

The error `"needs to have a value for field 'id'"` typically means:
1. The object's primary key was not successfully committed before accessing the M2M relationship
2. The transaction may have rolled back
3. A signal handler is attempting the M2M operation before the object's ID is available in the current session

**Likely Culprits:**
- Django signal handlers on `CustomUser` model triggering before commit
- Missing `@transaction.atomic()` decorator or context manager
- Implicit transaction rollback due to validation error in one of the `.save()` calls
- Issue with how DRF's serializer calls methods vs. the model's signal handlers

---

## Frontend Integration Issues

**File:** `bengobox-erp-ui/src/services/auth/userManagementService.js`

### Current Implementation
```javascript
async createUser(userData) {
    try {
        return await axios.post('/auth/listusers/', userData);
    } catch (error) {
        console.error('Error creating user:', error);
        throw error;
    }
}
```

### Issues:
1. ❌ No error handling specific to M2M relationship issues
2. ❌ No retry logic for transient failures
3. ❌ No pre-validation of groups before sending to API
4. ❌ No clear mapping of form inputs to API contract

### Expected Payload Format
```javascript
{
    "first_name": "Joshua",
    "last_name": "Owuonda",
    "middle_name": "Were",
    "email": "joshuaowuonda41@gmail.com",
    "username": "joshowuonda",
    "phone": "+254799732318",
    "password": "ChnageMe123!",
    "groups": ["superusers", "ict_officer"],  // Array of group names or IDs
    "is_active": true,
    "is_staff": true,
    "timezone": "Africa/Nairobi"
}
```

---

## Workflow Gaps & Issues

### Backend Issues
| # | Issue | Severity | Impact |
|---|-------|----------|--------|
| 1 | M2M relationship error in user creation | 🔴 Critical | Users cannot be created via API |
| 2 | No transaction.atomic() wrapping | 🟠 High | Data consistency issues possible |
| 3 | Inconsistent endpoint naming (`listusers` not RESTful) | 🟡 Medium | Confusing API contract |
| 4 | APIView instead of ViewSet for user CRUD | 🟡 Medium | Missing automatic routing/docs |
| 5 | No input validation for groups | 🟠 High | Invalid group names silently ignored |
| 6 | Email send logic in try-except but not async | 🟡 Medium | Blocks request if email fails |
| 7 | User created with `is_active=False` by default | 🟠 High | Users cannot login until email confirmation |
| 8 | No password policy enforcement in serializer | 🟡 Medium | Invalid passwords might be accepted |

### Frontend Issues
| # | Issue | Severity | Impact |
|---|-------|----------|--------|
| 1 | Generic error handling in createUser() | 🟠 High | Poor UX when M2M error occurs |
| 2 | No groups pre-validation before API call | 🟡 Medium | Invalid groups sent undetected |
| 3 | Endpoint URL inconsistency with backend | 🟡 Medium | Frontend/backend may diverge |
| 4 | No loading state management | 🟡 Medium | User can submit multiple times |
| 5 | No fields missing validation | 🟡 Medium | API rejected requests with poor feedback |

---

## Test Cases Failing

### 1. **Create User with Groups**
```
Input: Valid user data with groups array
Expected: User created with groups assigned
Actual: 500 ValueError on M2M relationship
Status: ❌ FAILING
```

### 2. **Create User without Groups**
```
Input: Valid user data, no groups
Expected: User created with default Staff group
Actual: Unknown (needs testing)
Status: ⚠️ UNTESTED
```

### 3. **Create User with Invalid Group**
```
Input: User data with non-existent group names
Expected: 400 Validation error
Actual: Unknown (needs testing)
Status: ⚠️ UNTESTED
```

### 4. **Update User Groups**
```
Input: Valid user, new groups array
Expected: Groups updated via user.groups.set()
Actual: Unknown (needs testing)
Status: ⚠️ UNTESTED
```

### 5. **List Users (Superuser)**
```
Input: Superuser auth token
Expected: All users returned
Actual: Unknown (needs testing)
Status: ⚠️ UNTESTED
```

### 6. **List Users (Non-Superuser)**
```
Input: Regular user auth token
Expected: Filtered users (business/employee association)
Actual: Unknown (needs testing)
Status: ⚠️ UNTESTED
```

---

## Fix Implementation Plan

### Phase 1: Critical Fix (Immediate)

#### 1.1 Fix User Creation M2M Error
**File:** `authmanagement/serializers.py`  
**Method:** `UserSerializer.create()`

**Changes:**
```python
@transaction.atomic
def create(self, validated_data):
    """
    Create user with groups assignment.
    Uses transaction.atomic() to ensure M2M relationships work correctly.
    """
    try:
        # Extract groups (must be before popping validated_data)
        selectedroles = validated_data.pop('groups', None)
        
        # Create user instance
        user = User(
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            middle_name=validated_data.get('middle_name', ''),
            username=validated_data['username'],
            email=validated_data['email'],
            phone=validated_data.get('phone', ''),
            pic=validated_data.get('pic'),
            timezone=validated_data.get('timezone', 'Africa/Nairobi'),
        )
        
        # Handle password
        password = validated_data.get('password')
        if not password:
            raise serializers.ValidationError({'password': 'Password is required.'})
        user.set_password(password)
        
        # Important: Set is_active BEFORE saving to avoid double-save
        user.is_active = validated_data.get('is_active', False)
        user.is_staff = validated_data.get('is_staff', False)
        
        # Save user (obtains ID required for M2M)
        user.save()
        
        # NOW handle groups (after user has ID)
        if selectedroles:
            self._assign_groups_to_user(user, selectedroles)
        else:
            # Assign default Staff group if no groups provided
            staff_group, _ = Group.objects.get_or_create(name='Staff')
            user.groups.add(staff_group)
        
        # Create auth token
        Token.objects.create(user=user)
        
        # Send confirmation email asynchronously
        self._send_confirmation_email_async(user)
        
        return user
        
    except Exception as e:
        # Clean up on error
        if user.pk:
            user.delete()
        raise

def _assign_groups_to_user(self, user, selectedroles):
    """
    Safely assign groups to user.
    Handles both group IDs and group names (case-insensitive).
    """
    if not selectedroles:
        return
    
    ids = []
    names = []
    
    for role in selectedroles:
        try:
            # Try to convert to int (group ID)
            ids.append(int(role))
        except (TypeError, ValueError):
            # Treat as group name
            names.append(str(role).strip())
    
    # Build query for groups by ID or name
    q = Q(id__in=ids) if ids else Q()
    for name in names:
        q |= Q(name__iexact=name)
    
    if q:
        groups = Group.objects.filter(q)
        if groups.exists():
            user.groups.set(groups)
        else:
            logger.warning(f"No groups found for: {selectedroles}")

def _send_confirmation_email_async(self, user):
    """
    Send confirmation email asynchronously.
    Prevents blocking the request if email fails.
    """
    try:
        from notifications.services import EmailService
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode
        
        token = default_token_generator.make_token(user)
        user.email_confirm_token = token
        user.save(update_fields=['email_confirm_token'])
        
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        
        # Queue async email send (would use Celery in production)
        email_service = EmailService()
        email_service.send_email(
            subject='Confirm your BengoBox ERP registration',
            recipient_list=[user.email],
            template='auth/confirm_email.html',
            context={'user': user, 'uid': uid, 'token': token},
            async_send=True
        )
    except Exception as e:
        logger.error(f"Failed to send confirmation email for user {user.id}: {e}")
        # Don't raise – email failure shouldn't block user creation
```

#### 1.2 Fix UserViewSet Response Format
**File:** `authmanagement/views.py`  
**Class:** `UserViewSet`

**Changes:**
```python
def post(self, request, format=None):
    """
    Create a new user with proper error handling.
    """
    try:
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return APIResponse.created(
                data=serializer.to_representation(user),
                message='User created successfully. Please check your email to confirm.',
                correlation_id=get_correlation_id(request)
            )
        return APIResponse.validation_error(
            errors=serializer.errors,
            correlation_id=get_correlation_id(request)
        )
    except serializers.ValidationError as e:
        logger.error(f"Validation error creating user: {e}")
        return APIResponse.validation_error(
            errors={'detail': str(e)},
            correlation_id=get_correlation_id(request)
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}", exc_info=True)
        return APIResponse.server_error(
            message='Failed to create user',
            error_id=str(e),
            correlation_id=get_correlation_id(request)
        )
```

---

### Phase 2: API Design Improvements (Next Sprint)

#### 2.1 Migrate to ModelViewSet
**Replace:** `APIView`-based `UserViewSet`  
**Use:** `BaseModelViewSet` (already used in rest of app)

**Benefits:**
- Automatic routing via `DefaultRouter`
- Consistent with other modules
- Better Swagger/OpenAPI docs
- Less boilerplate code

**Example:**
```python
class UserViewSet(BaseModelViewSet):
    """User CRUD operations with approval workflow integration."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    def get_queryset(self):
        """Filter users based on permissions."""
        user = self.request.user
        if user.is_superuser:
            return User.objects.all()
        # Return only related users
        from hrm.employees.models import Employee
        employee_user_ids = Employee.objects.filter(
            organisation__owner=user
        ).values_list('user_id', flat=True)
        return User.objects.filter(id__in=list(employee_user_ids))
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a user account."""
        user = self.get_object()
        user.is_active = True
        user.save()
        return APIResponse.success(data={'status': 'activated'})
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a user account."""
        user = self.get_object()
        user.is_active = False
        user.save()
        return APIResponse.success(data={'status': 'deactivated'})
```

#### 2.2 Consistent Endpoint Naming
**Change:** `/api/v1/auth/listusers/` → `/api/v1/auth/users/`

**Update URLs:**
```python
from rest_framework.routers import DefaultRouter

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')
router.register(r'groups', GroupViewSet, basename='groups')

urlpatterns = [
    path('', include(router.urls)),
    # ... other paths
]
```

#### 2.3 Add Input Validation
**File:** `authmanagement/serializers.py`

```python
class UserSerializer(serializers.ModelSerializer):
    # ... existing fields ...
    
    def validate_password(self, value):
        """Validate password against policy."""
        from authmanagement.models import PasswordPolicy
        policy = PasswordPolicy.objects.first()
        if policy:
            if len(value) < policy.min_length:
                raise serializers.ValidationError(
                    f'Password must be at least {policy.min_length} characters.'
                )
            if policy.require_uppercase and not any(c.isupper() for c in value):
                raise serializers.ValidationError(
                    'Password must contain uppercase letters.'
                )
            if policy.require_lowercase and not any(c.islower() for c in value):
                raise serializers.ValidationError(
                    'Password must contain lowercase letters.'
                )
            if policy.require_numbers and not any(c.isdigit() for c in value):
                raise serializers.ValidationError(
                    'Password must contain numbers.'
                )
            if policy.require_special_chars and not any(
                c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in value
            ):
                raise serializers.ValidationError(
                    'Password must contain special characters.'
                )
        return value
    
    def validate_email(self, value):
        """Validate email uniqueness (case-insensitive)."""
        existing = User.objects.filter(email__iexact=value).first()
        if existing and (not self.instance or existing.pk != self.instance.pk):
            raise serializers.ValidationError('Email already in use.')
        return value.lower()
    
    def validate_username(self, value):
        """Validate username uniqueness and format."""
        if not value.isidentifier():
            raise serializers.ValidationError(
                'Username must contain only letters, numbers, and underscores.'
            )
        existing = User.objects.filter(username__iexact=value).first()
        if existing and (not self.instance or existing.pk != self.instance.pk):
            raise serializers.ValidationError('Username already in use.')
        return value.lower()
    
    def validate_groups(self, value):
        """Validate groups exist before assignment."""
        if not value:
            return value
        
        ids = []
        names = []
        for g in value:
            try:
                ids.append(int(g))
            except (TypeError, ValueError):
                names.append(str(g))
        
        q = Q(id__in=ids) if ids else Q()
        for name in names:
            q |= Q(name__iexact=name)
        
        groups = Group.objects.filter(q).count()
        expected = len(set(value))
        
        if groups != expected:
            raise serializers.ValidationError(
                f'One or more groups not found. Provided: {value}'
            )
        return value
```

---

### Phase 3: Testing & Documentation

#### 3.1 Unit Tests
**File:** `authmanagement/tests/test_user_creation.py`

```python
import pytest
from django.contrib.auth.models import Group
from rest_framework.test import APIClient
from authmanagement.models import CustomUser as User

@pytest.mark.django_db
class TestUserCreation:
    
    def setup_method(self):
        self.client = APIClient()
        # Create test groups
        self.group_admin = Group.objects.create(name='Admin')
        self.group_staff = Group.objects.create(name='Staff')
    
    def test_create_user_with_groups_by_name(self):
        """Test creating user with group names."""
        data = {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john@example.com',
            'username': 'johndoe',
            'password': 'SecurePass123!',
            'groups': ['Admin', 'Staff'],
        }
        
        response = self.client.post('/api/v1/auth/users/', data, format='json')
        
        assert response.status_code == 201
        user = User.objects.get(email='john@example.com')
        assert user.groups.count() == 2
        assert user.groups.filter(name='Admin').exists()
    
    def test_create_user_with_groups_by_id(self):
        """Test creating user with group IDs."""
        data = {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane@example.com',
            'username': 'janesmith',
            'password': 'SecurePass123!',
            'groups': [str(self.group_admin.id)],
        }
        
        response = self.client.post('/api/v1/auth/users/', data, format='json')
        
        assert response.status_code == 201
        user = User.objects.get(email='jane@example.com')
        assert user.groups.filter(id=self.group_admin.id).exists()
    
    def test_create_user_invalid_group(self):
        """Test creating user with non-existent group."""
        data = {
            'first_name': 'Bob',
            'last_name': 'Jones',
            'email': 'bob@example.com',
            'username': 'bobjones',
            'password': 'SecurePass123!',
            'groups': ['NonExistent'],
        }
        
        response = self.client.post('/api/v1/auth/users/', data, format='json')
        
        assert response.status_code == 400
        assert 'groups' in response.data['errors']
    
    def test_create_user_weak_password(self):
        """Test creating user with weak password."""
        data = {
            'first_name': 'Weak',
            'last_name': 'Pass',
            'email': 'weak@example.com',
            'username': 'weakpass',
            'password': 'simple',  # Too simple
            'groups': ['Staff'],
        }
        
        response = self.client.post('/api/v1/auth/users/', data, format='json')
        
        assert response.status_code == 400
        assert 'password' in response.data['errors']
    
    def test_create_user_duplicate_email(self):
        """Test creating user with duplicate email."""
        User.objects.create_user(
            email='existing@example.com',
            username='existing',
            password='Pass123!',
        )
        
        data = {
            'first_name': 'Dup',
            'last_name': 'Licate',
            'email': 'existing@example.com',
            'username': 'duplicate',
            'password': 'SecurePass123!',
            'groups': ['Staff'],
        }
        
        response = self.client.post('/api/v1/auth/users/', data, format='json')
        
        assert response.status_code == 400
        assert 'email' in response.data['errors']
```

#### 3.2 Integration Tests
```python
@pytest.mark.django_db
class TestUserWorkflow:
    
    def test_complete_user_creation_flow(self):
        """Test full user creation → confirmation → login flow."""
        # 1. Create user
        data = {
            'first_name': 'Flow',
            'last_name': 'Test',
            'email': 'flow@example.com',
            'username': 'flowtest',
            'password': 'SecurePass123!',
            'groups': ['Staff'],
        }
        response = self.client.post('/api/v1/auth/users/', data, format='json')
        assert response.status_code == 201
        
        # 2. Verify user is inactive
        user = User.objects.get(email='flow@example.com')
        assert not user.is_active
        
        # 3. Simulate email confirmation
        user.is_active = True
        user.save()
        
        # 4. Try to login
        login_response = self.client.post('/api/v1/auth/login/', {
            'email': 'flow@example.com',
            'password': 'SecurePass123!',
        })
        assert login_response.status_code == 200
        assert 'access' in login_response.data
```

---

## Implementation Timeline

| Phase | Task | Effort | Timeline |
|-------|------|--------|----------|
| 1 | Fix M2M error + error handling | 4h | **This week** |
| 1 | Add input validation | 3h | **This week** |
| 1 | Update tests | 4h | **This week** |
| 2 | Migrate to ModelViewSet | 4h | Next week |
| 2 | Update endpoint naming | 2h | Next week |
| 2 | Frontend integration fixes | 3h | Next week |
| 3 | Complete test suite | 8h | Following week |

**Total Effort:** ~28 hours (1 developer-week)

---

## Rollout Strategy

### Pre-Deployment
1. ✅ Fix critical M2M error
2. ✅ Run unit tests
3. ✅ Test with frontend locally
4. ✅ Code review

### Deployment
1. Deploy backend fixes to staging
2. Run integration tests against staging
3. Deploy frontend changes
4. Test end-to-end flow
5. Deploy to production

### Post-Deployment
1. Monitor error logs
2. Verify email confirmations working
3. Test user activation/deactivation
4. Verify group assignment

---

## Related Issues
- Missing email confirmation flow
- No user activation notifications
- Password policy not enforced
- No audit trail for user creation/updates
- Missing 2FA setup during user creation

---

## Success Criteria
✅ User creation succeeds with groups  
✅ Groups validated before M2M assignment  
✅ Email confirmation sent asyncly  
✅ User starts inactive, activated via email  
✅ Password policy enforced  
✅ All tests passing (>90% coverage)  
✅ API response time < 500ms for user creation  

