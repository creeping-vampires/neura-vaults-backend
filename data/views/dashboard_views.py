import logging
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiResponse, OpenApiExample, OpenApiParameter
from rest_framework import status,serializers
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from rest_framework.response import Response
from data.data_access_layer import AgentDAL
from ..models import AgentTrade, PortfolioSnapshot
from ..cache_utils import cache_response
from .utils import log_error

logger = logging.getLogger(__name__)

@extend_schema(
    summary="Global Dashboard Data",
    description="Get global dashboard data including total AUM, active agents, 24-hour trade volume, total trades, and daily trade volumes with 24-hour percent changes",
    responses={
        200: OpenApiResponse(
            description="Dashboard data retrieved successfully",
            response=inline_serializer(
                name="Dashboard Response",
                fields={
                    "total_aum": serializers.FloatField(help_text="Total assets under management in USD"),
                    "total_aum_percent_change": serializers.FloatField(help_text="24-hour percent change in total AUM"),
                    "active_agents": serializers.IntegerField(help_text="Number of active agents"),
                    "active_agents_percent_change": serializers.FloatField(help_text="24-hour percent change in active agents"),
                    "trade_volume_24h": serializers.FloatField(help_text="Total trade volume in the last 24 hours in USD"),
                    "trade_volume_percent_change": serializers.FloatField(help_text="24-hour percent change in trade volume"),
                    "total_trades_24h": serializers.IntegerField(help_text="Total number of trades in the last 24 hours"),
                    "total_trades_percent_change": serializers.FloatField(help_text="24-hour percent change in total trades"),
                    "daily_trade_volumes": serializers.ListField(
                        child=inline_serializer(
                            name="Daily Volume",
                            fields={
                                "date": serializers.DateField(help_text="Date of the trade volume data"),
                                "volume": serializers.FloatField(help_text="Trade volume for this date in USD")
                            }
                        ),
                        help_text="List of daily trade volumes for the past 7 days"
                    )
                }
            )
        ),
        500: OpenApiResponse(description="Error retrieving dashboard data")
    },
    tags=["Dashboard"]
)
@api_view(['GET'])
@authentication_classes([])
@permission_classes([])
@cache_response(timeout=settings.DASHBOARD_CACHE_TIMEOUT, key_prefix='dashboard')
def global_dashboard(request):
    """
    Get global dashboard data for all agents.
    
    Returns:
        - total_aum: Total assets under management in USD
        - total_aum_percent_change: 24-hour percent change in total AUM
        - active_agents: Number of active agents
        - active_agents_percent_change: 24-hour percent change in active agents
        - trade_volume_24h: Total trade volume in the last 24 hours in USD
        - trade_volume_percent_change: 24-hour percent change in trade volume
        - total_trades_24h: Total number of trades in the last 24 hours
        - total_trades_percent_change: 24-hour percent change in total trades
        - daily_trade_volumes: List of daily trade volumes for the past 7 days
    """
    try:
        
        # Helper function to calculate percent change
        def calculate_percent_change(current, previous):
            if previous == 0:
                return 0 if current == 0 else 100.0  # 100% increase from 0
            return ((current - previous) / previous) * 100.0
        
        # Current period metrics
        # Get active agents count
        active_agents = AgentDAL.get_active_agents_count()
        
        # Get recent trades (current 24 hours)
        recent_trades = AgentDAL.get_recent_trades(hours=24)
        total_trades_24h = recent_trades.count()
        logger.info(f"Dashboard API - Total trades in last 24h: {total_trades_24h}")
        
        # Log total trades in database for debugging
        all_trades_count = AgentTrade.objects.all().count()
        logger.info(f"Dashboard API - Total trades in database: {all_trades_count}")
        
        # Calculate 24-hour trade volume
        trade_volume = recent_trades.aggregate(volume=Sum('amount_usd'))
        trade_volume_24h = float(trade_volume['volume'] or 0)
    
        # Get the latest snapshot for each agent (regardless of status)
        latest_snapshots = PortfolioSnapshot.objects.raw(
            """
            SELECT ps.* FROM data_portfoliosnapshot ps
            INNER JOIN (
                SELECT agent_id, MAX(timestamp) as max_timestamp
                FROM data_portfoliosnapshot
                GROUP BY agent_id
            ) latest ON ps.agent_id = latest.agent_id AND ps.timestamp = latest.max_timestamp
            INNER JOIN data_agent a ON ps.agent_id = a.id
            WHERE a.is_deleted = FALSE
              AND a.deleted_at IS NULL
            """
        )
        
        # Calculate total AUM from snapshots
        total_aum = sum(float(snapshot.total_usd_value) for snapshot in latest_snapshots)
        logger.info(f"Dashboard API - Total AUM from portfolio snapshots: {total_aum}")
        
        # Fallback to zero if no snapshots exist
        if total_aum == 0:
            logger.warning("No portfolio snapshots found for AUM calculation")
            total_aum = 0.0
        
        # Previous period metrics (24-48 hours ago)
        # Calculate the timestamp for 24 hours ago using server's local timezone
        now = timezone.localtime(timezone.now())
        time_24h_ago = now - timezone.timedelta(hours=24)
        logger.info(f"Dashboard API - Using 24h ago reference time: {time_24h_ago} (Server local time)")
        
        # Get active agents count 24 hours ago
        previous_active_agents = AgentDAL.get_active_agents_count(as_of=time_24h_ago)
        
        # Get previous day's trade volume and count (for consistency with chart data)
        previous_trade_volume_24h = AgentDAL.get_previous_day_trade_volume()
        previous_total_trades = AgentDAL.get_previous_day_trade_count()
        logger.info(f"Dashboard API - Previous day trade volume: {previous_trade_volume_24h}, count: {previous_total_trades}")
        
        # Calculate previous total AUM using portfolio snapshots from 24 hours ago
        # Find snapshots closest to 24 hours ago for each agent (regardless of status)
        previous_snapshots = PortfolioSnapshot.objects.raw(
            """
            SELECT ps.* FROM data_portfoliosnapshot ps
            INNER JOIN (
                SELECT agent_id, MAX(timestamp) as max_timestamp
                FROM data_portfoliosnapshot
                WHERE timestamp <= %s
                GROUP BY agent_id
            ) prev ON ps.agent_id = prev.agent_id AND ps.timestamp = prev.max_timestamp
            INNER JOIN data_agent a ON ps.agent_id = a.id
            WHERE a.is_deleted = FALSE
              AND a.deleted_at IS NULL
            """, [time_24h_ago]
        )
        
        # Calculate previous total AUM from snapshots
        previous_total_aum = sum(float(snapshot.total_usd_value) for snapshot in previous_snapshots)
        logger.info(f"Dashboard API - Previous total AUM from portfolio snapshots: {previous_total_aum}")
        
        # Fallback to zero if no previous snapshots exist
        if previous_total_aum == 0:
            logger.warning("No previous portfolio snapshots found for AUM calculation")
            previous_total_aum = 0.0
        
        # Calculate percent changes
        total_aum_percent_change = calculate_percent_change(total_aum, previous_total_aum)
        active_agents_percent_change = calculate_percent_change(active_agents, previous_active_agents)
        trade_volume_percent_change = calculate_percent_change(trade_volume_24h, previous_trade_volume_24h)
        total_trades_percent_change = calculate_percent_change(total_trades_24h, previous_total_trades)
        
        # Get daily trade volumes for the past 7 days
        daily_trade_volumes = AgentDAL.get_daily_trade_volumes(days=7)
        
        return Response({
            "total_aum": total_aum,
            "total_aum_percent_change": round(total_aum_percent_change, 2),
            "active_agents": active_agents,
            "active_agents_percent_change": round(active_agents_percent_change, 2),
            "trade_volume_24h": trade_volume_24h,
            "trade_volume_percent_change": round(trade_volume_percent_change, 2),
            "total_trades_24h": total_trades_24h,
            "total_trades_percent_change": round(total_trades_percent_change, 2),
            "daily_trade_volumes": daily_trade_volumes
        })
    
    except Exception as e:
        error_context = log_error(e, {
            'endpoint': 'global_dashboard'
        })
        return Response({
            "error": f"Error retrieving dashboard data: {str(e)}",
            "error_id": error_context.get('error_id')
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)