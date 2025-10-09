from rest_framework import serializers
from .models import PipelineStage, Deal


class PipelineStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PipelineStage
        fields = ['id', 'name', 'order', 'is_won', 'is_lost']


class DealSerializer(serializers.ModelSerializer):
    class Meta:
        model = Deal
        fields = ['id', 'title', 'contact', 'lead', 'stage', 'amount', 'close_date', 'owner', 'created_at', 'updated_at']


