from rest_framework import serializers
from .models import Lead
from core.validators import validate_non_negative_decimal


class LeadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lead
        fields = ['id', 'contact', 'source', 'status', 'value', 'owner', 'created_at', 'updated_at']

    def validate(self, attrs):
        value = attrs.get('value')
        if value is not None:
            validate_non_negative_decimal(value, 'value')
        return attrs


