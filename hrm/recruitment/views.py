from rest_framework import viewsets, permissions, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from .models import JobPosting, Candidate, Application
from .serializers import JobPostingSerializer, CandidateSerializer, ApplicationSerializer


class JobPostingViewSet(viewsets.ModelViewSet):
    queryset = JobPosting.objects.all()
    serializer_class = JobPostingSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["title", "description", "department", "location"]
    ordering_fields = ["posted_at", "title"]
    throttle_scope = "user"

    @action(detail=True, methods=["post"], url_path="open")
    def open_posting(self, request, pk=None):
        posting = self.get_object()
        posting.status = "open"
        posting.posted_at = timezone.now()
        posting.save(update_fields=["status", "posted_at"])
        return Response(self.get_serializer(posting).data)

    @action(detail=True, methods=["post"], url_path="close")
    def close_posting(self, request, pk=None):
        posting = self.get_object()
        posting.status = "closed"
        posting.closed_at = timezone.now()
        posting.save(update_fields=["status", "closed_at"])
        return Response(self.get_serializer(posting).data)


class CandidateViewSet(viewsets.ModelViewSet):
    queryset = Candidate.objects.all()
    serializer_class = CandidateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["full_name", "email", "phone"]
    ordering_fields = ["created_at"]
    throttle_scope = "user"


class ApplicationViewSet(viewsets.ModelViewSet):
    queryset = Application.objects.all()
    serializer_class = ApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["candidate__full_name", "candidate__email", "notes"]
    ordering_fields = ["applied_at"]
    throttle_scope = "user"

    @action(detail=True, methods=["post"], url_path="advance")
    def advance(self, request, pk=None):
        app = self.get_object()
        transitions = {
            "applied": "screening",
            "screening": "interview",
            "interview": "offered",
            "offered": "hired",
        }
        next_status = transitions.get(app.status)
        if not next_status:
            return Response({"detail": "No next status."}, status=status.HTTP_400_BAD_REQUEST)
        app.status = next_status
        app.save(update_fields=["status"])
        return Response(self.get_serializer(app).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        app = self.get_object()
        app.status = "rejected"
        app.save(update_fields=["status"])
        return Response(self.get_serializer(app).data)

