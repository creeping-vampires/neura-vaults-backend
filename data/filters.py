from django_filters import rest_framework as filters
from .models import VaultDepositRun, VaultWithdrawalRun, VaultRebalance
from django.utils import timezone
from datetime import timedelta


class VaultDepositFilter(filters.FilterSet):
    """Filter for VaultDepositRun model"""
    days = filters.NumberFilter(method='filter_by_days')
    
    class Meta:
        model = VaultDepositRun
        fields = {
            'vault_address': ['exact'],
            'status': ['exact'],
            'asset_symbol': ['exact'],
        }
    
    def filter_by_days(self, queryset, name, value):
        if value:
            start_date = timezone.now() - timedelta(days=int(value))
            return queryset.filter(created_at__gte=start_date)
        return queryset


class VaultWithdrawalFilter(filters.FilterSet):
    """Filter for VaultWithdrawalRun model"""
    days = filters.NumberFilter(method='filter_by_days')
    
    class Meta:
        model = VaultWithdrawalRun
        fields = {
            'vault_address': ['exact'],
            'status': ['exact'],
            'asset_symbol': ['exact'],
        }
    
    def filter_by_days(self, queryset, name, value):
        if value:
            start_date = timezone.now() - timedelta(days=int(value))
            return queryset.filter(created_at__gte=start_date)
        return queryset


class VaultRebalanceFilter(filters.FilterSet):
    """Filter for VaultRebalance model"""
    days = filters.NumberFilter(method='filter_by_days')
    start_date = filters.DateTimeFilter(field_name='created_at', lookup_expr='gte')
    end_date = filters.DateTimeFilter(field_name='created_at', lookup_expr='lte')
    
    class Meta:
        model = VaultRebalance
        fields = {
            'rebalance_id': ['exact'],
            'transaction_type': ['exact'],
            'status': ['exact'],
            'from_protocol': ['exact'],
            'to_protocol': ['exact'],
            'from_pool_address': ['exact'],
            'to_pool_address': ['exact'],
            'token_symbol': ['exact'],
        }
    
    def filter_by_days(self, queryset, name, value):
        if value:
            start_date = timezone.now() - timedelta(days=int(value))
            return queryset.filter(created_at__gte=start_date)
        return queryset
