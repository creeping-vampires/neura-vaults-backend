import logging
from rest_framework import serializers
from decimal import Decimal
from data.utils.rpc_utils import get_token_balance, get_token_decimals
from ..models import Withdrawal, CapitalFlow

logger = logging.getLogger(__name__)

class WithdrawalSerializer(serializers.ModelSerializer):
    """
    Serializer for Withdrawal model.
    Handles validation and creation of withdrawal requests by users.
    """
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    token_symbol = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    trx_hash = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    to_address = serializers.CharField(max_length=42, required=True, help_text='Ethereum address to withdraw funds to')
    
    # Use a string field for amount to avoid validation issues with large numbers
    amount = serializers.CharField(required=True, help_text='Amount in wei or decimal format')
    
    # Keep amount_wei as a read-only field
    amount_wei = serializers.CharField(read_only=True)

    class Meta:
        model = Withdrawal
        fields = [
            'id', 'user', 'agent', 'fund', 'amount', 'amount_wei', 'usd_value', 'token_symbol',
            'to_address', 'status', 'trx_hash', 'created_at'
        ]

    def validate(self, data):
        request = self.context.get('request')
        user = data.get('user') or (request.user if request else None)
        
        if not user:
            raise serializers.ValidationError("User must be authenticated")

        # Ensure the agent belongs to the user
        agent = data.get('agent')

        if agent and agent.user.privy_address != user.privy_address:
            raise serializers.ValidationError({"agent": "You don't have permission to access this agent"})
            
        # Ensure the fund belongs to the agent
        fund = data.get('fund')
        if fund and agent and fund.wallet.agent != agent:
            raise serializers.ValidationError({"fund": "This fund doesn't belong to the specified agent"})
            
        # Get token details
        token_address = fund.token_address
        token_symbol = fund.token_symbol
        decimals = get_token_decimals(token_address)
        
        # Process the amount input (which is a string)
        amount_str = data.get('amount')
        if not amount_str:
            raise serializers.ValidationError({"amount": "This field is required"})
            
        try:
            # Convert to Decimal for calculations
            amount_decimal = Decimal(amount_str)
            
            # Determine if this is wei or decimal format
            # If it has more than 18 digits or no decimal point, assume it's wei
            if '.' not in amount_str or len(amount_str.split('.')[0]) > 18:
                # It's wei format
                amount_wei = amount_decimal
                amount = amount_decimal / (10 ** decimals)
                logger.info(f"Interpreted {amount_str} as wei amount, converted to {amount} {token_symbol}")
            else:
                # It's decimal format
                amount = amount_decimal
                amount_wei = amount_decimal * (10 ** decimals)
                logger.info(f"Interpreted {amount_str} as decimal amount, converted to {amount_wei} wei")
                
            # Store both values in the validated data
            # Convert the original string input to a proper Decimal for the model
            data['amount'] = amount
            data['amount_wei'] = amount_wei
            
            # Ensure the amount is positive
            if amount <= 0:
                raise serializers.ValidationError({"amount": "Amount must be greater than zero"})
                
        except (ValueError, TypeError, ArithmeticError) as e:
            raise serializers.ValidationError({"amount": f"Invalid amount format: {str(e)}"})
            
        # Check for sufficient balance using RPC call
        wallet_address = fund.wallet.address
        
        # Get actual on-chain balance in wei
        actual_balance_wei = get_token_balance(wallet_address, token_address, True)
        
        logger.info(f"Actual on-chain balance for {token_symbol} (wei): {actual_balance_wei}")
        logger.info(f"Requested withdrawal amount (wei): {data['amount_wei']}")
            
        if data['amount_wei'] > actual_balance_wei:
            raise serializers.ValidationError({"amount": "Insufficient funds"})
        
        logger.info("Validation passed")
        return data
        
    def create(self, validated_data):
        import requests
        from django.conf import settings
        
        # Set token_symbol from the fund
        validated_data['token_symbol'] = validated_data['fund'].token_symbol
        validated_data['status'] = Withdrawal.StatusChoices.PENDING
        
        # Get token address from the fund
        token_address = validated_data['fund'].token_address
        
        # Create the withdrawal record in the database
        withdrawal = super().create(validated_data)
        
        try:
            # Get the wallet_id from the agent wallet
            agent_wallet = validated_data['fund'].wallet
            wallet_id = agent_wallet.wallet_id
            
            # If wallet_id is None or empty, log a warning and use the wallet's database ID as fallback
            if not wallet_id:
                logger.warning(f"Agent wallet {agent_wallet.id} has no wallet_id set, using database ID as fallback")
                wallet_id = str(agent_wallet.id)
            
            # Prepare data for the trade API call
            # Use the exact amount_wei for the API call
            trade_api_data = {
                'to': validated_data['to_address'],
                'amount': str(int(validated_data['amount_wei'])),  # Pass the exact wei amount as a string
                'tokenAddress': token_address,
                'walletId': wallet_id
            }
            
            # Log the API call details
            logger.info(f"Calling trade API for withdrawal {withdrawal.id} with data: {trade_api_data}")
            
            # Make the API call to the trade API
            # add header with x-api-key 
            trade_api_url = f"{settings.TRADE_API_BASE_URL}/api/agent/withdraw"
            response = requests.post(trade_api_url, json=trade_api_data, headers={'x-api-key': settings.API_TOKEN_KEY})
          
            
            # Check if the API call was successful
            if response.status_code == 200 or response.status_code == 201:
                logger.info(f"Trade API call successful for withdrawal {withdrawal.id}. Response: {response.text}")
                
                # Parse the response to get the transaction hash
                try:
                    response_data = response.json()
                    if response_data.get('success') and response_data.get('trxHash'):
                        # Update the withdrawal with the transaction hash
                        withdrawal.trx_hash = response_data['trxHash']
                        withdrawal.status = Withdrawal.StatusChoices.CONFIRMED
                        withdrawal.save()
                        logger.info(f"Updated withdrawal {withdrawal.id} with transaction hash: {withdrawal.trx_hash}")
                        
                        # Record the withdrawal in CapitalFlow for PNL calculation
                        try:
                            # Get the agent from the fund's wallet
                            agent = agent_wallet.agent
                            
                            # Create a CapitalFlow record for this withdrawal
                            from ..utils.common import fetch_token_price
                            from asgiref.sync import async_to_sync
                            
                            # Fetch the token price and calculate USD value
                            token_symbol = validated_data['token_symbol']
                            token_price = async_to_sync(fetch_token_price)(token_symbol)
                            
                            # Calculate USD value based on token price
                            if token_price is not None:
                                usd_value = float(validated_data['amount']) * token_price
                                withdrawal.usd_value = usd_value
                                withdrawal.save()
                                logger.info(f"Calculated USD value for {token_symbol} withdrawal: {usd_value} USD (amount: {validated_data['amount']}, price: {token_price})")
                            else:
                                logger.warning(f"Could not fetch price for {token_symbol}, using token amount as USD value during withdrawal")
                            
                            # capital_flow = CapitalFlow.objects.create(
                            #     agent=agent,
                            #     flow_type='withdrawal',
                            #     token_address=token_address,
                            #     token_symbol=token_symbol,
                            #     amount=validated_data['amount'],
                            #     usd_value=usd_value,
                            #     transaction_hash=response_data['trxHash'],
                            #     notes=f"Withdrawal to {validated_data['to_address']}"
                            # )
                            
                            # logger.info(f"Created CapitalFlow record {capital_flow.id} for withdrawal {withdrawal.id}")
                        except Exception as e:
                            logger.error(f"Error updating amount_usd for withdrawal {withdrawal.id}: {str(e)}")
                            # Don't fail the whole process if CapitalFlow creation fails
                            
                        # Update the portfolio snapshot after withdrawal
                        try:
                            from ..utils.common import create_portfolio_value_snapshot_for_agent
                            from asgiref.sync import async_to_sync
                            
                            # Create a new snapshot using the dedicated function
                            snapshot_result = async_to_sync(create_portfolio_value_snapshot_for_agent)(agent_wallet.agent.id)
                            
                            if snapshot_result.get('success', False):
                                logger.info(f"Created portfolio snapshot for agent {agent_wallet.agent.id} after withdrawal with value {snapshot_result.get('total_usd_value', 0)}")
                            else:
                                logger.warning(f"Failed to create portfolio snapshot for agent {agent_wallet.agent.id} after withdrawal: {snapshot_result.get('error', 'Unknown error')}")
                                
                        except Exception as e:
                            logger.error(f"Error creating portfolio snapshot for agent {agent_wallet.agent.id} after withdrawal: {str(e)}")
                            # Don't fail the whole process if snapshot update fails
                    else:
                        logger.warning(f"Trade API response missing success or trxHash fields: {response_data}")
                except Exception as e:
                    logger.error(f"Error parsing trade API response for withdrawal {withdrawal.id}: {str(e)}")
            else:
                logger.error(f"Trade API call failed for withdrawal {withdrawal.id}. Status: {response.status_code}, Response: {response.text}")
                # Update withdrawal status to FAILED if the API call fails
                withdrawal.status = Withdrawal.StatusChoices.FAILED
                withdrawal.save()
        except Exception as e:
            logger.error(f"Error calling trade API for withdrawal {withdrawal.id}: {str(e)}")
            # Update withdrawal status to FAILED if there's an exception
            withdrawal.status = Withdrawal.StatusChoices.FAILED
            withdrawal.save()
        
        return withdrawal
