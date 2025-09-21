import logging
from django.http import Http404
from django.conf import settings
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample

from ..models import UserRole, InviteCode
from ..serializers.role_serializers import UserRoleSerializer, InviteCodeSerializer, InviteCodeRedeemSerializer
from ..authentication import PrivyAuthentication
from ..data_access_layer import UserDAL, InviteCodeDAL

logger = logging.getLogger(__name__)


class IsAdminUser(permissions.BasePermission):
    """
    Permission to only allow admin users to access the view.
    """
    def has_permission(self, request, view):
        user = UserDAL.get_user_by_privy_address(request.user.privy_address)
        return UserRole.objects.filter(user=user, role=UserRole.RoleChoices.ADMIN).exists()


class IsAdminOrKOLUser(permissions.BasePermission):
    """
    Permission to only allow admin or KOL users to access the view.
    """
    def has_permission(self, request, view):
        user = UserDAL.get_user_by_privy_address(request.user.privy_address)
        return UserRole.objects.filter(
            user=user, 
            role__in=[UserRole.RoleChoices.ADMIN, UserRole.RoleChoices.KOL]
        ).exists()


@extend_schema_view(
    list=extend_schema(
        summary="List User Roles",
        description="Get a list of all user roles (Admin only)",
        responses={
            200: OpenApiResponse(description="User roles retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin access required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Roles"]
    ),
    retrieve=extend_schema(
        summary="Get User Role",
        description="Get details of a specific user role (Admin only)",
        responses={
            200: OpenApiResponse(description="User role retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin access required"),
            404: OpenApiResponse(description="Not found - User role not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Roles"]
    ),
    create=extend_schema(
        summary="Create User Role",
        description="Create a new user role (Admin only)",
        responses={
            201: OpenApiResponse(description="User role created successfully"),
            400: OpenApiResponse(description="Bad request - Invalid input data"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin access required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Roles"]
    ),
    update=extend_schema(
        summary="Update User Role",
        description="Update a specific user role (Admin only)",
        responses={
            200: OpenApiResponse(description="User role updated successfully"),
            400: OpenApiResponse(description="Bad request - Invalid input data"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin access required"),
            404: OpenApiResponse(description="Not found - User role not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Roles"]
    ),
    destroy=extend_schema(
        summary="Delete User Role",
        description="Delete a specific user role (Admin only)",
        responses={
            204: OpenApiResponse(description="User role deleted successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin access required"),
            404: OpenApiResponse(description="Not found - User role not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Roles"]
    )
)
class UserRoleViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user roles."""
    serializer_class = UserRoleSerializer
    authentication_classes = [PrivyAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminUser]
    queryset = UserRole.objects.all()

    @extend_schema(
        summary="Get My Roles",
        description="Get the roles of the current authenticated user",
        responses={
            200: OpenApiResponse(description="User roles retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Roles"]
    )
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAuthenticated])
    def my_roles(self, request):
        """Get the roles of the current authenticated user."""
        try:
            user = UserDAL.get_user_by_privy_address(request.user.privy_address)
            roles = UserRole.objects.filter(user=user)
            serializer = self.get_serializer(roles, many=True)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error getting user roles: {str(e)}")
            return Response(
                {"detail": "Error getting user roles"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema_view(
    list=extend_schema(
        summary="List Invite Codes",
        description="Get a list of invite codes created by the current user (Admin/KOL only)",
        responses={
            200: OpenApiResponse(description="Invite codes retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin/KOL access required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Invite Codes"]
    ),
    retrieve=extend_schema(
        summary="Get Invite Code",
        description="Get details of a specific invite code (Admin/KOL only)",
        responses={
            200: OpenApiResponse(description="Invite code retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin/KOL access required"),
            404: OpenApiResponse(description="Not found - Invite code not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Invite Codes"]
    ),
    create=extend_schema(
        summary="Create Invite Code",
        description="Create a new invite code (Admin/KOL only)",
        responses={
            201: OpenApiResponse(description="Invite code created successfully"),
            400: OpenApiResponse(description="Bad request - Invalid input data"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Admin/KOL access required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Invite Codes"]
    )
)
class InviteCodeViewSet(viewsets.ModelViewSet):
    """ViewSet for managing invite codes."""
    serializer_class = InviteCodeSerializer
    authentication_classes = [PrivyAuthentication]
    permission_classes = [permissions.IsAuthenticated, IsAdminOrKOLUser]
    http_method_names = ['get', 'post', 'head', 'options']  # No PUT, PATCH, DELETE

    def get_queryset(self):
        """Get invite codes created by the current user."""
        user = UserDAL.get_user_by_privy_address(self.request.user.privy_address)
        # Check if user is admin
        is_admin = UserRole.objects.filter(user=user, role=UserRole.RoleChoices.ADMIN).exists()
        if is_admin:
            # Admins can see all invite codes
            return InviteCode.objects.all().order_by('-created_at')
        else:
            # KOLs can only see their own invite codes
            return InviteCode.objects.filter(created_by=user).order_by('-created_at')

    @extend_schema(
        summary="Get Daily Invite Code Limit Info",
        description="Get information about the daily invite code limit for KOL users",
        responses={
            200: OpenApiResponse(description="Daily invite code limit information"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - Not a KOL user"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Invite Codes"]
    )
    @action(detail=False, methods=['get'])
    def daily_limit(self, request):
        """Get information about the daily invite code limit."""
        try:
            user = UserDAL.get_user_by_privy_address(request.user.privy_address)
            
            # Check if user is a KOL
            is_kol = UserRole.objects.filter(user=user, role=UserRole.RoleChoices.KOL).exists()
            if not is_kol:
                return Response(
                    {"detail": "Only KOL users have daily invite code limits."},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            daily_limit = settings.KOL_DAILY_INVITE_LIMIT
            daily_count = InviteCodeDAL.count_daily_invite_codes(user)
            remaining = max(0, daily_limit - daily_count)
            
            response_data = {
                'daily_limit': daily_limit,
                'used_today': daily_count,
                'remaining_today': remaining,
                'credits_per_code': settings.KOL_INVITE_CREDITS
            }
            
            return Response(response_data)
        except Exception as e:
            logger.error(f"Error getting daily invite code limit: {str(e)}")
            return Response(
                {"detail": "Error getting daily invite code limit"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Redeem Invite Code",
        description="Redeem an invite code to get credits and possibly KOL role",
        request=InviteCodeRedeemSerializer,
        responses={
            200: OpenApiResponse(description="Invite code redeemed successfully"),
            400: OpenApiResponse(description="Bad request - Invalid or expired code"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Invite Codes"]
    )
    @action(detail=False, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def redeem(self, request):
        """Redeem an invite code."""
        try:
            serializer = InviteCodeRedeemSerializer(data=request.data)
            if serializer.is_valid():
                user = UserDAL.get_user_by_privy_address(request.user.privy_address)
                invite_code = serializer.redeem(user)
                
                response_data = {
                    'success': True,
                    'message': f"Successfully redeemed invite code for {invite_code.redeemable_credits} credits",
                    'credits_added': invite_code.redeemable_credits,
                    'kol_role_assigned': invite_code.assign_kol_role
                }
                
                return Response(response_data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error redeeming invite code: {str(e)}")
            return Response(
                {"detail": "Error redeeming invite code"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
