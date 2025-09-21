from rest_framework import serializers
from data.models import VaultWithdrawalRun, VaultWithdrawalTransaction


class VaultWithdrawalTransactionSerializer(serializers.ModelSerializer):
    """Serializer for VaultWithdrawalTransaction model"""
    
    class Meta:
        model = VaultWithdrawalTransaction
        fields = [
            'id',
            'transaction_hash',
            'gas_used',
            'status',
            'created_at'
        ]
        read_only_fields = fields


class VaultWithdrawalRunSerializer(serializers.ModelSerializer):
    """Serializer for VaultWithdrawalRun model"""
    
    transactions = VaultWithdrawalTransactionSerializer(many=True, read_only=True)
    
    class Meta:
        model = VaultWithdrawalRun
        fields = [
            'id',
            'status',
            'vault_address',
            'queue_length_before',
            'queue_length_after',
            'processed_count',
            'batch_size',
            'total_withdrawal_amount',
            'total_withdrawal_amount_formatted',
            'asset_symbol',
            'asset_decimals',
            'error_message',
            'execution_duration_seconds',
            'created_at',
            'transactions'
        ]
        read_only_fields = fields
