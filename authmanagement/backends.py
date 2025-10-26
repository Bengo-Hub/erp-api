#email backend
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

User = get_user_model()

class EmailBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            # Get user by email (treat 'username' as email)
            user = User.objects.get(email=username)
            if user.check_password(password):
                # Check ESS login restrictions for employees
                try:
                    employee = user.employee
                    can_login, reason = employee.can_login_to_ess()
                    
                    if not can_login:
                        # Store the reason in the request for the view to access
                        if request:
                            request.ess_login_denied_reason = reason
                        # Return None to deny authentication
                        return None
                        
                except Exception as e:
                    # If user is not an employee or any error, allow login
                    # (This covers admin users, superusers, etc.)
                    pass
                
                return user
            return None  # Explicit return on password failure
        except User.DoesNotExist:
            return None  # User doesn't exist