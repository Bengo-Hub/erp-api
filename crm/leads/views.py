from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead
from .serializers import LeadSerializer


class LeadViewSet(viewsets.ModelViewSet):
    queryset = Lead.objects.all()
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['contact__user__first_name', 'contact__user__last_name', 'source']
    ordering_fields = ['created_at', 'value']
    throttle_scope = 'user'

    @action(detail=True, methods=['post'], url_path='advance')
    def advance(self, request, pk=None):
        lead = self.get_object()
        transitions = {
            'new': 'contacted',
            'contacted': 'qualified',
            'qualified': 'won',
        }
        next_status = transitions.get(lead.status)
        if not next_status:
            return Response({'detail': 'No next status.'}, status=status.HTTP_400_BAD_REQUEST)
        lead.status = next_status
        lead.save(update_fields=['status'])
        return Response(self.get_serializer(lead).data)

    @action(detail=True, methods=['post'], url_path='lose')
    def lose(self, request, pk=None):
        lead = self.get_object()
        lead.status = 'lost'
        lead.save(update_fields=['status'])
        return Response(self.get_serializer(lead).data)


