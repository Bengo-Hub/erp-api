"""
Filters for invoicing module
"""
import django_filters
from django.db.models import Q
from .models import Invoice, CreditNote, DebitNote, DeliveryNote, ProformaInvoice


class CommaSeparatedCharFilter(django_filters.CharFilter):
    """
    Custom filter that supports comma-separated values.
    If a single value is provided, it filters exact match.
    If comma-separated values are provided (e.g., 'sent,paid'), it filters using __in.
    """
    def filter(self, qs, value):
        if not value:
            return qs

        # Check if value contains commas (comma-separated list)
        if ',' in value:
            values = [v.strip() for v in value.split(',') if v.strip()]
            if values:
                return qs.filter(**{f'{self.field_name}__in': values})
            return qs

        # Single value - use default filtering
        return super().filter(qs, value)


class InvoiceFilter(django_filters.FilterSet):
    """Filter for Invoice model"""

    # Status filter - supports comma-separated values like 'sent,paid'
    status = CommaSeparatedCharFilter(field_name='status')

    # Customer filter
    customer = django_filters.NumberFilter(field_name='customer')

    # Date filters
    invoice_date = django_filters.DateFilter(field_name='invoice_date')
    invoice_date_after = django_filters.DateFilter(field_name='invoice_date', lookup_expr='gte')
    invoice_date_before = django_filters.DateFilter(field_name='invoice_date', lookup_expr='lte')
    due_date = django_filters.DateFilter(field_name='due_date')
    due_date_after = django_filters.DateFilter(field_name='due_date', lookup_expr='gte')
    due_date_before = django_filters.DateFilter(field_name='due_date', lookup_expr='lte')

    # Payment status filter - also supports comma-separated
    payment_status = CommaSeparatedCharFilter(field_name='payment_status')

    # Amount filters
    total_min = django_filters.NumberFilter(field_name='total', lookup_expr='gte')
    total_max = django_filters.NumberFilter(field_name='total', lookup_expr='lte')

    # Search filter
    search = django_filters.CharFilter(method='filter_search')

    class Meta:
        model = Invoice
        fields = ['status', 'customer', 'invoice_date', 'due_date', 'payment_status']

    def filter_search(self, queryset, name, value):
        """Search across invoice number and customer details"""
        return queryset.filter(
            Q(invoice_number__icontains=value) |
            Q(customer__user__first_name__icontains=value) |
            Q(customer__user__last_name__icontains=value) |
            Q(customer__business_name__icontains=value)
        )


class CreditNoteFilter(django_filters.FilterSet):
    """Filter for CreditNote model"""

    status = CommaSeparatedCharFilter(field_name='status')
    customer = django_filters.NumberFilter(field_name='customer')
    source_invoice = django_filters.NumberFilter(field_name='source_invoice')
    credit_note_date = django_filters.DateFilter(field_name='credit_note_date')
    credit_note_date_after = django_filters.DateFilter(field_name='credit_note_date', lookup_expr='gte')
    credit_note_date_before = django_filters.DateFilter(field_name='credit_note_date', lookup_expr='lte')

    class Meta:
        model = CreditNote
        fields = ['status', 'customer', 'source_invoice', 'credit_note_date']


class DebitNoteFilter(django_filters.FilterSet):
    """Filter for DebitNote model"""

    status = CommaSeparatedCharFilter(field_name='status')
    customer = django_filters.NumberFilter(field_name='customer')
    source_invoice = django_filters.NumberFilter(field_name='source_invoice')
    debit_note_date = django_filters.DateFilter(field_name='debit_note_date')
    debit_note_date_after = django_filters.DateFilter(field_name='debit_note_date', lookup_expr='gte')
    debit_note_date_before = django_filters.DateFilter(field_name='debit_note_date', lookup_expr='lte')

    class Meta:
        model = DebitNote
        fields = ['status', 'customer', 'source_invoice', 'debit_note_date']


class DeliveryNoteFilter(django_filters.FilterSet):
    """Filter for DeliveryNote model"""

    status = CommaSeparatedCharFilter(field_name='status')
    customer = django_filters.NumberFilter(field_name='customer')
    supplier = django_filters.NumberFilter(field_name='supplier')
    source_invoice = django_filters.NumberFilter(field_name='source_invoice')
    source_purchase_order = django_filters.NumberFilter(field_name='source_purchase_order')
    delivery_date = django_filters.DateFilter(field_name='delivery_date')
    delivery_date_after = django_filters.DateFilter(field_name='delivery_date', lookup_expr='gte')
    delivery_date_before = django_filters.DateFilter(field_name='delivery_date', lookup_expr='lte')

    class Meta:
        model = DeliveryNote
        fields = ['status', 'customer', 'supplier', 'source_invoice', 'source_purchase_order', 'delivery_date']


class ProformaInvoiceFilter(django_filters.FilterSet):
    """Filter for ProformaInvoice model"""

    status = CommaSeparatedCharFilter(field_name='status')
    customer = django_filters.NumberFilter(field_name='customer')
    source_quotation = django_filters.NumberFilter(field_name='source_quotation')
    proforma_date = django_filters.DateFilter(field_name='proforma_date')
    proforma_date_after = django_filters.DateFilter(field_name='proforma_date', lookup_expr='gte')
    proforma_date_before = django_filters.DateFilter(field_name='proforma_date', lookup_expr='lte')
    valid_until = django_filters.DateFilter(field_name='valid_until')
    valid_until_after = django_filters.DateFilter(field_name='valid_until', lookup_expr='gte')
    valid_until_before = django_filters.DateFilter(field_name='valid_until', lookup_expr='lte')

    class Meta:
        model = ProformaInvoice
        fields = ['status', 'customer', 'source_quotation', 'proforma_date', 'valid_until']
