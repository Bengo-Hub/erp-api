from django.contrib import admin
from .models import PipelineStage, Deal


@admin.register(PipelineStage)
class PipelineStageAdmin(admin.ModelAdmin):
    list_display = ('name', 'order', 'is_won', 'is_lost')
    list_editable = ('order', 'is_won', 'is_lost')


@admin.register(Deal)
class DealAdmin(admin.ModelAdmin):
    list_display = ('title', 'contact', 'stage', 'amount', 'owner', 'created_at')
    list_filter = ('stage',)
    search_fields = ('title', 'contact__user__first_name', 'contact__user__last_name')


