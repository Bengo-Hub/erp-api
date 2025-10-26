"""
Middleware for attendance module.
Auto-creates default Regular shift if it doesn't exist.
"""
from decimal import Decimal
from django.utils.deprecation import MiddlewareMixin


class DefaultShiftMiddleware(MiddlewareMixin):
    """
    Middleware that ensures the default 'Regular Shift' exists.
    Creates it on first request if it doesn't exist.
    """
    
    _shift_created = False  # Class variable to track if we've checked/created the shift
    
    def process_request(self, request):
        """Check and create Regular shift if needed"""
        if not DefaultShiftMiddleware._shift_created:
            self._ensure_regular_shift_exists()
            DefaultShiftMiddleware._shift_created = True
        return None
    
    def _ensure_regular_shift_exists(self):
        """Create Regular shift with Monday-Friday 8AM-5PM schedule and default rotation if it doesn't exist"""
        from hrm.attendance.models import WorkShift, WorkShiftSchedule, ShiftRotation
        from django.utils import timezone
        from datetime import timedelta
        
        try:
            # Check if Regular shift exists
            regular_shift = WorkShift.objects.filter(name='Regular Shift').first()
            
            if not regular_shift:
                # Create the Regular shift
                regular_shift = WorkShift.objects.create(
                    name='Regular Shift',
                    grace_minutes=15,
                    total_hours_per_week=Decimal('40.00')
                )
                
                # Define the default schedule (Monday-Friday, 8AM-5PM with 1 hour break)
                default_schedule = [
                    {'day': 'Monday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': True},
                    {'day': 'Tuesday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': True},
                    {'day': 'Wednesday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': True},
                    {'day': 'Thursday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': True},
                    {'day': 'Friday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': True},
                    {'day': 'Saturday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': False},
                    {'day': 'Sunday', 'start_time': '08:00', 'end_time': '17:00', 'break_hours': Decimal('1.0'), 'is_working_day': False},
                ]
                
                # Create schedule entries
                for schedule_item in default_schedule:
                    WorkShiftSchedule.objects.create(
                        work_shift=regular_shift,
                        **schedule_item
                    )
                
                # Create default rotation for Regular Shift
                default_rotation = ShiftRotation.objects.create(
                    title='Regular Shift Rotation',
                    current_active_shift=regular_shift,
                    run_duration=1,
                    run_unit='Months',
                    break_duration=0,
                    break_unit='Days',
                    next_change_date=timezone.now() + timedelta(days=30),
                    is_active=True
                )
                default_rotation.shifts.add(regular_shift)
                
                print(f"✓ Created default 'Regular Shift' with Monday-Friday 8AM-5PM schedule and rotation")
                
        except Exception as e:
            # Fail silently to avoid breaking the app
            # The shift will be created on next request
            print(f"Warning: Could not create Regular shift: {e}")
            pass

