from rest_framework import viewsets, filters, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, OpenApiParameter, extend_schema_view
from django.utils import timezone
from datetime import timedelta

from ..models import VaultRebalance
from ..serializers.vault_rebalance_serializers import VaultRebalanceSerializer, CombinedVaultRebalanceSerializer
from ..cache_utils import cache_response
from ..filters import VaultRebalanceFilter


class VaultRebalanceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing vault rebalance trades.
    """
    queryset = VaultRebalance.objects.all().order_by('-created_at')
    serializer_class = VaultRebalanceSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = VaultRebalanceFilter
    ordering_fields = ['created_at', 'amount_usd', 'transaction_type']
    ordering = ['-created_at']
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary="List Vault Rebalance Trades",
        description="Get a list of vault rebalance trades with optional filtering by rebalance ID, transaction type, status, protocols, and date range",
        parameters=[
            OpenApiParameter(
                name='rebalance_id',
                description='Filter by rebalance ID',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='transaction_type',
                description='Filter by transaction type (withdrawal, deposit)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='status',
                description='Filter by status (pending, completed, failed)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='from_protocol',
                description='Filter by source protocol',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='to_protocol',
                description='Filter by destination protocol',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='days',
                description='Number of days to look back',
                required=False,
                type=int
            ),
            OpenApiParameter(
                name='start_date',
                description='Start date for filtering (YYYY-MM-DD)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='end_date',
                description='End date for filtering (YYYY-MM-DD)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='token_symbol',
                description='Filter by token symbol',
                required=False,
                type=str
            ),
        ],
    )
    @cache_response(timeout=60)  # Cache for 1 minute
    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
            
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        summary="List Combined Rebalance Trades",
        description="Get a list of combined rebalance trades where withdrawal and deposit transactions with the same rebalance ID are merged into a single object",
        parameters=[
            OpenApiParameter(
                name='rebalance_id',
                description='Filter by rebalance ID',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='status',
                description='Filter by status (pending, completed, failed)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='from_protocol',
                description='Filter by source protocol',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='to_protocol',
                description='Filter by destination protocol',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='days',
                description='Number of days to look back',
                required=False,
                type=int
            ),
            OpenApiParameter(
                name='start_date',
                description='Start date for filtering (YYYY-MM-DD)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='end_date',
                description='End date for filtering (YYYY-MM-DD)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='token_symbol',
                description='Filter by token symbol',
                required=False,
                type=str
            ),
        ],
    )
    @action(detail=False, methods=['get'], url_path='combined')
    @cache_response(timeout=60)  # Cache for 1 minute
    def combined_trades(self, request):
        """
        Get a list of combined rebalance trades where withdrawal and deposit transactions 
        with the same rebalance ID are merged into a single object.
        """
        # Apply filters to the base queryset
        queryset = self.filter_queryset(self.get_queryset())
        
        # Get combined trades
        combined_trades = CombinedVaultRebalanceSerializer.get_combined_rebalance_trades(queryset)
        
        # Paginate the results
        page = self.paginate_queryset(combined_trades)
        if page is not None:
            serializer = CombinedVaultRebalanceSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = CombinedVaultRebalanceSerializer(combined_trades, many=True)
        return Response(serializer.data)
