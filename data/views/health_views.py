from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

@extend_schema(
    summary="Health Check",
    description="Simple health check endpoint to verify API is running",
    responses={
        200: OpenApiResponse(
            description="API is healthy",
            examples=[
                OpenApiExample(
                    "Health Response",
                    value={
                        "status": "healthy",
                        "timestamp": "2024-05-28T07:35:20Z"
                    }
                )
            ]
        )
    },
    tags=["Health"]
)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def health_check(request):
    """
    Simple health check endpoint to verify the API is running.
    Returns a 200 OK response with a timestamp.
    """
    return Response({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat()
    }, status=status.HTTP_200_OK)
