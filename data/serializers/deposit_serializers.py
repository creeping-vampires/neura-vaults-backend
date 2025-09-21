import logging
from rest_framework import serializers
from decimal import Decimal
from django.utils.translation import gettext_lazy as _
from data.utils.rpc_utils import get_token_decimals, get_transaction_receipt, get_token_transfer_events, verify_token_transfer, get_web3_provider
from ..models import Agent, CapitalFlow

logger = logging.getLogger(__name__)

class DepositSerializer(serializers.Serializer):
    """
    Serializer for recording deposits with transaction hash verification.
    Validates the transaction on-chain before recording the deposit.
    """
    agent_id = serializers.IntegerField(required=True, help_text=_('ID of the agent receiving the deposit'))
    transaction_hash = serializers.CharField(max_length=66, required=True, help_text=_('Transaction hash of the deposit transaction'))
    token_address = serializers.CharField(max_length=42, required=True, help_text=_('Contract address of the deposited token'))
    token_symbol = serializers.CharField(max_length=10, required=True, help_text=_('Symbol of the deposited token'))
    notes = serializers.CharField(required=False, allow_blank=True, help_text=_('Optional notes about this deposit'))
    
    def validate(self, data):
        request = self.context.get('request')
        user = request.user if request else None
        
        if not user:
            raise serializers.ValidationError(_("User must be authenticated"))
        
        # Validate agent ownership
        agent_id = data.get('agent_id')
        try:
            agent = Agent.objects.get(id=agent_id)
            if agent.user.privy_address != user.privy_address:
                raise serializers.ValidationError({"agent_id": _("You don't have permission to access this agent")})
        except Agent.DoesNotExist:
            raise serializers.ValidationError({"agent_id": _("Agent not found")})
        
        # Store agent in validated data for later use
        data['agent'] = agent
        
        # Validate transaction hash
        tx_hash = data.get('transaction_hash')
        token_address = data.get('token_address')
        token_symbol = data.get('token_symbol')
        
        # Check if this transaction hash has already been recorded anywhere in the system
        existing_deposit = CapitalFlow.objects.filter(
            transaction_hash=tx_hash,
            flow_type='deposit'
        ).first()
        
        if existing_deposit:
            raise serializers.ValidationError({
                "transaction_hash": _(f"This transaction has already been recorded as a deposit in the system (ID: {existing_deposit.id})")
            })
        
        # Get transaction receipt to verify it exists and was successful
        receipt = get_transaction_receipt(tx_hash)
        if not receipt:
            raise serializers.ValidationError({"transaction_hash": _("Transaction not found or pending")})
        
        if receipt.get('status') != 1:
            raise serializers.ValidationError({"transaction_hash": _("Transaction failed")})
        
        # Verify this is a token transfer to the agent's wallet
        wallet_address = agent.wallet.address if hasattr(agent, 'wallet') else None
        if not wallet_address:
            raise serializers.ValidationError({"agent_id": _("Agent has no associated wallet")})
        
        # Check if this is a HYPE token deposit
        is_hype_token = token_address.lower() == '0x5555555555555555555555555555555555555555'
        
        if is_hype_token:
            # For HYPE token, verify the transaction directly
            try:
                w3 = get_web3_provider()
                tx = w3.eth.get_transaction(tx_hash)
                
                # Check if the transaction is to the agent's wallet
                if tx and tx.get('to') and tx['to'].lower() == wallet_address.lower():
                    # Get the value transferred
                    value = tx.get('value', 0)
                    
                    # Store the verified amount in validated data
                    data['amount_wei'] = value
                    data['amount'] = w3.from_wei(value, 'ether')
                    
                    # Fetch the token price and calculate USD value
                    from ..utils.common import fetch_token_price
                    from asgiref.sync import async_to_sync
                    
                    token_price = async_to_sync(fetch_token_price)(token_symbol)
                    if token_price is not None:
                        data['usd_value'] = float(data['amount']) * token_price
                        logger.info(f"Calculated USD value for HYPE deposit: {data['usd_value']} USD (amount: {data['amount']}, price: {token_price})")
                    else:
                        # Fallback if price not available
                        data['usd_value'] = float(data['amount'])
                        logger.warning(f"Could not fetch price for {token_symbol}, using token amount as USD value")
                    
                    logger.info(f"Verified HYPE token deposit of {data['amount']} {token_symbol} to {wallet_address}")
                    return data
                else:
                    raise serializers.ValidationError({"transaction_hash": _("Transaction is not a valid HYPE token deposit to the agent's wallet")})
            except Exception as e:
                logger.error(f"Error verifying HYPE token deposit: {str(e)}")
                raise serializers.ValidationError({"transaction_hash": _("Failed to verify HYPE token deposit")})
        else:
            # For ERC20 tokens, use the existing verification logic
            # Get token transfer events from the transaction
            transfer_events = get_token_transfer_events(tx_hash, token_address)
            
            # Verify the transfer was to the agent's wallet
            transfer_data = verify_token_transfer(transfer_events, wallet_address)
            if not transfer_data:
                raise serializers.ValidationError({"transaction_hash": _("No valid token transfer to agent wallet found in this transaction")})
            
            # Get token decimals to convert wei amount to decimal
            decimals = get_token_decimals(token_address)
            
            # Convert wei amount to decimal
            amount_wei = Decimal(transfer_data['value'])
            amount = amount_wei / (10 ** decimals)
            
            # Store the verified amount in validated data
            data['amount'] = amount
            data['amount_wei'] = amount_wei
            
            # Fetch the token price and calculate USD value
            from ..utils.common import fetch_token_price
            from asgiref.sync import async_to_sync
            
            token_price = async_to_sync(fetch_token_price)(token_symbol)
            if token_price is not None:
                data['usd_value'] = float(amount) * token_price
                logger.info(f"Calculated USD value for {token_symbol} deposit: {data['usd_value']} USD (amount: {amount}, price: {token_price})")
            else:
                # Fallback if price not available
                data['usd_value'] = float(amount)
                logger.warning(f"Could not fetch price for {token_symbol}, using token amount as USD value")
        
        return data
    
    def create(self, validated_data):
        """
        Create a CapitalFlow record for the deposit after validation.
        """
        agent = validated_data['agent']
        
        # Create the capital flow record
        capital_flow = CapitalFlow.objects.create(
            agent=agent,
            flow_type='deposit',
            token_address=validated_data['token_address'],
            token_symbol=validated_data['token_symbol'],
            amount=validated_data['amount'],
            usd_value=validated_data['usd_value'],
            transaction_hash=validated_data['transaction_hash'],
            notes=validated_data.get('notes', f"Deposit verified via transaction hash")
        )
        
        logger.info(f"Created deposit record {capital_flow.id} for agent {agent.id} with transaction hash {validated_data['transaction_hash']}")
        
        # Note: Portfolio snapshot creation is now handled in the view after confirming deposit success
        
        return {
            'id': capital_flow.id,
            'agent_id': agent.id,
            'token_symbol': validated_data['token_symbol'],
            'amount': str(validated_data['amount']),
            'usd_value': str(validated_data['usd_value']),
            'transaction_hash': validated_data['transaction_hash'],
            'timestamp': capital_flow.timestamp.isoformat(),
            'notes': capital_flow.notes
        }
