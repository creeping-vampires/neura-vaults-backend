from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from typing import List, Dict, Any
from ..models import User, UserCredits, UserRole
from ..data_access_layer import UserRoleDAL

class UserCreditsSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserCredits
        fields = ['balance', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

class UserSerializer(serializers.ModelSerializer):
    credits = UserCreditsSerializer(read_only=True)
    privy_id = serializers.CharField(source='privy_address', read_only=True)
    roles = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['privy_id', 'description', 'is_active', 'created_at', 'updated_at', 'credits', 'roles']
        read_only_fields = ['created_at', 'updated_at', 'privy_id', 'roles']
    
    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_roles(self, obj: User) -> List[Dict[str, Any]]:
        """Get user roles with a default of 'user' if no roles exist."""
        user_roles = UserRoleDAL.get_user_roles(obj)
        if not user_roles.exists():
            # Return default role if no roles exist
            return [{'role': 'user', 'role_display': 'User'}]
        
        # Return all roles the user has
        return [{'role': role.role, 'role_display': role.get_role_display()} for role in user_roles]