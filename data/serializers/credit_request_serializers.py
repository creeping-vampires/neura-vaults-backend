import logging
from rest_framework import serializers
from django.utils import timezone

from ..models import CreditRequest
from ..data_access_layer import CreditRequestDAL

logger = logging.getLogger(__name__)

class CreditRequestSerializer(serializers.ModelSerializer):
    """Serializer for CreditRequest model."""
    
    class Meta:
        model = CreditRequest
        fields = [
            'id', 'privy_id', 'twitter_handle', 'status', 'credits_requested',
            'credits_granted', 'created_at', 'updated_at', 'processed_at', 'notes'
        ]
        read_only_fields = [
            'id', 'privy_id', 'status', 'credits_requested', 'credits_granted',
            'created_at', 'updated_at', 'processed_at', 'notes'
        ]
    
    def validate_twitter_handle(self, value):
        """Validate the Twitter handle."""
        # Remove @ symbol if present
        if value.startswith('@'):
            value = value[1:]
        
        # Check if the Twitter handle is valid
        if not value:
            raise serializers.ValidationError("Twitter handle cannot be empty")
        
        # Check if a credit request with this Twitter handle already exists
        if CreditRequest.objects.filter(twitter_handle=value).exists():
            raise serializers.ValidationError("A credit request with this Twitter handle already exists")
        
        return value
    
    def create(self, validated_data):
        """Create a new credit request."""
        # Set default values
        validated_data['status'] = CreditRequest.StatusChoices.PENDING
        validated_data['credits_granted'] = 0
        
        # Create the credit request
        credit_request = CreditRequestDAL.create_credit_request(
            privy_id=validated_data.get('privy_id'),
            twitter_handle=validated_data.get('twitter_handle'),
            credits_requested=validated_data.get('credits_requested')
        )
        
        return credit_request
