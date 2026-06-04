"""
Phase 4 tests: POS-adapted shift planner — cycle resolution, override precedence, slot upsert.
"""
from datetime import date, time

from django.test import TestCase

from hrm.employees.models import Employee, CustomUser
from hrm.attendance.shift_planner_models import (
    ShiftRoster, ShiftRosterSlot, ShiftAssignment, StaffShiftOverride,
)
from hrm.attendance.shift_planner_api import _resolve_one


class ShiftPlannerTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(email="rota@example.com", password="x", first_name="Rota", last_name="Staff")
        self.employee = Employee.objects.create(
            user=self.user, gender="Female", date_of_birth=date(1992, 5, 5),
            residential_status="Resident", national_id="ID-ROTA", pin_no="P-RT",
            shif_or_nhif_number="SH-RT", nssf_no="NS-RT",
        )
        # 2-week roster anchored on a Monday; day 1 works 08:00-17:00, day 3 is off.
        self.roster = ShiftRoster.objects.create(name="2-Week A", cycle_days=14, start_date=date(2026, 6, 1))
        ShiftRosterSlot.objects.create(roster=self.roster, employee=self.employee, cycle_day=1,
                                       start_time=time(8, 0), end_time=time(17, 0))
        ShiftRosterSlot.objects.create(roster=self.roster, employee=self.employee, cycle_day=3, is_off_day=True)
        self.assignment = ShiftAssignment.objects.create(
            employee=self.employee, roster=self.roster, start_date=date(2026, 6, 1), is_active=True)

    def _indexes(self):
        assignments_by_emp = {self.employee.id: [self.assignment]}
        slots_index = {(s.roster_id, s.employee_id, s.cycle_day): s for s in ShiftRosterSlot.objects.all()}
        overrides_index = {(o.employee_id, o.date): o for o in StaffShiftOverride.objects.filter(status="approved")}
        return assignments_by_emp, slots_index, overrides_index

    def test_cycle_day_resolution(self):
        self.assertEqual(self.roster.cycle_day_for(date(2026, 6, 1)), 1)
        self.assertEqual(self.roster.cycle_day_for(date(2026, 6, 3)), 3)
        self.assertEqual(self.roster.cycle_day_for(date(2026, 6, 15)), 1)  # wraps after 14 days

    def test_roster_slot_working_and_off(self):
        a, s, o = self._indexes()
        working = _resolve_one(self.employee.id, date(2026, 6, 1), a, s, o)
        self.assertEqual(working["status"], "working")
        self.assertEqual(working["start_time"], "08:00:00")
        off = _resolve_one(self.employee.id, date(2026, 6, 3), a, s, o)
        self.assertEqual(off["status"], "off")
        self.assertEqual(off["source"], "roster")

    def test_override_takes_precedence(self):
        StaffShiftOverride.objects.create(
            employee=self.employee, date=date(2026, 6, 1), override_type="off_duty",
            status="approved", reason="Medical")
        a, s, o = self._indexes()
        res = _resolve_one(self.employee.id, date(2026, 6, 1), a, s, o)
        self.assertEqual(res["status"], "off")
        self.assertEqual(res["source"], "override")

    def test_unassigned_when_outside_window(self):
        a, s, o = self._indexes()
        res = _resolve_one(self.employee.id, date(2026, 5, 1), a, s, o)  # before assignment start
        self.assertEqual(res["status"], "unassigned")


class OvertimeComputationTest(TestCase):
    def test_overtime_split_per_rule(self):
        from decimal import Decimal
        from hrm.attendance.models import AttendanceRecord, AttendanceRule
        user = CustomUser.objects.create_user(email="ot@example.com", password="x", first_name="O", last_name="T")
        emp = Employee.objects.create(
            user=user, gender="Male", date_of_birth=date(1990, 1, 1), residential_status="Resident",
            national_id="ID-OT", pin_no="P-OT", shif_or_nhif_number="SH-OT", nssf_no="NS-OT")
        AttendanceRule.objects.create(name="OT", rule_type="overtime_policy", is_active=True,
                                      overtime_threshold_hours=Decimal("8.00"),
                                      overtime_rate_multiplier=Decimal("1.50"),
                                      max_overtime_hours=Decimal("4.00"), min_work_hours=Decimal("6.00"))
        rec = AttendanceRecord(employee=emp, date=date(2026, 6, 1), total_seconds_worked=10 * 3600, check_out=date(2026, 6, 1))
        reg, ot = rec.compute_hours()
        self.assertEqual(reg, Decimal("8.00"))
        self.assertEqual(ot, Decimal("2.00"))

    def test_overtime_capped_and_half_day(self):
        from decimal import Decimal
        from hrm.attendance.models import AttendanceRecord, AttendanceRule
        user = CustomUser.objects.create_user(email="hd@example.com", password="x", first_name="H", last_name="D")
        emp = Employee.objects.create(
            user=user, gender="Male", date_of_birth=date(1990, 1, 1), residential_status="Resident",
            national_id="ID-HD", pin_no="P-HD", shif_or_nhif_number="SH-HD", nssf_no="NS-HD")
        AttendanceRule.objects.create(name="OT2", rule_type="overtime_policy", is_active=True,
                                      overtime_threshold_hours=Decimal("8.00"), max_overtime_hours=Decimal("4.00"),
                                      min_work_hours=Decimal("6.00"))
        # 15h worked -> overtime capped at 4
        rec = AttendanceRecord(employee=emp, date=date(2026, 6, 2), total_seconds_worked=15 * 3600, check_out=date(2026, 6, 2))
        reg, ot = rec.compute_hours()
        self.assertEqual(ot, Decimal("4.00"))
        # 4h worked -> half-day
        rec2 = AttendanceRecord(employee=emp, date=date(2026, 6, 3), total_seconds_worked=4 * 3600, check_out=date(2026, 6, 3))
        rec2.compute_hours()
        self.assertEqual(rec2.status, "half-day")


class LateDetectionTest(TestCase):
    def test_late_status_applied_with_grace(self):
        from datetime import time, datetime, timezone as dttz
        from decimal import Decimal
        from django.utils import timezone
        from hrm.attendance.models import AttendanceRecord, WorkShift, WorkShiftSchedule
        user = CustomUser.objects.create_user(email="late@example.com", password="x", first_name="La", last_name="Te")
        emp = Employee.objects.create(
            user=user, gender="Male", date_of_birth=date(1990, 1, 1), residential_status="Resident",
            national_id="ID-LATE", pin_no="P-LT", shif_or_nhif_number="SH-LT", nssf_no="NS-LT")
        shift = WorkShift.objects.create(name="Day", start_time=time(8, 0), grace_minutes=15)
        # 2026-06-01 is a Monday
        WorkShiftSchedule.objects.create(work_shift=shift, day="Monday", start_time=time(8, 0), end_time=time(17, 0))
        # Check-in at 08:30 local (past 08:15 grace) -> late
        ci = timezone.make_aware(datetime(2026, 6, 1, 8, 30))
        rec = AttendanceRecord(employee=emp, work_shift=shift, date=date(2026, 6, 1), check_in=ci, status="present")
        rec.apply_late_status()
        self.assertEqual(rec.status, "late")
        # Within grace (08:10) -> stays present
        ci2 = timezone.make_aware(datetime(2026, 6, 1, 8, 10))
        rec2 = AttendanceRecord(employee=emp, work_shift=shift, date=date(2026, 6, 1), check_in=ci2, status="present")
        rec2.apply_late_status()
        self.assertEqual(rec2.status, "present")
