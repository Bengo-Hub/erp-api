from django.contrib import admin

from .models import *
from business.models import Branch
from django.contrib.auth import get_user_model
from django.db.models import Q

User=get_user_model()

class PurchaseItemsInline(admin.TabularInline):
    model = PurchaseItems
    extra=0

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ('purchase_id','supplier', 'sub_total', 'grand_total', 'balance_due','balance_overdue','purchase_status','payment_status', 'paymethod','added_by', 'date_added', 'date_updated')
    list_filter = ('purchase_status', 'paymethod',  'added_by')
    search_fields = ('purchase_id', 'purchase_status', 'payment_status','paymethod',  'added_by__username')
    list_editable=['sub_total','supplier','grand_total', 'purchase_status','payment_status', 'paymethod',  'added_by',]
    list_display_links=['purchase_id']
    inlines = [PurchaseItemsInline]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['added_by'].queryset = User.objects.filter(Q(is_staff=True)|Q(groups__name__in=['staff','manager','cashier']))
        form.base_fields['added_by'].initial = request.user
        form.base_fields['supplier'].queryset = Contact.objects.filter(contact_type__icontains='Suppliers')
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        #print(qs)
        if request.user.is_superuser:
            return qs
        else:
            # Get the branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter purchases based on the obtained branches
            qs = qs.filter(branch__in=branches)
        return qs

class PurchaseReturnedItemInline(admin.TabularInline):
    model = PurchaseReturnedItem
    extra = 0

@admin.register(PurchaseReturn)
class PurchaseReturnAdmin(admin.ModelAdmin):
    list_display = ('date_returned','original_purchase', 'added_by', 'return_amount', 'payment_status')
    list_filter = ('payment_status',)
    search_fields = ('original_purchase__purchase_id', 'reason')
    inlines = [PurchaseReturnedItemInline]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['added_by'].queryset = User.objects.filter(Q(is_staff=True)|Q(role__name__in=['staff','manager','cashier']))
        form.base_fields['added_by'].initial = request.user
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        #print(qs)
        if request.user.is_superuser:
            return qs
        else:
            # Get the branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter returns based on the obtained branches
            qs = qs.filter(original_purchase__branch__in=branches)
        return qs