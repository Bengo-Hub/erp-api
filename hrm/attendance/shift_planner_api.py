"""
Shift planner API — serializers, viewsets and the roster-resolution endpoint that powers the
week-grid planner UI. Adapts the pos-api shift endpoints (roster CRUD, atomic slot upsert,
per-date overrides, resolve-for-range) to Django/DRF.
"""
from datetime import datetime, date, timedelta

from django.db import transaction
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .shift_planner_models import ShiftRoster, ShiftRosterSlot, ShiftAssignment, StaffShiftOverride


# ── Serializers ────────────────────────────────────────────────────────────────
class ShiftRosterSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftRosterSlot
        fields = ["id", "roster", "employee", "cycle_day", "start_time", "end_time", "is_off_day"]
        extra_kwargs = {"roster": {"required": False}}


class ShiftRosterSerializer(serializers.ModelSerializer):
    slots = ShiftRosterSlotSerializer(many=True, read_only=True)

    class Meta:
        model = ShiftRoster
        fields = ["id", "name", "outlet_id", "cycle_days", "start_date", "is_active", "slots",
                  "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class ShiftAssignmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()
    roster_name = serializers.CharField(source="roster.name", read_only=True)

    class Meta:
        model = ShiftAssignment
        fields = ["id", "employee", "employee_name", "roster", "roster_name", "start_date",
                  "end_date", "is_active", "created_at"]
        read_only_fields = ["created_at"]

    def get_employee_name(self, obj):
        return str(obj.employee)


class StaffShiftOverrideSerializer(serializers.ModelSerializer):
    employee_name = serializers.SerializerMethodField()

    class Meta:
        model = StaffShiftOverride
        fields = ["id", "employee", "employee_name", "outlet_id", "date", "override_type",
                  "start_time", "end_time", "reason", "status", "created_by", "approved_by",
                  "created_at", "updated_at"]
        read_only_fields = ["created_by", "approved_by", "created_at", "updated_at"]

    def get_employee_name(self, obj):
        return str(obj.employee)

    def validate(self, attrs):
        otype = attrs.get("override_type")
        if otype in ("manual_shift", "half_day") and not (attrs.get("start_time") and attrs.get("end_time")):
            raise serializers.ValidationError("start_time and end_time are required for manual_shift / half_day.")
        return attrs


# ── ViewSets ───────────────────────────────────────────────────────────────────
class ShiftRosterViewSet(viewsets.ModelViewSet):
    queryset = ShiftRoster.objects.all().prefetch_related("slots")
    serializer_class = ShiftRosterSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["get", "put"])
    def slots(self, request, pk=None):
        """GET lists the roster's slots; PUT atomically replaces the full slot set (pos-style upsert)."""
        roster = self.get_object()
        if request.method == "GET":
            return Response(ShiftRosterSlotSerializer(roster.slots.all(), many=True).data)

        payload = request.data if isinstance(request.data, list) else request.data.get("slots", [])
        with transaction.atomic():
            roster.slots.all().delete()
            created = []
            for item in payload:
                created.append(ShiftRosterSlot(
                    roster=roster,
                    employee_id=item["employee"],
                    cycle_day=item["cycle_day"],
                    start_time=item.get("start_time"),
                    end_time=item.get("end_time"),
                    is_off_day=item.get("is_off_day", False),
                ))
            ShiftRosterSlot.objects.bulk_create(created)
        return Response(ShiftRosterSlotSerializer(roster.slots.all(), many=True).data, status=status.HTTP_200_OK)


class ShiftAssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = ShiftAssignmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ShiftAssignment.objects.select_related("employee", "roster")
        emp = self.request.query_params.get("employee")
        if emp:
            qs = qs.filter(employee_id=emp)
        roster = self.request.query_params.get("roster")
        if roster:
            qs = qs.filter(roster_id=roster)
        return qs


class StaffShiftOverrideViewSet(viewsets.ModelViewSet):
    serializer_class = StaffShiftOverrideSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = StaffShiftOverride.objects.select_related("employee")
        p = self.request.query_params
        if p.get("employee"):
            qs = qs.filter(employee_id=p["employee"])
        if p.get("from"):
            qs = qs.filter(date__gte=p["from"])
        if p.get("to"):
            qs = qs.filter(date__lte=p["to"])
        return qs

    def perform_create(self, serializer):
        # Manager-created overrides auto-approve; otherwise leave the serializer default (approved).
        serializer.save(created_by=self.request.user if self.request.user.is_authenticated else None,
                        approved_by=self.request.user if self.request.user.is_authenticated else None)


# ── Roster resolution (planner data) ─────────────────────────────────────────────
def _resolve_one(employee_id, on_date, assignments_by_emp, slots_index, overrides_index):
    """Resolve an employee's effective schedule for a date: override > roster slot > unassigned."""
    ov = overrides_index.get((employee_id, on_date))
    if ov:
        if ov.override_type == "off_duty":
            return {"status": "off", "source": "override", "reason": ov.reason}
        return {"status": "working", "source": "override", "override_type": ov.override_type,
                "start_time": str(ov.start_time) if ov.start_time else None,
                "end_time": str(ov.end_time) if ov.end_time else None}

    for assignment in assignments_by_emp.get(employee_id, []):
        if assignment.covers(on_date):
            cd = assignment.roster.cycle_day_for(on_date)
            slot = slots_index.get((assignment.roster_id, employee_id, cd))
            if slot is None:
                continue
            if slot.is_off_day:
                return {"status": "off", "source": "roster"}
            return {"status": "working", "source": "roster", "roster": assignment.roster.name,
                    "start_time": str(slot.start_time) if slot.start_time else None,
                    "end_time": str(slot.end_time) if slot.end_time else None}
    return {"status": "unassigned"}


class ShiftPlannerResolveView(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        """GET resolve?from=YYYY-MM-DD&to=YYYY-MM-DD[&employee_ids=1,2] → schedule per employee per date."""
        try:
            d_from = datetime.strptime(request.query_params["from"], "%Y-%m-%d").date()
            d_to = datetime.strptime(request.query_params["to"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            return Response({"error": "from and to (YYYY-MM-DD) are required"}, status=status.HTTP_400_BAD_REQUEST)
        if d_to < d_from or (d_to - d_from).days > 62:
            return Response({"error": "invalid range (max 62 days)"}, status=status.HTTP_400_BAD_REQUEST)

        emp_filter = request.query_params.get("employee_ids")
        assignments = ShiftAssignment.objects.select_related("roster").filter(is_active=True)
        if emp_filter:
            ids = [int(x) for x in emp_filter.split(",") if x.strip().isdigit()]
            assignments = assignments.filter(employee_id__in=ids)

        assignments_by_emp = {}
        roster_ids = set()
        emp_ids = set()
        for a in assignments:
            assignments_by_emp.setdefault(a.employee_id, []).append(a)
            roster_ids.add(a.roster_id)
            emp_ids.add(a.employee_id)

        slots_index = {
            (s.roster_id, s.employee_id, s.cycle_day): s
            for s in ShiftRosterSlot.objects.filter(roster_id__in=roster_ids)
        }
        overrides_index = {
            (o.employee_id, o.date): o
            for o in StaffShiftOverride.objects.filter(date__gte=d_from, date__lte=d_to, status="approved")
        }

        days = [(d_from + timedelta(days=i)) for i in range((d_to - d_from).days + 1)]
        result = {}
        for emp_id in emp_ids:
            result[emp_id] = {
                d.isoformat(): _resolve_one(emp_id, d, assignments_by_emp, slots_index, overrides_index)
                for d in days
            }
        return Response({"from": d_from.isoformat(), "to": d_to.isoformat(), "schedule": result})
