"""Onboarding API — serializers, viewsets, and the start/complete-task actions."""
from django.utils import timezone
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .onboarding_models import EmployeeOnboarding, OnboardingTask


class OnboardingTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = OnboardingTask
        fields = ["id", "onboarding", "category", "title", "order", "is_done", "done_at", "assigned_to"]
        read_only_fields = ["done_at"]


class EmployeeOnboardingSerializer(serializers.ModelSerializer):
    tasks = OnboardingTaskSerializer(many=True, read_only=True)
    employee_name = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeOnboarding
        fields = ["id", "employee", "employee_name", "status", "probation_end_date",
                  "started_at", "completed_at", "tasks", "progress", "created_at"]
        read_only_fields = ["started_at", "completed_at", "created_at"]

    def get_employee_name(self, obj):
        return str(obj.employee)

    def get_progress(self, obj):
        tasks = list(obj.tasks.all())
        done = sum(1 for t in tasks if t.is_done)
        return {"done": done, "total": len(tasks)}


class EmployeeOnboardingViewSet(viewsets.ModelViewSet):
    queryset = EmployeeOnboarding.objects.all().prefetch_related("tasks")
    serializer_class = EmployeeOnboardingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        emp = self.request.query_params.get("employee")
        if emp:
            qs = qs.filter(employee_id=emp)
        return qs

    def perform_create(self, serializer):
        onboarding = serializer.save()
        onboarding.seed_default_tasks()

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """Seed the default checklist and move the onboarding to in_progress."""
        onboarding = self.get_object()
        onboarding.seed_default_tasks()
        return Response(self.get_serializer(onboarding).data)


class OnboardingTaskViewSet(viewsets.ModelViewSet):
    queryset = OnboardingTask.objects.select_related("onboarding")
    serializer_class = OnboardingTaskSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def toggle(self, request, pk=None):
        """Toggle a task done/undone; completing the last task completes the onboarding."""
        task = self.get_object()
        task.is_done = not task.is_done
        task.done_at = timezone.now() if task.is_done else None
        task.save(update_fields=["is_done", "done_at"])
        task.onboarding.refresh_status()
        return Response(OnboardingTaskSerializer(task).data, status=status.HTTP_200_OK)
