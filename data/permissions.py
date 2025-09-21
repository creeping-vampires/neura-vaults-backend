from rest_framework import permissions
from django.conf import settings


class IsDefAIAdmin(permissions.BasePermission):
    """
    Custom permission to only allow the admin user (with ADMIN_PRIVY_ID) to access the view.
    """
    
    def has_permission(self, request, view):
        # Check if the user is authenticated and has the admin privy ID
        return (
            request.user and 
            request.user.is_authenticated and 
            request.user.privy_address == settings.ADMIN_PRIVY_ID
        )
