import logging

from rest_framework.validators import ValidationError
from rest_framework.decorators import api_view, authentication_classes, permission_classes, parser_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.parsers import JSONParser
from django.conf import settings
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample, inline_serializer, OpenApiParameter
from rest_framework import viewsets, status,serializers, mixins
from ..models import CreditRequest, User
from ..serializers import CreditRequestSerializer
from ..authentication import PrivyAuthentication
from ..permissions import IsDefAIAdmin
from ..data_access_layer import CreditRequestDAL, UserCreditsDAL, UserDAL
from .utils import log_error

logger = logging.getLogger(__name__)

@extend_schema_view(
    list=extend_schema(
        summary="List Credit Requests",
        description="Get a list of all credit requests for the authenticated user",
        responses={
            200: CreditRequestSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Credits"]
    ),
    create=extend_schema(
        summary="Create Credit Request",
        description="Create a new credit request",
        responses={
            201: CreditRequestSerializer,
            400: OpenApiResponse(description="Bad request - Invalid input data"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Credits"]
    )
)
class CreditRequestViewSet(viewsets.GenericViewSet, mixins.CreateModelMixin, mixins.ListModelMixin):
    """ViewSet for managing credit requests. Only supports create and list operations."""
    serializer_class = CreditRequestSerializer
    authentication_classes = [PrivyAuthentication]
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Get credit requests for the authenticated user."""
        if not hasattr(self.request, 'user') or not self.request.user:
            return CreditRequest.objects.none()
            
        try:
            user = User.objects.get(privy_address=self.request.user.privy_address)
            return CreditRequestDAL.get_credit_requests_for_user(user)
        except User.DoesNotExist:
            return CreditRequest.objects.none()
    
    def perform_create(self, serializer):
        """Create a new credit request for the authenticated user with validation for unique Twitter handle."""
        try:
            user = User.objects.get(privy_address=self.request.user.privy_address)
            twitter_handle = serializer.validated_data.get('twitter_handle')
            # Always use the default credits_requested value from settings
            
            # Normalize Twitter handle (remove @ if present and convert to lowercase)
            if twitter_handle.startswith('@'):
                twitter_handle = twitter_handle[1:]
            twitter_handle = twitter_handle.lower()
            
            # Check if this Twitter handle has already been used in a request
            existing_twitter_requests = CreditRequest.objects.filter(twitter_handle__iexact=twitter_handle)
            if existing_twitter_requests.exists():
                raise ValidationError({"detail": "This Twitter handle has already been used for a credit request"})
            
            # Check if this Privy ID has already been used in a request
            existing_privy_requests = CreditRequest.objects.filter(privy_id=user.privy_address)
            if existing_privy_requests.exists():
                raise ValidationError({"detail": "You have already submitted a credit request with this account"})
            
            credit_request = CreditRequestDAL.create_credit_request(
                user=user,
                twitter_handle=twitter_handle,
                credits_requested=settings.DEFAULT_USER_CREDITS  # Use value from settings
            )
            
            # Return the created credit request
            return credit_request
        except ValidationError as e:
            # Re-raise validation errors
            raise
        except Exception as e:
            error_context = log_error(e, {'action': 'create_credit_request'})
            raise ValidationError({"detail": f"Failed to create credit request: {str(e)}"})


@extend_schema(
    description="Admin endpoint to view all credit requests with optional status filtering",
    parameters=[
        OpenApiParameter(
            name="status",
            description="Filter credit requests by status",
            required=False,
            type=str,
            enum=["pending", "approved", "rejected", "all"]
        )
    ],
    responses={
        200: OpenApiResponse(description="List of credit requests"),
        400: OpenApiResponse(description="Invalid status parameter"),
        500: OpenApiResponse(description="Server error")
    },
    tags=["Admin"]
)
@api_view(['GET'])
@parser_classes([JSONParser])
@permission_classes([IsDefAIAdmin])
def admin_view_credit_requests(request):
    """
    Admin endpoint to view all credit requests.
    Only accessible by admin users.
    
    Query Parameters:
    - status: Filter by status ('pending', 'approved', 'rejected', or 'all')
    """
    try:
        # Get status filter from query parameters (default to 'pending')
        status_filter = request.query_params.get('status', 'pending')
        
        # Get credit requests based on status filter
        if status_filter == 'all':
            credit_requests = CreditRequest.objects.all().order_by('-created_at')
        else:
            credit_requests = CreditRequest.objects.filter(status=status_filter).order_by('-created_at')
        
        # Serialize the credit requests
        serializer = CreditRequestSerializer(credit_requests, many=True)
        return Response(serializer.data)
    except Exception as e:
        log_error(e, {'action': 'admin_view_credit_requests'})
        return Response({"detail": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    summary="Admin Approve Credit Request",
    description="Admin endpoint to approve a credit request",
    request=inline_serializer(
        name="AdminApproveCreditRequestSerializer",
        fields={
            'credit_request_id': serializers.IntegerField(help_text="ID of the credit request to approve"),
            'credits_granted': serializers.IntegerField(help_text="Number of credits to grant", required=False),
            'notes': serializers.CharField(help_text="Optional notes about the approval", required=False)
        }
    ),
    responses={
        200: OpenApiResponse(
            description="Credit request approved successfully",
            examples=[
                OpenApiExample(
                    "Approve Response",
                    value={
                        "credit_request": {
                            "id": 1,
                            "privy_id": "privy_1234...",
                            "twitter_handle": "@user1",
                            "status": "approved",
                            "credits_requested": 10,
                            "credits_granted": 10,
                            "created_at": "2024-03-21T10:00:00Z",
                            "updated_at": "2024-03-21T10:00:00Z",
                            "processed_at": "2024-03-21T11:00:00Z",
                            "notes": "Approved by admin"
                        },
                        "message": "Credit request approved successfully"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Bad request - Invalid input data"),
        401: OpenApiResponse(description="Unauthorized - Authentication required"),
        403: OpenApiResponse(description="Forbidden - Admin access required"),
        404: OpenApiResponse(description="Not found - Credit request not found"),
        500: OpenApiResponse(description="Internal server error")
    },
    tags=["Admin"]
)
@api_view(['POST'])
@authentication_classes([PrivyAuthentication])
@permission_classes([IsAuthenticated, IsDefAIAdmin])
def admin_approve_credit_request(request):
    """
    Admin endpoint to approve a credit request.
    Only accessible by admin users.
    """
    try:
        # Get credit request ID from request
        credit_request_id = request.data.get('credit_request_id')
        credits_granted = request.data.get('credits_granted')
        notes = request.data.get('notes', '')
        
        if not credit_request_id:
            return Response({"detail": "No credit request ID provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        logger.info(f"Admin user {request.user.privy_address} attempting to approve credit request: {credit_request_id}")
        
        try:
            # Get credit request
            credit_request = CreditRequest.objects.get(id=credit_request_id)
            
            # Check if credit request is already processed
            if credit_request.status != CreditRequest.StatusChoices.PENDING:
                return Response({
                    "detail": f"Credit request is already {credit_request.status}"
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # If credits_granted not provided, use the requested amount
            if credits_granted is None:
                credits_granted = credit_request.credits_requested
            
            # Approve the credit request
            approved_request = CreditRequestDAL.approve_credit_request(
                credit_request=credit_request,
                credits_granted=credits_granted,
                notes=notes
            )
            
            # Serialize the approved request
            serializer = CreditRequestSerializer(approved_request)
            
            return Response({
                "credit_request": serializer.data,
                "message": "Credit request approved successfully"
            }, status=status.HTTP_200_OK)
            
        except CreditRequest.DoesNotExist:
            return Response({"detail": "Credit request not found"}, status=status.HTTP_404_NOT_FOUND)
        
    except Exception as e:
        logger.error(f"Error in admin_approve_credit_request: {str(e)}")
        return Response({"detail": f"An error occurred: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)