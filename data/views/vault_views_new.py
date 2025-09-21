from rest_framework import viewsets, filters, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from ..models import VaultDepositRun, VaultWithdrawalRun
from ..serializers.vault_deposit_serializers import VaultDepositRunSerializer
from ..serializers.vault_withdrawal_serializers import VaultWithdrawalRunSerializer
from ..cache_utils import cache_response


class VaultDepositViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing vault deposit runs.
    """
    queryset = VaultDepositRun.objects.all().order_by('-created_at')
    serializer_class = VaultDepositRunSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'processed_count']
    ordering = ['-created_at']
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary="List Vault Deposits",
        description="Get a list of vault deposit runs with optional filtering by vault address, status, and date range",
        parameters=[
            OpenApiParameter(
                name='vault_address',
                description='Filter by vault address',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='status',
                description='Filter by status (success, failed, skipped)',
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
                name='asset_symbol',
                description='Filter by asset symbol (e.g., USDe, USDT0)',
                required=False,
                type=str
            ),
        ],
    )
    @cache_response(timeout=60)  # Cache for 1 minute
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Apply filters manually
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        vault_address = request.query_params.get('vault_address')
        if vault_address:
            queryset = queryset.filter(vault_address=vault_address)
            
        asset_symbol = request.query_params.get('asset_symbol')
        if asset_symbol:
            queryset = queryset.filter(asset_symbol=asset_symbol)
        
        days = request.query_params.get('days')
        if days:
            start_date = timezone.now() - timedelta(days=int(days))
            queryset = queryset.filter(created_at__gte=start_date)
        
        # Apply ordering
        queryset = self.filter_queryset(queryset)
            
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class VaultWithdrawalViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing vault withdrawal runs.
    """
    queryset = VaultWithdrawalRun.objects.all().order_by('-created_at')
    serializer_class = VaultWithdrawalRunSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['created_at', 'processed_count']
    ordering = ['-created_at']
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary="List Vault Withdrawals",
        description="Get a list of vault withdrawal runs with optional filtering by vault address, status, and date range",
        parameters=[
            OpenApiParameter(
                name='vault_address',
                description='Filter by vault address',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='status',
                description='Filter by status (success, failed, skipped)',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='days',
                description='Number of days to look back',
                required=False,
                type=int
            ),
        ],
    )
    @cache_response(timeout=60)  # Cache for 1 minute
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        
        # Apply filters manually
        status_filter = request.query_params.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        vault_address = request.query_params.get('vault_address')
        if vault_address:
            queryset = queryset.filter(vault_address=vault_address)
        
        days = request.query_params.get('days')
        if days:
            start_date = timezone.now() - timedelta(days=int(days))
            queryset = queryset.filter(created_at__gte=start_date)
        
        # Apply ordering
        queryset = self.filter_queryset(queryset)
            
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)
