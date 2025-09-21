import logging
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse, OpenApiExample, OpenApiParameter
from rest_framework import status, serializers
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Avg, Count, Q
from rest_framework.response import Response
from datetime import datetime, timedelta, date
from decimal import Decimal
from ..models import YieldMonitorRun, YieldMonitorPoolSnapshot, YieldMonitorTransaction, YieldMonitorMetrics, VaultPrice
from ..cache_utils import cache_response
from .utils import log_error
from ..serializers import VaultPriceSerializer, VaultPriceChartSerializer

logger = logging.getLogger(__name__)

@extend_schema(
    summary="Latest Yield Monitor Status",
    description="Get the latest yield monitor run status and key metrics for dashboard display",
    responses={
        200: OpenApiResponse(
            description="Latest yield monitor status retrieved successfully",
            response=inline_serializer(
                name="YieldMonitorStatusResponse",
                fields={
                    "latest_run": inline_serializer(
                        name="LatestRun",
                        fields={
                            "id": serializers.IntegerField(help_text="Run ID"),
                            "timestamp": serializers.DateTimeField(help_text="Run timestamp"),
                            "status": serializers.CharField(help_text="Run status (success, failed, skipped)"),
                            "execution_duration": serializers.FloatField(help_text="Execution duration in seconds"),
                            "total_yield_generated": serializers.CharField(help_text="Total yield generated in wei"),
                            "total_yield_percentage": serializers.FloatField(help_text="Total yield percentage"),
                            "total_withdrawn": serializers.CharField(help_text="Total amount withdrawn in wei"),
                            "total_reinvested": serializers.CharField(help_text="Total amount reinvested in wei"),
                            "pools_processed": serializers.IntegerField(help_text="Number of pools processed"),
                            "pools_with_yield": serializers.IntegerField(help_text="Number of pools that had yield claimed"),
                            "vault_address": serializers.CharField(help_text="Vault contract address"),
                            "asset_symbol": serializers.CharField(help_text="Asset token symbol"),
                            "error_message": serializers.CharField(help_text="Error message if failed", allow_null=True),
                        }
                    ),
                    "daily_metrics": inline_serializer(
                        name="DailyMetrics",
                        fields={
                            "total_runs_today": serializers.IntegerField(help_text="Total runs today"),
                            "successful_runs_today": serializers.IntegerField(help_text="Successful runs today"),
                            "failed_runs_today": serializers.IntegerField(help_text="Failed runs today"),
                            "total_yield_claimed_today": serializers.CharField(help_text="Total yield claimed today in wei"),
                            "daily_growth_percentage": serializers.FloatField(help_text="Daily growth percentage"),
                            "average_execution_time": serializers.FloatField(help_text="Average execution time in seconds"),
                        }
                    ),
                    "vault_info": inline_serializer(
                        name="VaultInfo",
                        fields={
                            "total_principal_deposited": serializers.CharField(help_text="Total principal deposited in wei"),
                            "current_total_value": serializers.CharField(help_text="Current total value in wei"),
                            "idle_assets": serializers.CharField(help_text="Idle assets in vault in wei"),
                        }
                    ),
                    "recent_transactions": serializers.ListField(
                        child=inline_serializer(
                            name="RecentTransaction",
                            fields={
                                "transaction_hash": serializers.CharField(help_text="Transaction hash"),
                                "transaction_type": serializers.CharField(help_text="Transaction type (withdrawal/deposit)"),
                                "amount_formatted": serializers.FloatField(help_text="Transaction amount in human-readable format"),
                                "pool_address": serializers.CharField(help_text="Pool contract address"),
                                "submitted_at": serializers.DateTimeField(help_text="Transaction submission time"),
                                "status": serializers.CharField(help_text="Transaction status"),
                            }
                        ),
                        help_text="Recent transactions (last 10)"
                    )
                }
            )
        ),
        404: OpenApiResponse(description="No yield monitor runs found"),
        500: OpenApiResponse(description="Error retrieving yield monitor status")
    },
    tags=["Yield Monitor"]
)
@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
@cache_response(timeout=60)  # Cache for 1 minute
def get_yield_monitor_status(request):
    """Get the latest yield monitor status and key metrics"""
    try:
        # Get the latest run
        latest_run = YieldMonitorRun.objects.select_related().order_by('-timestamp').first()
        
        if not latest_run:
            return Response(
                {"error": "No yield monitor runs found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Get today's metrics
        today = date.today()
        daily_metrics = YieldMonitorMetrics.objects.filter(
            date=today,
            vault_address=latest_run.vault_address
        ).first()
        
        # Get recent transactions (last 10)
        recent_transactions = YieldMonitorTransaction.objects.select_related(
            'pool_snapshot'
        ).filter(
            monitor_run__vault_address=latest_run.vault_address
        ).order_by('-submitted_at')[:10]
        
        # Format the response
        response_data = {
            "latest_run": {
                "id": latest_run.id,
                "timestamp": latest_run.timestamp,
                "status": latest_run.status,
                "execution_duration": float(latest_run.execution_duration_seconds or 0),
                "total_yield_generated": str(latest_run.total_yield_generated),
                "total_yield_percentage": float(latest_run.total_yield_percentage),
                "total_withdrawn": str(latest_run.total_withdrawn),
                "total_reinvested": str(latest_run.total_reinvested),
                "pools_processed": latest_run.pools_processed,
                "pools_with_yield": latest_run.pools_with_yield,
                "vault_address": latest_run.vault_address,
                "asset_symbol": latest_run.asset_symbol,
                "error_message": latest_run.error_message,
            },
            "daily_metrics": {
                "total_runs_today": daily_metrics.total_runs if daily_metrics else 0,
                "successful_runs_today": daily_metrics.successful_runs if daily_metrics else 0,
                "failed_runs_today": daily_metrics.failed_runs if daily_metrics else 0,
                "total_yield_claimed_today": str(daily_metrics.total_yield_claimed if daily_metrics else 0),
                "daily_growth_percentage": float(daily_metrics.daily_growth_percentage if daily_metrics else 0),
                "average_execution_time": float(daily_metrics.average_execution_time if daily_metrics else 0),
            },
            "vault_info": {
                "total_principal_deposited": str(latest_run.total_principal_deposited),
                "current_total_value": str(latest_run.current_total_value),
                "idle_assets": str(latest_run.idle_assets),
            },
            "recent_transactions": [
                {
                    "transaction_hash": tx.transaction_hash,
                    "transaction_type": tx.transaction_type,
                    "amount_formatted": float(tx.amount_formatted),
                    "pool_address": tx.pool_snapshot.pool_address,
                    "submitted_at": tx.submitted_at,
                    "status": tx.status,
                }
                for tx in recent_transactions
            ]
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error retrieving yield monitor status: {str(e)}")
        return Response(
            {"error": "Error retrieving yield monitor status"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    summary="Yield Monitor History",
    description="Get historical yield monitor runs with pagination and filtering",
    parameters=[
        OpenApiParameter(
            name='days',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Number of days to look back (default: 7)',
            default=7
        ),
        OpenApiParameter(
            name='status',
            type=str,
            location=OpenApiParameter.QUERY,
            description='Filter by status (success, failed, skipped)',
            required=False
        ),
        OpenApiParameter(
            name='limit',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Maximum number of results (default: 50)',
            default=50
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Yield monitor history retrieved successfully",
            response=inline_serializer(
                name="YieldMonitorHistoryResponse",
                fields={
                    "runs": serializers.ListField(
                        child=inline_serializer(
                            name="HistoricalRun",
                            fields={
                                "id": serializers.IntegerField(),
                                "timestamp": serializers.DateTimeField(),
                                "status": serializers.CharField(),
                                "execution_duration": serializers.FloatField(),
                                "total_yield_percentage": serializers.FloatField(),
                                "total_withdrawn": serializers.CharField(),
                                "pools_processed": serializers.IntegerField(),
                                "pools_with_yield": serializers.IntegerField(),
                            }
                        )
                    ),
                    "summary": inline_serializer(
                        name="HistorySummary",
                        fields={
                            "total_runs": serializers.IntegerField(),
                            "success_rate": serializers.FloatField(),
                            "total_yield_claimed": serializers.CharField(),
                            "average_yield_percentage": serializers.FloatField(),
                        }
                    )
                }
            )
        ),
        500: OpenApiResponse(description="Error retrieving yield monitor history")
    },
    tags=["Yield Monitor"]
)
@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
@cache_response(timeout=300)  # Cache for 5 minutes
def get_yield_monitor_history(request):
    """Get historical yield monitor runs"""
    try:
        # Get query parameters
        days = int(request.GET.get('days', 7))
        status_filter = request.GET.get('status')
        limit = int(request.GET.get('limit', 50))
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Build query
        query = YieldMonitorRun.objects.filter(
            timestamp__gte=start_date,
            timestamp__lte=end_date
        )
        
        if status_filter:
            query = query.filter(status=status_filter)
        
        # Get runs
        runs = query.order_by('-timestamp')[:limit]
        
        # Calculate summary statistics
        total_runs = query.count()
        successful_runs = query.filter(status='success').count()
        success_rate = (successful_runs / total_runs * 100) if total_runs > 0 else 0
        
        total_yield_claimed = query.aggregate(
            total=Sum('total_withdrawn')
        )['total'] or 0
        
        average_yield_percentage = query.aggregate(
            avg=Avg('total_yield_percentage')
        )['avg'] or 0
        
        # Format response
        response_data = {
            "runs": [
                {
                    "id": run.id,
                    "timestamp": run.timestamp,
                    "status": run.status,
                    "execution_duration": float(run.execution_duration_seconds or 0),
                    "total_yield_percentage": float(run.total_yield_percentage),
                    "total_withdrawn": str(run.total_withdrawn),
                    "pools_processed": run.pools_processed,
                    "pools_with_yield": run.pools_with_yield,
                }
                for run in runs
            ],
            "summary": {
                "total_runs": total_runs,
                "success_rate": round(success_rate, 2),
                "total_yield_claimed": str(total_yield_claimed),
                "average_yield_percentage": round(float(average_yield_percentage), 6),
            }
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error retrieving yield monitor history: {str(e)}")
        return Response(
            {"error": "Error retrieving yield monitor history"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    summary="Pool Performance Data",
    description="Get performance data for individual pools from recent yield monitor runs",
    parameters=[
        OpenApiParameter(
            name='days',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Number of days to look back (default: 7)',
            default=7
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Pool performance data retrieved successfully",
            response=inline_serializer(
                name="PoolPerformanceResponse",
                fields={
                    "pools": serializers.ListField(
                        child=inline_serializer(
                            name="PoolPerformance",
                            fields={
                                "pool_address": serializers.CharField(),
                                "total_principal": serializers.CharField(),
                                "total_yield_generated": serializers.CharField(),
                                "average_yield_percentage": serializers.FloatField(),
                                "times_processed": serializers.IntegerField(),
                                "last_processed": serializers.DateTimeField(),
                                "success_rate": serializers.FloatField(),
                            }
                        )
                    )
                }
            )
        ),
        500: OpenApiResponse(description="Error retrieving pool performance data")
    },
    tags=["Yield Monitor"]
)
@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
@cache_response(timeout=300)  # Cache for 5 minutes
def get_pool_performance(request):
    """Get performance data for individual pools"""
    try:
        days = int(request.GET.get('days', 7))
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Get pool snapshots from the time range
        pool_snapshots = YieldMonitorPoolSnapshot.objects.select_related(
            'monitor_run'
        ).filter(
            monitor_run__timestamp__gte=start_date,
            monitor_run__timestamp__lte=end_date
        )
        
        # Aggregate data by pool
        pool_data = {}
        for snapshot in pool_snapshots:
            pool_addr = snapshot.pool_address
            
            if pool_addr not in pool_data:
                pool_data[pool_addr] = {
                    'total_principal': 0,
                    'total_yield': 0,
                    'yield_percentages': [],
                    'processed_count': 0,
                    'total_runs': 0,
                    'last_processed': None,
                }
            
            pool_info = pool_data[pool_addr]
            pool_info['total_principal'] = max(pool_info['total_principal'], snapshot.principal_deposited)
            pool_info['total_yield'] += snapshot.calculated_yield_share
            pool_info['yield_percentages'].append(float(snapshot.yield_percentage))
            pool_info['total_runs'] += 1
            
            if snapshot.was_processed:
                pool_info['processed_count'] += 1
                if not pool_info['last_processed'] or snapshot.monitor_run.timestamp > pool_info['last_processed']:
                    pool_info['last_processed'] = snapshot.monitor_run.timestamp
        
        # Format response
        pools_response = []
        for pool_addr, data in pool_data.items():
            avg_yield_percentage = sum(data['yield_percentages']) / len(data['yield_percentages']) if data['yield_percentages'] else 0
            success_rate = (data['processed_count'] / data['total_runs'] * 100) if data['total_runs'] > 0 else 0
            
            pools_response.append({
                "pool_address": pool_addr,
                "total_principal": str(data['total_principal']),
                "total_yield_generated": str(data['total_yield']),
                "average_yield_percentage": round(avg_yield_percentage, 6),
                "times_processed": data['processed_count'],
                "last_processed": data['last_processed'],
                "success_rate": round(success_rate, 2),
            })
        
        # Sort by total principal (descending)
        pools_response.sort(key=lambda x: int(x['total_principal']), reverse=True)
        
        return Response({"pools": pools_response}, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error retrieving pool performance data: {str(e)}")
        return Response(
            {"error": "Error retrieving pool performance data"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    summary="Daily Metrics Chart Data",
    description="Get daily aggregated metrics for charting and trend analysis",
    parameters=[
        OpenApiParameter(
            name='days',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Number of days to look back (default: 30)',
            default=30
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Daily metrics retrieved successfully",
            response=inline_serializer(
                name="DailyMetricsResponse",
                fields={
                    "daily_data": serializers.ListField(
                        child=inline_serializer(
                            name="DailyMetric",
                            fields={
                                "date": serializers.DateField(),
                                "total_runs": serializers.IntegerField(),
                                "successful_runs": serializers.IntegerField(),
                                "total_yield_claimed": serializers.CharField(),
                                "daily_growth_percentage": serializers.FloatField(),
                                "average_execution_time": serializers.FloatField(),
                                "vault_value_end": serializers.CharField(),
                            }
                        )
                    )
                }
            )
        ),
        500: OpenApiResponse(description="Error retrieving daily metrics")
    },
    tags=["Yield Monitor"]
)
@api_view(['GET'])
@authentication_classes([TokenAuthentication])
@permission_classes([AllowAny])
@cache_response(timeout=600)  # Cache for 10 minutes
def get_daily_metrics(request):
    """Get daily aggregated metrics for charting"""
    try:
        days = int(request.GET.get('days', 30))
        
        # Calculate date range
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        # Get daily metrics
        daily_metrics = YieldMonitorMetrics.objects.filter(
            date__gte=start_date,
            date__lte=end_date
        ).order_by('date')
        
        # Format response
        daily_data = [
            {
                "date": metric.date,
                "total_runs": metric.total_runs,
                "successful_runs": metric.successful_runs,
                "total_yield_claimed": str(metric.total_yield_claimed),
                "daily_growth_percentage": float(metric.daily_growth_percentage),
                "average_execution_time": float(metric.average_execution_time),
                "vault_value_end": str(metric.vault_value_end or 0),
            }
            for metric in daily_metrics
        ]
        
        return Response({"daily_data": daily_data}, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error retrieving daily metrics: {str(e)}")
        return Response(
            {"error": "Error retrieving daily metrics"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    summary="Latest Vault Prices",
    description="Get the latest vault price data for both USDe and USDT0 vaults",
    responses={
        200: OpenApiResponse(
            description="Dictionary with token symbols as keys and vault price data as values"
        ),
        404: OpenApiResponse(description="No vault price data found"),
        500: OpenApiResponse(description="Error retrieving vault price data")
    },
    tags=["Yield Monitor"]
)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@cache_response(timeout=60)  # Cache for 1 minute
def get_latest_vault_price(request):
    """Get the latest vault price data for both USDe and USDT0 vaults"""
    try:
        from ..models import VaultPrice
        from ..serializers import VaultPriceSerializer
        
        # Get the latest vault price records for each token type
        tokens = ['USDe', 'USDT0']
        result = []
        
        for token in tokens:
            latest_price = VaultPrice.objects.filter(token=token).order_by('-created_at').first()
            if latest_price:
                serializer = VaultPriceSerializer(latest_price)
                result.append(serializer.data)
        
        if not result:
            return Response(
                {"error": "No vault price data found"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        return Response(result, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error retrieving latest vault prices: {str(e)}")
        return Response(
            {"error": "Error retrieving vault price data"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@extend_schema(
    summary="Vault Price Chart Data",
    description="Get historical vault price data for charting",
    parameters=[
        OpenApiParameter(
            name='days',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Number of days to look back (default: 30)',
            default=30
        ),
        OpenApiParameter(
            name='limit',
            type=int,
            location=OpenApiParameter.QUERY,
            description='Maximum number of data points (default: 100)',
            default=100
        ),
    ],
    responses={
        200: OpenApiResponse(
            description="Vault price chart data retrieved successfully",
            response=inline_serializer(
                name="VaultPriceChartResponse",
                fields={
                    "chart_data": serializers.ListField(
                        child=inline_serializer(
                            name="VaultPriceDataPoint",
                            fields={
                                "timestamp": serializers.DateTimeField(help_text="Data point timestamp"),
                                "share_price_formatted": serializers.DecimalField(help_text="Formatted share price", max_digits=20, decimal_places=8),
                                "pool_apy": serializers.DecimalField(help_text="Highest pool APY at this time", max_digits=10, decimal_places=4),
                            }
                        )
                    )
                }
            )
        ),
        404: OpenApiResponse(description="No vault price data found"),
        500: OpenApiResponse(description="Error retrieving vault price chart data")
    },
    tags=["Yield Monitor"]
)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([AllowAny])
@cache_response(timeout=300)  # Cache for 5 minutes
def get_vault_price_chart_data(request):
    """Get historical vault price data for charting for both USDe and USDT0 vaults"""
    try:
        from ..models import VaultPrice
        from ..serializers import VaultPriceChartSerializer
        
        # Get query parameters
        days = int(request.GET.get('days', 30))
        limit = int(request.GET.get('limit', 100))
        token = request.GET.get('token', None)  # Optional token filter
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Base query for date range
        base_query = VaultPrice.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        # Process each token type separately
        result = []
        tokens = [token] if token else ['USDe', 'USDT0']
        
        for current_token in tokens:
            # Filter by token
            token_data = base_query.filter(token=current_token).order_by('created_at')
            
            if not token_data.exists():
                continue
                
            # If there's more data than the limit, sample it
            if token_data.count() > limit:
                # Simple sampling - get every Nth record
                step = token_data.count() // limit
                sampled_indices = range(0, token_data.count(), step)
                token_data = [token_data[i] for i in sampled_indices if i < token_data.count()][:limit]
            
            # Serialize the data
            serializer = VaultPriceChartSerializer(token_data, many=True)
            result.append({
                "token": current_token,
                "data": serializer.data
            })
        
        if not result:
            return Response(
                {"error": "No vault price chart data found"},
                status=status.HTTP_404_NOT_FOUND
            )
            
        return Response({"chart_data": result}, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error retrieving vault price chart data: {str(e)}")
        return Response(
            {"error": "Error retrieving vault price chart data"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
