from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample
from data.data_access_layer import OptimizationResultDAO
from django.utils import timezone
from django.db.models import Q
from collections import defaultdict
from data.models import OptimizationResult, YieldReport

@extend_schema(
    summary="Recent Pool APY Results",
    description="Fetch the latest yield report for each unique pool-token combination, sorted by APY descending.",
    parameters=[],
    responses={
        200: OpenApiResponse(
            description="List of latest pool APY optimization results",
            examples=[
                OpenApiExample(
                    "Pool APY Results",
                    value={
                        "results": [
                            {
                                "id": 1,
                                "created_at": "2025-08-15T06:16:55.430365+00:00",
                                "token": "USDe",
                                "protocol": "Protocol",
                                "apy": 12.5,
                                "tvl": 1000000.0,
                                "token_address": "0x1234567890",
                                "pool_address": "0x9876543210",
                                "is_current_best": True
                            }
                        ],
                        "count": 1,
                        "pools_count": 1
                    }
                )
            ]
        )
    },
    tags=["Pool Optimization"]
)
@api_view(['GET'])
@authentication_classes([])  # Public endpoint, no authentication required
@permission_classes([])      # Public endpoint, no permissions required
def get_recent_pool_apy_results(request):
    """
    Fetch the latest yield report for each unique pool-token combination.
    Groups by pool address and token, returning the latest record for each combination,
    sorted by APY in descending order (highest yield first).
    This is a public endpoint that requires no authentication.
    """
    # Get all yield reports with valid pool addresses, excluding HYPE token
    yield_reports = YieldReport.objects.filter(
        pool_address__isnull=False,
        pool_address__gt=''
    ).exclude(
        token='HYPE'  # Exclude HYPE token
    ).order_by('pool_address', 'token', '-created_at')
    
    # Use a dictionary to track unique pool-token combinations
    unique_results = {}
    
    # Process each yield report
    for report in yield_reports:
        # Create a unique key for each pool-token combination
        key = f"{report.pool_address}_{report.token}"
        
        # Only add the first (latest) entry for each unique combination
        if key not in unique_results:
            unique_results[key] = {
                'id': report.id,
                'created_at': report.created_at,
                'token': report.token,
                'protocol': report.protocol,
                'apy': float(report.apy),
                'tvl': float(report.tvl),
                'token_address': report.token_address,
                'pool_address': report.pool_address,
                'is_current_best': report.is_current_best
            }
    
    # Convert dictionary values to list
    results_data = list(unique_results.values())
    
    # Sort all results by APY descending to show highest yields first
    results_data.sort(key=lambda x: x['apy'], reverse=True)
    
    return Response({
        'results': results_data,
        'count': len(results_data),
        'pools_count': len(unique_results)
    }, status=status.HTTP_200_OK)
