from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status

from .models import TrainingCourse, TrainingEnrollment, TrainingEvaluation
from .serializers import (
    TrainingCourseSerializer,
    TrainingEnrollmentSerializer,
    TrainingEvaluationSerializer,
)


class TrainingCourseViewSet(viewsets.ModelViewSet):
    queryset = TrainingCourse.objects.all()
    serializer_class = TrainingCourseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description"]
    ordering_fields = ["start_date", "end_date", "created_at"]
    throttle_scope = "user"


class TrainingEnrollmentViewSet(viewsets.ModelViewSet):
    queryset = TrainingEnrollment.objects.all()
    serializer_class = TrainingEnrollmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["employee__user__email", "course__title"]
    ordering_fields = ["enrolled_at"]
    throttle_scope = "user"

    @action(detail=True, methods=["post"], url_path="complete")
    def complete(self, request, pk=None):
        enrollment = self.get_object()
        enrollment.status = "completed"
        enrollment.save(update_fields=["status"])
        return Response(self.get_serializer(enrollment).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        enrollment = self.get_object()
        enrollment.status = "cancelled"
        enrollment.save(update_fields=["status"])
        return Response(self.get_serializer(enrollment).data)


class TrainingEvaluationViewSet(viewsets.ModelViewSet):
    queryset = TrainingEvaluation.objects.all()
    serializer_class = TrainingEvaluationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["created_at"]
    throttle_scope = "user"

