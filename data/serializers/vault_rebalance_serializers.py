from rest_framework import serializers
from django.db.models import Q
from collections import defaultdict
from ..models import VaultRebalance


class VaultRebalanceSerializer(serializers.ModelSerializer):
    """
    Serializer for the VaultRebalance model.
    """
    class Meta:
        model = VaultRebalance
        fields = [
            'id', 'rebalance_id', 'transaction_type', 'status',
            'from_protocol', 'to_protocol', 'from_pool_address', 'to_pool_address',
            'amount_usd', 'amount_token', 'amount_token_raw', 'token_symbol', 'token_decimals',
            'transaction_hash', 'block_number', 'gas_used', 'gas_price',
            'error_message', 'strategy_summary', 'created_at', 'updated_at'
        ]


class CombinedVaultRebalanceSerializer(serializers.Serializer):
    """
    Serializer that combines withdrawal and deposit transactions with the same rebalance_id.
    """
    rebalance_id = serializers.CharField()
    status = serializers.CharField()
    from_protocol = serializers.CharField()
    to_protocol = serializers.CharField()
    from_pool_address = serializers.CharField()
    to_pool_address = serializers.CharField()
    amount_token = serializers.DecimalField(max_digits=78, decimal_places=18)
    amount_token_raw = serializers.CharField()
    token_symbol = serializers.CharField()
    token_decimals = serializers.IntegerField()
    strategy_summary = serializers.CharField(allow_null=True)
    withdrawal_transaction = serializers.SerializerMethodField()
    deposit_transaction = serializers.SerializerMethodField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()

    def get_withdrawal_transaction(self, obj):
        """
        Get the withdrawal transaction details.
        """
        if 'withdrawal' in obj:
            return {
                'id': obj['withdrawal'].id,
                'transaction_hash': obj['withdrawal'].transaction_hash,
                'block_number': obj['withdrawal'].block_number,
                'gas_used': obj['withdrawal'].gas_used,
                'gas_price': obj['withdrawal'].gas_price,
                'status': obj['withdrawal'].status,
                'error_message': obj['withdrawal'].error_message,
                'created_at': obj['withdrawal'].created_at,
                'updated_at': obj['withdrawal'].updated_at
            }
        return None

    def get_deposit_transaction(self, obj):
        """
        Get the deposit transaction details.
        """
        if 'deposit' in obj:
            return {
                'id': obj['deposit'].id,
                'transaction_hash': obj['deposit'].transaction_hash,
                'block_number': obj['deposit'].block_number,
                'gas_used': obj['deposit'].gas_used,
                'gas_price': obj['deposit'].gas_price,
                'status': obj['deposit'].status,
                'error_message': obj['deposit'].error_message,
                'created_at': obj['deposit'].created_at,
                'updated_at': obj['deposit'].updated_at
            }
        return None

    @classmethod
    def get_combined_rebalance_trades(cls, queryset=None):
        """
        Combine withdrawal and deposit transactions with the same rebalance_id.
        """
        if queryset is None:
            queryset = VaultRebalance.objects.all().order_by('-created_at')

        # Group transactions by rebalance_id
        rebalance_groups = defaultdict(dict)
        for transaction in queryset:
            rebalance_id = transaction.rebalance_id
            if transaction.transaction_type == VaultRebalance.WITHDRAWAL:
                rebalance_groups[rebalance_id]['withdrawal'] = transaction
            elif transaction.transaction_type == VaultRebalance.DEPOSIT:
                rebalance_groups[rebalance_id]['deposit'] = transaction

        # Create combined objects
        combined_trades = []
        for rebalance_id, transactions in rebalance_groups.items():
            # Skip if we don't have both withdrawal and deposit
            if 'withdrawal' not in transactions or 'deposit' not in transactions:
                continue

            withdrawal = transactions['withdrawal']
            deposit = transactions['deposit']

            # Determine overall status
            if withdrawal.status == VaultRebalance.FAILED or deposit.status == VaultRebalance.FAILED:
                status = VaultRebalance.FAILED
            elif withdrawal.status == VaultRebalance.PENDING or deposit.status == VaultRebalance.PENDING:
                status = VaultRebalance.PENDING
            else:
                status = VaultRebalance.COMPLETED

            # Create combined object
            combined_trade = {
                'rebalance_id': rebalance_id,
                'status': status,
                'from_protocol': withdrawal.from_protocol,
                'to_protocol': deposit.to_protocol,
                'from_pool_address': withdrawal.from_pool_address,
                'to_pool_address': deposit.to_pool_address,
                'amount_token': withdrawal.amount_token,  # Using withdrawal amount
                'amount_token_raw': withdrawal.amount_token_raw,
                'token_symbol': withdrawal.token_symbol,
                'token_decimals': withdrawal.token_decimals,
                'strategy_summary': withdrawal.strategy_summary or deposit.strategy_summary,  # Use either one if available
                'withdrawal': withdrawal,
                'deposit': deposit,
                'created_at': withdrawal.created_at,  # Using withdrawal timestamp
                'updated_at': max(withdrawal.updated_at, deposit.updated_at)  # Latest update
            }
            combined_trades.append(combined_trade)

        return combined_trades
