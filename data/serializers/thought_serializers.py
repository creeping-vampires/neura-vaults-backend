from rest_framework import serializers
from django.utils import timezone

from ..models import Thought
from ..data_access_layer import ThoughtDAL

class ThoughtSerializer(serializers.ModelSerializer):
    """Serializer for Thought model."""
    agent_name = serializers.CharField(source='agent.name', read_only=True)
    
    class Meta:
        model = Thought
        fields = ['thoughtId', 'agent', 'agent_name', 'createdAt', 'thought', 'agent_role']
        read_only_fields = ['thoughtId', 'createdAt']
