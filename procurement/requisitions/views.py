from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import ProcurementRequest
from .serializers import ProcurementRequestSerializer

class ProcurementRequestViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows procurement requests to be viewed or edited.
    """
    serializer_class = ProcurementRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = ProcurementRequest.objects.all()
        
        # Filter by query parameters
        requester = self.request.query_params.get('requester', None)
        status = self.request.query_params.get('status', None)
        request_type = self.request.query_params.get('request_type', None)
        
        if requester:
            queryset = queryset.filter(requester=requester)
        if status:
            queryset = queryset.filter(status=status)
        if request_type:
            queryset = queryset.filter(request_type=request_type)
            
        return queryset

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        print(serializer.validated_data)
        
        try:
            self.perform_update(serializer)
        except Exception as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied, force refresh
            instance._prefetched_objects_cache = {}
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        procurement_request = self.get_object()
        # Replace request_approvals logic with centralized Approval model
        procurement_request.approvals.create(
            approver=request.user,
            status='approved',
            notes=request.data.get('notes', 'Approved by ' + request.user.username)
        )
        procurement_request.status = 'approved'
        procurement_request.save()
        return Response({'status': 'approved'})
    
    @action(detail=True, methods=['post']) #axios.post(`${BASE_URL}requisitions/requisitions/${id}/publish/`
    def publish(self, request, pk=None):
        procurement_request = self.get_object()
        procurement_request.request_approvals.create(approver=request.user, status='pending', notes=request.data.get('notes','Published by '+request.user.username))
        procurement_request.status = 'submitted'
        procurement_request.save()
        return Response({'status': 'published'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        procurement_request = self.get_object()
        #create rejection reason
        procurement_request.request_approvals.create(approver=request.user, status='rejected', notes=request.data.get('notes','Rejected by '+request.user.username))
        procurement_request.status = 'rejected'
        procurement_request.save()
        return Response({'status': 'rejected'})

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """
        Process approved requests based on their type
        """
        procurement_request = self.get_object()
        
        if procurement_request.status != 'approved':
            return Response(
                {'error': 'Only approved requests can be processed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add processing logic here based on request_type
        procurement_request.status = 'processing'
        procurement_request.save()
        return Response({'status': 'processing'})

class UserRequestViewSet(viewsets.ModelViewSet):
    """
    API endpoint that shows requests for the current user only
    """
    serializer_class = ProcurementRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProcurementRequest.objects.filter(requester=self.request.user)

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)
