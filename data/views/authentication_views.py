import logging
from django.http import Http404
from django.conf import settings
from rest_framework import viewsets, status, serializers
from rest_framework.validators import ValidationError
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample, inline_serializer
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from ..models import User
from ..serializers import UserSerializer
from ..authentication import PrivyAuthentication
from ..data_access_layer import UserDAL, UserCreditsDAL
from .utils import log_error

class PrivyUser:
    """
    A simple class to represent a Privy user for DRF authentication.
    This ensures compatibility with DRF's permission system and throttling.
    """
    def __init__(self, privy_address):
        self.privy_address = privy_address
        # Required attribute for DRF IsAuthenticated permission
        self.is_authenticated = True
        # Required attribute for DRF UserRateThrottle
        self.pk = privy_address
        # Additional attributes for DRF compatibility
        self.id = privy_address
        self.username = privy_address
    
    def __str__(self):
        return self.privy_address

# Custom throttling class that works with PrivyUser
class PrivyUserRateThrottle(UserRateThrottle):
    """
    Custom throttle class that works with PrivyUser objects.
    Uses privy_address as the throttle cache key.
    """
    def get_cache_key(self, request, view):
        if request.user and hasattr(request.user, 'privy_address'):
            ident = request.user.privy_address
            return self.cache_format % {
                'scope': self.scope,
                'ident': ident
            }
        return None

class PrivyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = PrivyAuthentication
    name = 'PrivyAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': 'Privy JWT token for authentication'
        }


@extend_schema_view(
    create=extend_schema(
        summary="Create User",
        description="Create a new user using the authenticated privy address",
        request=inline_serializer(
            name='UserCreateRequest',
            fields={
                'description': serializers.CharField(help_text="User description", required=False)
            }
        ),
        responses={
            201: OpenApiResponse(
                description="User created successfully",
                examples=[
                    OpenApiExample(
                        "User Response",
                        value={
                            "privy_id": "privy_1234...",
                            "description": "User description",
                            "is_active": True,
                            "created_at": "2024-03-21T10:00:00Z",
                            "updated_at": "2024-03-21T10:00:00Z",
                            "credits": {
                                "balance": 2,
                                "created_at": "2024-03-21T10:00:00Z",
                                "updated_at": "2024-03-21T10:00:00Z"
                            }
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Invalid input data"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    ),
    retrieve=extend_schema(
        summary="Get User Details",
        description="Get details of a specific user by privy_id",
        responses={
            200: OpenApiResponse(
                description="User details retrieved successfully",
                examples=[
                    OpenApiExample(
                        "User Response",
                        value={
                            "privy_id": "privy_1234...",
                            "description": "User description",
                            "is_active": True,
                            "created_at": "2024-03-21T10:00:00Z",
                            "updated_at": "2024-03-21T10:00:00Z",
                            "credits": {
                                "balance": 2,
                                "created_at": "2024-03-21T10:00:00Z",
                                "updated_at": "2024-03-21T10:00:00Z"
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    ),
    update=extend_schema(
        summary="Update User",
        description="Update a specific user by privy_id",
        request=inline_serializer(
            name='UserUpdateRequest',
            fields={
                'description': serializers.CharField(help_text="User description", required=False)
            }
        ),
        responses={
            200: OpenApiResponse(description="User updated successfully"),
            400: OpenApiResponse(description="Bad request - Invalid input data"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    ),
    destroy=extend_schema(
        summary="Delete User",
        description="Soft delete a specific user by privy_id",
        responses={
            204: OpenApiResponse(description="User deleted successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    ),
    list=extend_schema(
        summary="List Users",
        description="Get a list of all users or just the current user",
        responses={
            200: OpenApiResponse(description="Users retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
)
class UserViewSet(viewsets.ModelViewSet):
    """ViewSet for managing users."""
    serializer_class = UserSerializer
    authentication_classes = [PrivyAuthentication]
    permission_classes = [IsAuthenticated]
    lookup_field = 'privy_address'
    lookup_url_kwarg = 'privy_id'

    def get_queryset(self):
        """Get all non-deleted users or just the current user."""
        # Check if this is a direct call to /api/user/ endpoint
        if self.action == 'list' and not self.request.query_params:
            # Return only the current user
            return User.objects.filter(privy_address=self.request.user.privy_address, is_deleted=False)
        # Otherwise return all users (for admin purposes or other filtered queries)
        return UserDAL.get_users()

    def get_object(self):
        """Get user by privy address."""
        return UserDAL.get_user_by_privy_address(self.kwargs['privy_id'])

    def perform_create(self, serializer):
        """Create a new user and initialize their credits."""
        try:
            # Get privy_address from the authenticated user
            privy_address = self.request.user.privy_address
            
            # Check if user exists (including soft-deleted ones)
            existing_user = User.all_objects.filter(privy_address=privy_address).first()
            
            if existing_user:
                if existing_user.is_deleted:
                    # Restore the soft-deleted user
                    existing_user.is_deleted = False
                    existing_user.deleted_at = None
                    existing_user.save()
                    
                    # Reset credits to default value
                    credits = UserCreditsDAL.get_user_credits(existing_user)
                    credits.balance = 2  # Default credit value
                    credits.save()
                    
                    logging.info(f"Restored soft-deleted user {privy_address} and reset credits to default")
                    serializer.instance = existing_user
                    return serializer.save()
                else:
                    raise ValidationError("User already exists")
            
            # Create the user with the privy_address from authentication
            user = serializer.save(privy_address=privy_address)
            
            # Create initial credits for the user
            UserCreditsDAL.get_user_credits(user)  # This will create credits with default balance of 2
            
            logging.info(f"Created new user {user.privy_address} with initial credits")
            return user
        except ValidationError as e:
            raise e
        except Exception as e:
            logging.error(f"Error creating user: {str(e)}")
            raise ValidationError("Error creating user")

    def perform_update(self, serializer):
        """Update a user."""
        try:
            serializer.save()
        except Exception as e:
            logging.error(f"Error updating user: {str(e)}")
            raise ValidationError("Error updating user")

    def perform_destroy(self, instance):
        """Soft delete a user."""
        try:
            instance.delete()  # This will call our custom delete method
        except Exception as e:
            logging.error(f"Error deleting user: {str(e)}")
            raise ValidationError("Error deleting user")

    @extend_schema(
        summary="Get User Credits",
        description="Get the credit balance for a specific user",
        responses={
            200: OpenApiResponse(
                description="Credit balance retrieved successfully",
                examples=[
                    OpenApiExample(
                        "Credit Balance",
                        value={
                            "balance": 2,
                            "privy_id": "privy_1234..."
                        }
                    )
                ]
            ),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
    @action(detail=True, methods=['get'])
    def credits(self, request, privy_id=None):
        """Get user credits."""
        try:
            user = UserDAL.get_user_by_privy_address(privy_id)
            credits = UserCreditsDAL.get_user_credits(user)
            return Response({
                'privy_id': user.privy_address,
                'credits': credits.balance
            })
        except Http404:
            return Response({'error': 'User not found'}, status=404)
        except Exception as e:
            logging.error(f"Error getting credits: {str(e)}")
            return Response({'error': str(e)}, status=500)
            
    @extend_schema(
        summary="Add Credits",
        description="Add credits to a user's balance",
        request=inline_serializer(
            name='AddCreditsRequest',
            fields={
                'amount': serializers.IntegerField(help_text="Number of credits to add")
            }
        ),
        responses={
            200: OpenApiResponse(
                description="Credits added successfully",
                examples=[
                    OpenApiExample(
                        "Updated Balance",
                        value={
                            "balance": 4,
                            "privy_id": "privy_1234..."
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Invalid amount"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
    @action(detail=True, methods=['post'])
    def add_credits(self, request, privy_id=None):
        """Add credits to a user's balance. Only accessible by admin."""
        # Check if user has admin privileges
        if request.user.privy_address != settings.ADMIN_PRIVY_ID:
            return Response({"detail": "You do not have permission to perform this action."}, 
                            status=status.HTTP_403_FORBIDDEN)
        try:
            user = self.get_object()
            amount = request.data.get('amount')

            if not amount or not isinstance(amount, int) or amount <= 0:
                return Response(
                    {"detail": "Invalid amount. Must be a positive integer."},
                    status=status.HTTP_400_BAD_REQUEST
                )

            credits = UserCreditsDAL.add_credits(user, amount)
            return Response({
                'balance': credits.balance,
                'privy_id': user.privy_address
            })
        except Exception as e:
            logging.error(f"Error adding credits: {str(e)}")
            return Response(
                {"detail": "Error adding credits"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @extend_schema(
        summary="Deduct Credits",
        description="Deduct credits from a user's balance",
        request=inline_serializer(
            name='DeductCreditsRequest',
            fields={
                'amount': serializers.IntegerField(help_text="Number of credits to deduct")
            }
        ),
        responses={
            200: OpenApiResponse(
                description="Credits deducted successfully",
                examples=[
                    OpenApiExample(
                        "Updated Balance",
                        value={
                            "balance": 1,
                            "privy_id": "privy_1234..."
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Invalid amount or insufficient credits"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
    @action(detail=True, methods=['post'])
    def deduct_credits(self, request, privy_id=None):
        """Deduct credits from a user's balance. Only accessible by admin."""
        # Check if user has admin privileges
        if request.user.privy_address != settings.ADMIN_PRIVY_ID:
            return Response({"detail": "You do not have permission to perform this action."}, 
                            status=status.HTTP_403_FORBIDDEN)
        try:
            user = self.get_object()
            amount = request.data.get('amount')
            
            if not amount or not isinstance(amount, int) or amount <= 0:
                return Response(
                    {"detail": "Invalid amount. Must be a positive integer."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not UserCreditsDAL.has_sufficient_credits(user, amount):
                return Response(
                    {"detail": "Insufficient credits"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            credits = UserCreditsDAL.deduct_credits(user, amount)
            return Response({
                'balance': credits.balance,
                'privy_id': user.privy_address
            })
        except Exception as e:
            logging.error(f"Error deducting credits: {str(e)}")
            return Response(
                {"detail": "Error deducting credits"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @extend_schema(
        summary="Restore Deleted User",
        description="Restore a previously deleted user",
        responses={
            200: OpenApiResponse(
                description="User restored successfully",
                examples=[
                    OpenApiExample(
                        "User Response",
                        value={
                            "privy_id": "privy_1234...",
                            "description": "User description",
                            "is_active": True,
                            "created_at": "2024-03-21T10:00:00Z",
                            "updated_at": "2024-03-21T10:00:00Z",
                            "credits": {
                                "balance": 2,
                                "created_at": "2024-03-21T10:00:00Z",
                                "updated_at": "2024-03-21T10:00:00Z"
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - User not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
    @action(detail=True, methods=['post'])
    def restore(self, request, privy_id=None):
        """Restore a soft-deleted user. Only accessible by admin."""
        # Check if user has admin privileges
        if request.user.privy_address != settings.ADMIN_PRIVY_ID:
            return Response({"detail": "You do not have permission to perform this action."}, 
                            status=status.HTTP_403_FORBIDDEN)
        try:
            logging.info(f"Attempting to restore user: {privy_id}")
            user = UserDAL.restore_user(privy_id)
            logging.info(f"Successfully restored user: {privy_id}")
            
            serializer = self.get_serializer(user)
            return Response(serializer.data)
        except ValueError as e:
            logging.warning(f"Restore error: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Http404:
            logging.warning(f"User not found: {privy_id}")
            return Response(
                {"error": "User not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            error_context = log_error(e, {
                'user_id': privy_id,
                'endpoint': 'restore'
            })
            return Response(
                {"error": "Error restoring user"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            
    @extend_schema(
        summary="Get Current User",
        description="Get details of the currently authenticated user",
        responses={
            200: OpenApiResponse(
                description="Current user details retrieved successfully",
                examples=[
                    OpenApiExample(
                        "User Response",
                        value={
                            "privy_id": "privy_1234...",
                            "description": "User description",
                            "is_active": True,
                            "created_at": "2024-03-21T10:00:00Z",
                            "updated_at": "2024-03-21T10:00:00Z",
                            "credits": {
                                "balance": 2,
                                "created_at": "2024-03-21T10:00:00Z",
                                "updated_at": "2024-03-21T10:00:00Z"
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get the current authenticated user."""
        try:
            user = UserDAL.get_user_by_privy_address(request.user.privy_address)
            serializer = self.get_serializer(user)
            return Response(serializer.data)
        except Exception as e:
            logging.error(f"Error getting current user: {str(e)}")
            return Response(
                {"error": "Error retrieving user information"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="List Deleted Users",
        description="Get a list of all deleted users",
        responses={
            200: UserSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["User"]
    )
    @action(detail=False, methods=['get'])
    def deleted(self, request):
        """Get all deleted users."""
        try:
            logging.info("Getting deleted users")
            users = UserDAL.get_deleted_users()
            logging.info(f"Found {users.count()} deleted users")
            
            serializer = self.get_serializer(users, many=True)
            return Response(serializer.data)
        except Exception as e:
            error_context = log_error(e, {
                'endpoint': 'deleted'
            })
            return Response(
                {"error": "Error retrieving deleted users"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
