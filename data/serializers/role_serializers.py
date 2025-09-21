import random
import string
from rest_framework import serializers
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

from ..models import UserRole, InviteCode
from ..data_access_layer import UserDAL, InviteCodeDAL

class UserRoleSerializer(serializers.ModelSerializer):
    """Serializer for UserRole model."""
    user_privy_id = serializers.CharField(source='user.privy_address', read_only=True)
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    
    class Meta:
        model = UserRole
        fields = ['id', 'user', 'user_privy_id', 'role', 'role_display', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']
        extra_kwargs = {
            'user': {'write_only': True}
        }


class InviteCodeSerializer(serializers.ModelSerializer):
    """Serializer for InviteCode model."""
    created_by_privy_id = serializers.CharField(source='created_by.privy_address', read_only=True)
    redeemed_by_privy_id = serializers.CharField(source='redeemed_by.privy_address', read_only=True, allow_null=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = InviteCode
        fields = [
            'id', 'code', 'created_by', 'created_by_privy_id', 'creator_role',
            'redeemable_credits', 'assign_kol_role', 'status', 'status_display',
            'redeemed_by', 'redeemed_by_privy_id', 'redeemed_at', 'created_at', 'expires_at'
        ]
        read_only_fields = ['code', 'created_by', 'creator_role', 'status', 'redeemed_by', 'redeemed_at', 'created_at', 'redeemable_credits']
        extra_kwargs = {
            'assign_kol_role': {'required': False},
            'expires_at': {'required': False}
        }
    
    def validate(self, data):
        """Validate the invite code data."""
        request = self.context.get('request')
        user = request.user
        
        # Get user roles
        user_obj = UserDAL.get_user_by_privy_address(user.privy_address)
        user_roles = UserRole.objects.filter(user=user_obj).values_list('role', flat=True)
        
        # Set default expiration date based on settings
        if 'expires_at' not in data or data['expires_at'] is None:
            expiry_hours = getattr(settings, 'INVITE_CODE_EXPIRY_HOURS', 24)  # Default to 24 hours if not set
            data['expires_at'] = timezone.localtime(timezone.now()) + timedelta(hours=expiry_hours)
        
        # Handle KOL-generated invite codes
        if 'kol' in user_roles:
            # Check if KOL has reached their daily limit
            daily_count = InviteCodeDAL.count_daily_invite_codes(user_obj)
            daily_limit = settings.KOL_DAILY_INVITE_LIMIT
            
            if daily_count >= daily_limit:
                raise serializers.ValidationError(f"You have reached your daily limit of {daily_limit} invite codes.")
            
            # KOL can only create codes with redeemable credits from env
            kol_credits = settings.KOL_INVITE_CREDITS
            data['redeemable_credits'] = kol_credits
            data['assign_kol_role'] = False
            data['creator_role'] = UserRole.RoleChoices.KOL
        
        # Handle ADMIN-generated invite codes
        elif 'admin' in user_roles:
            # Admin can create codes with credits from environment variables
            admin_credits = settings.ADMIN_INVITE_CREDITS
            data['redeemable_credits'] = admin_credits
            
            if 'assign_kol_role' not in data:
                data['assign_kol_role'] = True
                
            data['creator_role'] = UserRole.RoleChoices.ADMIN
        else:
            # Regular users cannot create invite codes
            raise serializers.ValidationError("You don't have permission to create invite codes.")
        
        return data
    
    def create(self, validated_data):
        """Create a new invite code."""
        request = self.context.get('request')
        user = UserDAL.get_user_by_privy_address(request.user.privy_address)
        
        # Generate a random invite code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        # Create the invite code
        invite_code = InviteCode.objects.create(
            code=code,
            created_by=user,
            **validated_data
        )
        
        return invite_code


class InviteCodeRedeemSerializer(serializers.Serializer):
    """Serializer for redeeming invite codes."""
    code = serializers.CharField(max_length=20)
    
    def validate_code(self, value):
        """Validate the invite code."""
        try:
            invite_code = InviteCode.objects.get(code=value)
            if not invite_code.is_valid():
                raise serializers.ValidationError("This invite code is no longer valid.")
        except InviteCode.DoesNotExist:
            raise serializers.ValidationError("Invalid invite code.")
        
        return value
    
    def redeem(self, user):
        """Redeem the invite code."""
        code = self.validated_data['code']
        try:
            invite_code = InviteCode.objects.get(code=code)
            success = invite_code.redeem(user)
            if success:
                return invite_code
            else:
                raise serializers.ValidationError("Failed to redeem invite code.")
        except InviteCode.DoesNotExist:
            raise serializers.ValidationError("Invalid invite code.")
