import logging
from rest_framework import viewsets
from rest_framework.validators import ValidationError
from rest_framework.permissions import IsAuthenticated
from django.http import Http404

from ..models import User, Withdrawal
from ..serializers import WithdrawalSerializer
from ..authentication import PrivyAuthentication
from .utils import log_error

logger = logging.getLogger(__name__)

class WithdrawalViewSet(viewsets.ModelViewSet):
    """ViewSet for managing withdrawal requests."""
    serializer_class = WithdrawalSerializer
    authentication_classes = [PrivyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get withdrawals for the authenticated user."""
        user = self.request.user
        if not hasattr(user, 'privy_address'):
            return Withdrawal.objects.none()
            
        try:
            db_user = User.objects.get(privy_address=user.privy_address)
            return Withdrawal.objects.filter(user=db_user)
        except User.DoesNotExist:
            return Withdrawal.objects.none()
    
    def get_object(self):
        """Get a single withdrawal, ensuring it belongs to the authenticated user."""
        obj = super().get_object()
        user = self.request.user
        
        if not hasattr(user, 'privy_address'):
            raise Http404
            
        try:
            db_user = User.objects.get(privy_address=user.privy_address)
            if obj.user != db_user:
                raise Http404
        except User.DoesNotExist:
            raise Http404
            
        return obj
    
    def perform_create(self, serializer):
        """Create a new withdrawal request."""
        user = self.request.user
        
        if not hasattr(user, 'privy_address'):
            raise ValidationError({"detail": "Authentication required"})
            
        try:
            db_user = User.objects.get(privy_address=user.privy_address)
            serializer.save(user=db_user)
        except User.DoesNotExist:
            raise ValidationError({"detail": "User not found"})
        except Exception as e:
            error_context = log_error(e, {"action": "create_withdrawal"})
            raise ValidationError({"detail": f"Error creating withdrawal: {str(e)}"})