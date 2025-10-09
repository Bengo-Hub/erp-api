from django.contrib import admin
from .models import Contact,CustomerGroup,ContactAccount
from business.models import Bussiness,Branch
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model

User=get_user_model()

@admin.register(CustomerGroup)
class CustomerGroupAdmin(admin.ModelAdmin):
    list_per_page = 10

class ContactAccountInline(admin.StackedInline):
    model=ContactAccount
    extra=0

@admin.register(ContactAccount)
class ContactAccountAdmin(admin.ModelAdmin):
    list_per_page = 10

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_per_page = 10
    inlines=[ContactAccountInline]
    list_display=['designation','user','business_name','business_address','contact_type','customer_group','account_type','tax_number','alternative_contact','phone','credit_limit','is_deleted']
    list_filter=['designation','user','business_name','business_address','contact_type','customer_group','account_type','tax_number','alternative_contact','phone','credit_limit']
    search_fields=['designation','user','business_name','business_address','contact_type','customer_group','account_type','tax_number','alternative_contact','phone','credit_limit']
    list_editable=['designation','business_name','business_address','contact_type','customer_group','account_type','tax_number','alternative_contact','phone','credit_limit','is_deleted']
    list_display_links=['user']


    def get_queryset(self, request):
        qs = super().get_queryset(request)
        #print(qs)
        if request.user.is_superuser:
            return qs
        else:
            # Get the business branches where the user is either the owner or an employee
            owned_branches = Branch.objects.filter(business__owner=request.user)
            employee_branches = Branch.objects.filter(business__employees__user=request.user)
            # Combine the two sets of branches using OR operator
            branches = owned_branches | employee_branches
            # Filter contacts based on the obtained branches
            qs = qs.filter(branch__in=branches)
        return qs

