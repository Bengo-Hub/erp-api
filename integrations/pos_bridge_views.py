"""
POS → ERP bridge endpoints.

Allows pos-api to record clock-in/out into HRM AttendanceRecords via a
lightweight S2S API (X-API-Key authentication).

POST /api/integrations/pos/clock-in/
    body: { "email": "staff@tenant.com", "outlet_id": "...", "shift_session_id": "..." }
    → creates or updates today's AttendanceRecord (check_in)

POST /api/integrations/pos/clock-out/
    body: { "email": "staff@tenant.com", "shift_session_id": "...", "total_minutes": 480 }
    → updates today's AttendanceRecord (check_out, total_seconds_worked)
"""

import logging

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.request import Request
from rest_framework.response import Response

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from authmanagement.models import CustomUser
from hrm.attendance.models import AttendanceRecord
from hrm.employees.models import Employee


class InternalServiceKeyAuthentication(BaseAuthentication):
    """Validates the X-API-Key header against INTERNAL_SERVICE_KEY setting."""

    def authenticate(self, request):
        key = request.META.get('HTTP_X_API_KEY', '')
        expected = getattr(settings, 'INTERNAL_SERVICE_KEY', '')
        if not expected:
            return None  # not configured — skip (dev mode)
        if key != expected:
            raise AuthenticationFailed('Invalid or missing X-API-Key')
        return (None, None)  # anonymous but authenticated

logger = logging.getLogger(__name__)


@api_view(['POST'])
@authentication_classes([InternalServiceKeyAuthentication])
def pos_clock_in(request: Request) -> Response:
    """
    Record a POS shift start as a check-in in HRM attendance.

    Body:
        email           str   — staff email (matches CustomUser.email)
        outlet_id       str   — POS outlet UUID (stored in notes)
        shift_session_id str  — POS session UUID (stored in notes)
    """
    email = request.data.get('email', '').strip().lower()
    outlet_id = request.data.get('outlet_id', '')
    session_id = request.data.get('shift_session_id', '')

    if not email:
        return Response({'error': 'email is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = CustomUser.objects.get(email__iexact=email)
    except CustomUser.DoesNotExist:
        return Response({'error': 'user not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        employee = user.employee
    except Employee.DoesNotExist:
        return Response({'error': 'no employee record for this user'}, status=status.HTTP_404_NOT_FOUND)

    today = timezone.localdate()
    now = timezone.now()

    record, created = AttendanceRecord.objects.get_or_create(
        employee=employee,
        date=today,
        defaults={
            'check_in': now,
            'status': 'present',
            'notes': f'POS clock-in: outlet={outlet_id} session={session_id}',
        },
    )

    if not created and record.check_in is None:
        record.check_in = now
        record.notes = f'POS clock-in: outlet={outlet_id} session={session_id}'
        record.save(update_fields=['check_in', 'notes', 'updated_at'])

    return Response({
        'status': 'ok',
        'attendance_id': record.pk,
        'employee_id': employee.pk,
        'date': str(today),
        'check_in': record.check_in.isoformat() if record.check_in else None,
        'created': created,
    })


@api_view(['POST'])
@authentication_classes([InternalServiceKeyAuthentication])
def pos_clock_out(request: Request) -> Response:
    """
    Record a POS shift end as a check-out in HRM attendance.

    Body:
        email           str   — staff email
        shift_session_id str  — POS session UUID
        total_minutes   int   — minutes worked this shift (from POS session)
    """
    email = request.data.get('email', '').strip().lower()
    total_minutes = int(request.data.get('total_minutes', 0))

    if not email:
        return Response({'error': 'email is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user = CustomUser.objects.get(email__iexact=email)
    except CustomUser.DoesNotExist:
        return Response({'error': 'user not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        employee = user.employee
    except Employee.DoesNotExist:
        return Response({'error': 'no employee record for this user'}, status=status.HTTP_404_NOT_FOUND)

    today = timezone.localdate()
    now = timezone.now()

    try:
        record = AttendanceRecord.objects.get(employee=employee, date=today)
    except AttendanceRecord.DoesNotExist:
        # Shift closed without a prior clock-in — create a minimal record
        record = AttendanceRecord.objects.create(
            employee=employee,
            date=today,
            check_out=now,
            total_seconds_worked=total_minutes * 60,
            status='present',
            notes='POS clock-out (no prior check-in)',
        )
        return Response({
            'status': 'ok',
            'attendance_id': record.pk,
            'date': str(today),
            'check_out': record.check_out.isoformat(),
        })

    record.check_out = now
    if total_minutes > 0:
        record.total_seconds_worked = total_minutes * 60
    elif record.check_in:
        delta = now - record.check_in
        record.total_seconds_worked = int(delta.total_seconds())
    record.save(update_fields=['check_out', 'total_seconds_worked', 'updated_at'])

    return Response({
        'status': 'ok',
        'attendance_id': record.pk,
        'date': str(today),
        'check_out': record.check_out.isoformat(),
        'total_seconds_worked': record.total_seconds_worked,
    })
