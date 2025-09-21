import os
import time
import psutil
import django
import platform
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from django.utils import timezone
from django.db import connection
from django.conf import settings
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

@extend_schema(
    summary="Health Check",
    description="Comprehensive health check endpoint to verify API and system status",
    responses={
        200: OpenApiResponse(
            description="API is healthy",
            examples=[
                OpenApiExample(
                    "Health Response",
                    value={
                        "status": "healthy",
                        "timestamp": "2024-05-28T07:35:20Z",
                        "version": "0.1.0",
                        "environment": "production",
                        "database": {
                            "status": "connected",
                            "type": "postgresql"
                        },
                        "system": {
                            "memory_usage": "25%",
                            "cpu_usage": "10%"
                        },
                        "uptime": "2d 3h 45m"
                    }
                )
            ]
        ),
        503: OpenApiResponse(description="API is unhealthy or database connection failed")
    },
    tags=["Health"]
)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
def health_check(request):
    """
    Comprehensive health check endpoint to verify the API and system status.
    Returns detailed information about the application, database, and system resources.
    """
    # Check database connection
    db_status = "connected"
    db_type = "unknown"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            db_type = connection.vendor
    except Exception:
        db_status = "disconnected"
    
    # Get system information
    memory_usage = f"{psutil.virtual_memory().percent}%"
    cpu_usage = f"{psutil.cpu_percent(interval=0.1)}%"
    
    # Get process start time
    process = psutil.Process(os.getpid())
    start_time = process.create_time()
    uptime_seconds = time.time() - start_time
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    uptime = f"{int(days)}d {int(hours)}h {int(minutes)}m"
    
    # Get application version from settings or pyproject.toml
    version = getattr(settings, 'VERSION', '0.1.0')
    environment = getattr(settings, 'ENVIRONMENT', 'development')
    
    return Response({
        'status': 'healthy',
        'name': 'Nura Vault Backend',
        'timestamp': timezone.now().isoformat(),
        'version': version,
        'environment': environment,
        'database': {
            'status': db_status,
            'type': db_type
        },
        'system': {
            'memory_usage': memory_usage,
            'cpu_usage': cpu_usage,
            'platform': platform.platform(),
            'python_version': platform.python_version()
        },
        'django_version': django.__version__,
        'uptime': uptime
    }, status=status.HTTP_200_OK)
