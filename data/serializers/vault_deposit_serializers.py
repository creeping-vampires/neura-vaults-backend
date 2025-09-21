from rest_framework import serializers
from data.models import VaultDepositRun, VaultDepositTransaction


class VaultDepositTransactionSerializer(serializers.ModelSerializer):
    """Serializer for VaultDepositTransaction model"""
    
    class Meta:
        model = VaultDepositTransaction
        fields = [
            'id',
            'transaction_hash',
            'gas_used',
            'status',
            'created_at'
        ]
        read_only_fields = fields


class VaultDepositRunSerializer(serializers.ModelSerializer):
    """Serializer for VaultDepositRun model"""
    
    transactions = VaultDepositTransactionSerializer(many=True, read_only=True)
    
    class Meta:
        model = VaultDepositRun
        fields = [
            'id',
            'status',
            'vault_address',
            'asset_address',
            'asset_symbol',
            'asset_decimals',
            'queue_length_before',
            'queue_length_after',
            'processed_count',
            'batch_size',
            'total_assets_to_deposit',
            'idle_assets_before',
            'error_message',
            'execution_duration_seconds',
            'created_at',
            'transactions'
        ]
        read_only_fields = fields
