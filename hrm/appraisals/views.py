from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import (
    AppraisalCycle, AppraisalTemplate, AppraisalQuestion,
    Appraisal, AppraisalResponse, Goal, GoalProgress
)
from .serializers import (
    AppraisalCycleSerializer, AppraisalTemplateSerializer,
    AppraisalQuestionSerializer, AppraisalSerializer,
    AppraisalResponseSerializer, GoalSerializer,
    GoalProgressSerializer
)

class AppraisalCycleViewSet(viewsets.ModelViewSet):
    queryset = AppraisalCycle.objects.all()
    serializer_class = AppraisalCycleSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'locations']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'start_date', 'end_date', 'due_date', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        cycle = self.get_object()
        cycle.status = 'activated'
        cycle.save()
        return Response({'status': 'cycle activated'})

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        cycle = self.get_object()
        cycle.status = 'closed'
        cycle.save()
        return Response({'status': 'cycle closed'})

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        cycle = self.get_object()
        cycle.status = 'reopened'
        cycle.save()
        return Response({'status': 'cycle reopened'})

class AppraisalTemplateViewSet(viewsets.ModelViewSet):
    queryset = AppraisalTemplate.objects.all()
    serializer_class = AppraisalTemplateSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class AppraisalQuestionViewSet(viewsets.ModelViewSet):
    queryset = AppraisalQuestion.objects.all()
    serializer_class = AppraisalQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['template', 'question_type', 'is_required']
    ordering_fields = ['order', 'created_at']

class AppraisalViewSet(viewsets.ModelViewSet):
    queryset = Appraisal.objects.all()
    serializer_class = AppraisalSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['cycle', 'employee', 'evaluator', 'template', 'status']
    search_fields = ['employee__user__first_name', 'employee__user__last_name']
    ordering_fields = ['created_at', 'updated_at', 'overall_rating']

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        appraisal = self.get_object()
        appraisal.status = 'completed'
        appraisal.save()
        return Response({'status': 'appraisal submitted'})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        appraisal = self.get_object()
        appraisal.status = 'approved'
        appraisal.save()
        return Response({'status': 'appraisal approved'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        appraisal = self.get_object()
        appraisal.status = 'rejected'
        appraisal.save()
        return Response({'status': 'appraisal rejected'})

class AppraisalResponseViewSet(viewsets.ModelViewSet):
    queryset = AppraisalResponse.objects.all()
    serializer_class = AppraisalResponseSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['appraisal', 'question']
    ordering_fields = ['created_at']

class GoalViewSet(viewsets.ModelViewSet):
    queryset = Goal.objects.all()
    serializer_class = GoalSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['employee', 'status', 'is_template']
    search_fields = ['title', 'description']
    ordering_fields = ['start_date', 'end_date', 'created_at']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def update_progress(self, request, pk=None):
        goal = self.get_object()
        progress = request.data.get('progress')
        comments = request.data.get('comments', '')

        if progress is None:
            return Response(
                {'error': 'Progress is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        GoalProgress.objects.create(
            goal=goal,
            progress=progress,
            comments=comments,
            updated_by=request.user
        )

        goal.progress = progress
        if progress == 100:
            goal.status = 'completed'
        elif progress > 0:
            goal.status = 'in_progress'
        goal.save()

        return Response({'status': 'progress updated'})

class GoalProgressViewSet(viewsets.ModelViewSet):
    queryset = GoalProgress.objects.all()
    serializer_class = GoalProgressSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['goal']
    ordering_fields = ['created_at']

    def perform_create(self, serializer):
        serializer.save(updated_by=self.request.user) 