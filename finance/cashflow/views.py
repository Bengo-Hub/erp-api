from datetime import datetime
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import models
from finance.accounts.models import Transaction
from django.db import models


class CashFlowView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        start = request.query_params.get('start_date')
        end = request.query_params.get('end_date')
        try:
            start_date = datetime.fromisoformat(start).date() if start else (timezone.now().date().replace(day=1))
        except ValueError:
            start_date = timezone.now().date().replace(day=1)
        try:
            end_date = datetime.fromisoformat(end).date() if end else timezone.now().date()
        except ValueError:
            end_date = timezone.now().date()

        qs = Transaction.objects.filter(transaction_date__date__gte=start_date, transaction_date__date__lte=end_date)

        inflow_types = ['income', 'refund']
        outflow_types = ['expense', 'payment', 'transfer']

        total_inflows = qs.filter(transaction_type__in=inflow_types).aggregate(total_amount=models.Sum('amount'))['total_amount'] or 0
        total_outflows = qs.filter(transaction_type__in=outflow_types).aggregate(total_amount=models.Sum('amount'))['total_amount'] or 0
        net_cash = total_inflows - total_outflows

        by_type = {}
        for t in inflow_types + outflow_types:
            by_type[t] = qs.filter(transaction_type=t).aggregate(total_amount=models.Sum('amount'))['total_amount'] or 0

        return Response({
            'start_date': start_date,
            'end_date': end_date,
            'total_inflows': total_inflows,
            'total_outflows': total_outflows,
            'net_cash': net_cash,
            'breakdown': by_type,
        })
