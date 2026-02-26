# Fix Implementation Checklist

**Status:** 🔴 TODO  
**Priority:** Critical  
**Target Date:** This Sprint  

---

## Phase 1: Critical Fix (Immediate)

### [ ] 1.1 Fix Serializer M2M Error

**File:** `authmanagement/serializers.py`

**Tasks:**
- [ ] Add `@transaction.atomic` decorator to `UserSerializer.create()`
- [ ] Extract `_assign_groups_to_user()` helper method
- [ ] Extract `_send_confirmation_email_async()` helper method
- [ ] Set `is_active` and `is_staff` BEFORE first save to avoid double-save
- [ ] Add error handling with proper rollback
- [ ] Test with groups by name
- [ ] Test with groups by ID
- [ ] Test without groups (defaults to Staff)

**Code Changes:**
```python
# Current (broken)
user.save()
# ... later ...
user.groups.add(role)  # ❌ Error

# Fixed
@transaction.atomic
def create(self, validated_data):
    # ... create user ...
    user.save()  # ✅ User has ID
    self._assign_groups_to_user(user, selectedroles)  # ✅ Safe now
```

---

### [ ] 1.2 Fix UserViewSet Response Format

**File:** `authmanagement/views.py`

**Tasks:**
- [ ] Update `UserViewSet.post()` to use `APIResponse.created()`
- [ ] Add proper error handling for serializer errors
- [ ] Add validation error responses
- [ ] Add 500 error handling
- [ ] Include correlation ID in all responses
- [ ] Test response structure

**Code Changes:**
```python
# Current (generic Response)
def post(self, request):
    serializer = UserSerializer(data=request.data)
    if serializer.is_valid():
        serializer.save()  # ❌ No error handling
        return Response(serializer.data)  # ❌ Generic response
    return Response(serializer.errors, status=400)

# Fixed
def post(self, request):
    try:
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return APIResponse.created(  # ✅ Structured response
                data=serializer.to_representation(user),
                message='User created successfully. Check email to confirm.',
            )
        return APIResponse.validation_error(
            errors=serializer.errors,
        )
    except Exception as e:
        return APIResponse.server_error(
            message='Failed to create user',
            error_id=str(e),
        )
```

---

### [ ] 1.3 Add Input Validation

**File:** `authmanagement/serializers.py`

**Tasks:**
- [ ] Add `validate_password()` method
  - [ ] Check against PasswordPolicy
  - [ ] Validate uppercase requirement
  - [ ] Validate lowercase requirement
  - [ ] Validate numbers requirement
  - [ ] Validate special chars requirement
  - [ ] Validate minimum length
- [ ] Add `validate_email()` method
  - [ ] Check uniqueness (case-insensitive)
  - [ ] Return lowercase
- [ ] Add `validate_username()` method
  - [ ] Check format (alphanumeric + underscore)
  - [ ] Check uniqueness (case-insensitive)
  - [ ] Return lowercase
- [ ] Add `validate_groups()` method
  - [ ] Check groups exist before assignment
  - [ ] Handle both IDs and names
  - [ ] Provide helpful error messages

---

### [ ] 1.4 Fix Double-Save Issue

**File:** `authmanagement/serializers.py`

**Current problematic code:**
```python
user.save()  # Save 1: creates user
# ... 
user.is_active = False  # Set flag
user.save()  # Save 2: updates user
# ...
user.groups.add(role)  # Try M2M here (may be in wrong transaction state)
```

**Fix:**
```python
user.is_active = validated_data.get('is_active', False)  # Set BEFORE save
user.is_staff = validated_data.get('is_staff', False)  # Set BEFORE save
user.save()  # Single save with all fields
# ...
user.groups.add(role)  # M2M now safe
```

---

### [ ] 1.5 Run Phase 1 Tests

**Commands:**
```bash
# Unit test: User creation with groups
pytest authmanagement/tests/test_user_creation.py::TestUserCreation::test_create_user_with_groups_by_name -v

# Manual test: POST to endpoint
curl -X POST http://localhost:8000/api/v1/auth/listusers/ \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Test",
    "last_name": "User",
    "email": "test@example.com",
    "username": "testuser",
    "password": "SecurePass123!",
    "groups": ["Staff"]
  }'

# Expected response
{
  "success": true,
  "data": {
    "id": 1,
    "first_name": "Test",
    "email": "test@example.com",
    "groups": [{"id": 1, "name": "Staff"}]
  },
  "message": "User created successfully. Check email to confirm."
}
```

---

## Phase 2: API Design (Next Sprint)

### [ ] 2.1 Migrate to ModelViewSet

**File:** `authmanagement/views.py`

**Changes:**
- [ ] Delete old `APIView`-based `UserViewSet` class
- [ ] Create new `BaseModelViewSet`-based `UserViewSet`
- [ ] Implement `get_queryset()` for permission filtering
- [ ] Add `@action` methods:
  - [ ] `activate` (POST /users/{id}/activate/)
  - [ ] `deactivate` (POST /users/{id}/deactivate/)
  - [ ] `reset-password` (POST /users/{id}/reset-password/)
  - [ ] `assign-role` (POST /users/{id}/assign-role/)
  - [ ] `remove-role` (POST /users/{id}/remove-role/)

---

### [ ] 2.2 Update URL Routing

**File:** `authmanagement/urls.py`

**Changes:**
- [ ] Create router: `router = DefaultRouter()`
- [ ] Register: `router.register(r'users', UserViewSet)`
- [ ] Include router: `urlpatterns = [..., path('', include(router.urls))]`
- [ ] Delete: `path('listusers/', ...)`
- [ ] Delete: `path('listusers/<int:pk>/', ...)`

**Before:**
```python
urlpatterns = [
    path('listusers/', UserViewSet.as_view(), name='users'),
    path('listusers/<int:pk>/', UserViewSet.as_view(), name='update_users'),
]
```

**After:**
```python
router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')

urlpatterns = [
    path('', include(router.urls)),
]
```

---

### [ ] 2.3 Update Frontend Service URLs

**File:** `bengobox-erp-ui/src/services/auth/userManagementService.js`

**Changes:**
- [ ] Replace all `/auth/listusers/` with `/auth/users/`
- [ ] Replace all `/auth/listusers/{id}/` with `/auth/users/{id}/`

**Before:**
```javascript
const response = await axios.post('/auth/listusers/', userData);
```

**After:**
```javascript
const response = await axios.post('/auth/users/', userData);
```

---

### [ ] 2.4 Add Frontend Error Handling

**File:** `bengobox-erp-ui/src/services/auth/userManagementService.js`

**Changes:**
- [ ] Add try-catch with specific error messages
- [ ] Map M2M errors to user-friendly messages
- [ ] Add validation error handling
- [ ] Add network error handling
- [ ] Add loading state management

**Example:**
```javascript
async createUser(userData) {
    try {
        const response = await axios.post('/auth/users/', userData);
        
        if (!response.data.success) {
            throw new Error(response.data.error?.detail || 'Failed to create user');
        }
        
        return response.data.data;
    } catch (error) {
        if (error.response?.status === 400) {
            const errors = error.response.data.errors;
            throw {
                type: 'validation',
                errors,  // { email: [...], password: [...] }
            };
        }
        if (error.response?.status === 500) {
            throw {
                type: 'server',
                message: 'Server error creating user. Please try again.',
            };
        }
        throw error;
    }
}
```

---

## Phase 3: Testing & Documentation (Following Week)

### [ ] 3.1 Complete Unit Test Suite

**File:** `authmanagement/tests/test_user_creation.py`

**Tests to add:**
- [ ] ✅ Create user with groups by name
- [ ] ✅ Create user with groups by ID
- [ ] ✅ Create user with invalid group
- [ ] ✅ Create user with weak password
- [ ] ✅ Create user with duplicate email
- [ ] ✅ Create user with invalid email format
- [ ] ✅ Create user without required fields
- [ ] ✅ Update user groups
- [ ] ✅ List users (superuser)
- [ ] ✅ List users (regular user)
- [ ] ✅ Activate user
- [ ] ✅ Deactivate user

**Command:**
```bash
pytest authmanagement/tests/ -v --cov=authmanagement
```

---

### [ ] 3.2 Complete Integration Tests

**File:** `authmanagement/tests/test_auth_workflow.py`

**Tests to add:**
- [ ] User creation → Email confirmation → Login
- [ ] Password reset flow
- [ ] Password change flow
- [ ] User activation/deactivation via API
- [ ] Group assignment/removal via API
- [ ] Superuser list all users
- [ ] Regular user list filtered users

---

### [ ] 3.3 Update API Documentation

**File:** `docs/API_AUTH.md` (create if not exists)

**Document:**
- [ ] User creation endpoint
- [ ] User list/retrieve endpoint
- [ ] User update endpoint
- [ ] User delete endpoint
- [ ] User activation/deactivation
- [ ] Password reset flow
- [ ] Email confirmation flow
- [ ] Error codes and messages
- [ ] Request/response examples

---

### [ ] 3.4 Add Code Comments

**File:** `authmanagement/serializers.py`

**Add docstrings to:**
- [ ] `UserSerializer` class
- [ ] `UserSerializer.create()`
- [ ] `UserSerializer.update()`
- [ ] `_assign_groups_to_user()`
- [ ] `_send_confirmation_email_async()`
- [ ] `validate_password()`
- [ ] `validate_email()`
- [ ] `validate_username()`
- [ ] `validate_groups()`

---

## Testing Checklist

### Manual Testing
```bash
# Setup
export API_URL="http://localhost:8000"
export ADMIN_TOKEN="your-admin-token"

# Test 1: Create user with groups
curl -X POST $API_URL/api/v1/auth/users/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Joshua",
    "last_name": "Owuonda",
    "email": "joshua@example.com",
    "username": "joshua",
    "password": "SecurePass123!",
    "groups": ["ict_officer", "staff"],
    "is_active": true
  }'
# Expected: 201 Created ✅

# Test 2: Verify groups assigned
curl -X GET $API_URL/api/v1/auth/users/?email=joshua@example.com \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Expected: groups array with 2 items ✅

# Test 3: Update user groups
curl -X PATCH $API_URL/api/v1/auth/users/1/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"groups": ["admin"]}'
# Expected: 200 OK, groups updated ✅

# Test 4: Invalid group
curl -X POST $API_URL/api/v1/auth/users/ \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "first_name": "Test",
    "last_name": "User",
    "email": "test@example.com",
    "username": "testuser",
    "password": "SecurePass123!",
    "groups": ["nonexistent"]
  }'
# Expected: 400 Bad Request, error message ✅
```

### Automated Testing
```bash
# Run all auth tests
pytest authmanagement/tests/ -v

# With coverage
pytest authmanagement/tests/ --cov=authmanagement --cov-report=html

# Run specific test
pytest authmanagement/tests/test_user_creation.py::TestUserCreation::test_create_user_with_groups_by_name -v
```

---

## Tracking & Progress

| Task | Owner | Status | Comments |
|------|-------|--------|----------|
| Fix M2M error | TBD | [ ] | Critical blocker |
| Add validation | TBD | [ ] | Prevents invalid data |
| Response formatting | TBD | [ ] | Improves UX |
| Unit tests | TBD | [ ] | Ensures quality |
| Integration tests | TBD | [ ] | End-to-end verification |
| ModelViewSet migration | TBD | [ ] | API design improvement |
| Frontend updates | TBD | [ ] | Consumer side fixes |
| Documentation | TBD | [ ] | Knowledge transfer |

---

## Sign-Off

- [ ] Code review approved
- [ ] All tests passing
- [ ] Staging deployment successful
- [ ] Frontend integration verified
- [ ] Production deployment complete
- [ ] Monitoring alerts configured
- [ ] Team trained on changes

---

## Notes

- Keep M2M fix minimal and focused – avoid schema changes
- User creation should be idempotent where possible
- Email confirmation is async – don't block request
- Consider adding audit trail for user creation/updates
- Plan for future multi-tenancy (business/organization context)
