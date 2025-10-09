from django.contrib import admin
from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('contact', 'status', 'value', 'owner', 'created_at')
    list_filter = ('status',)
    search_fields = ('contact__user__first_name', 'contact__user__last_name', 'source')


