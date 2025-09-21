import logging
import base64
from rest_framework import serializers
from django.core.files.base import ContentFile
import uuid
from ..models import Agent, AgentFunds, AgentTrade, AgentWallet, PortfolioSnapshot, RebalancingTrade
from ..data_access_layer import  AgentFundsDAL

logger = logging.getLogger(__name__)

class AgentSerializer(serializers.ModelSerializer):
    """Serializer for Agent model."""
    profile_image = serializers.CharField(required=False, write_only=True)
    profile_image_data = serializers.SerializerMethodField(read_only=True)
    wallet_address = serializers.SerializerMethodField(read_only=True)
    funds = serializers.SerializerMethodField(read_only=True)
    funds_usd_value = serializers.SerializerMethodField(read_only=True)
    pnl_24h = serializers.SerializerMethodField(read_only=True)
    _profile_image_data = None  # Store the base64 data temporarily

    class Meta:
        model = Agent
        fields = [
            'id', 'name', 'profile_image', 'profile_image_data', 'base_token', 'min_trade_size',
            'max_trade_size', 'min_stable_size', 'max_stable_size', 'whitelist_presets', 'trade_frequency',
            'strategy_description', 'detailed_instructions', 'llm_model', 'risk_profile',
            'trading_system', 'status', 'user', 'wallet_address', 'funds', 'funds_usd_value', 'pnl_24h'
        ]
        read_only_fields = ['id', 'user', 'profile_image_data', 'wallet_address', 'funds_usd_value', 'pnl_24h']
        
    def validate_trading_system(self, value):
        """Validate that the trading system is one of the allowed choices."""
        valid_choices = [choice[0] for choice in Agent.TradingSystemChoices.choices]
        if value not in valid_choices:
            raise serializers.ValidationError(
                f"Invalid trading system. Must be one of: {', '.join(valid_choices)}"
            )
        return value
        
    def validate_risk_profile(self, value):
        """Validate that the risk profile is one of the allowed choices."""
        if value is None:
            return value
            
        valid_choices = [choice[0] for choice in Agent.RiskProfileChoices.choices]
        if value not in valid_choices:
            raise serializers.ValidationError(
                f"Invalid risk profile. Must be one of: {', '.join(valid_choices)}"
            )
        return value
        
    def validate(self, data):
        """Validate the agent data as a whole."""
        # Check that min_trade_size is less than or equal to max_trade_size
        min_trade_size = data.get('min_trade_size')
        max_trade_size = data.get('max_trade_size')
        if min_trade_size and max_trade_size and min_trade_size > max_trade_size:
            raise serializers.ValidationError({
                'min_trade_size': 'Min trade size must be less than or equal to max trade size'
            })
            
        # Check that min_stable_size is less than or equal to max_stable_size
        min_stable_size = data.get('min_stable_size')
        max_stable_size = data.get('max_stable_size')
        if min_stable_size and max_stable_size and min_stable_size > max_stable_size:
            raise serializers.ValidationError({
                'min_stable_size': 'Min stable size must be less than or equal to max stable size'
            })
            
        # Check that min_stable_size is not negative
        if min_stable_size and min_stable_size < 0:
            raise serializers.ValidationError({
                'min_stable_size': 'Min stable size cannot be negative'
            })
            
        # Check that max_stable_size is not negative
        if max_stable_size and max_stable_size < 0:
            raise serializers.ValidationError({
                'max_stable_size': 'Max stable size cannot be negative'
            })
            
        # If risk_profile is provided, ensure it's a valid choice
        risk_profile = data.get('risk_profile')
        if risk_profile is not None:
            valid_choices = [choice[0] for choice in Agent.RiskProfileChoices.choices]
            if risk_profile not in valid_choices:
                raise serializers.ValidationError({
                    'risk_profile': f"Risk profile must be one of: {', '.join(valid_choices)}"
                })
                
        return data

    def get_wallet_address(self, obj):
        """Get the agent's wallet address."""
        try:
            return obj.wallet.address
        except AgentWallet.DoesNotExist:
            return None

    def get_profile_image_data(self, obj):
        """Get the base64 encoded image data."""
        # If we have stored base64 data (during creation/update), return it
        # if self._profile_image_data:
        #     return self._profile_image_data
            
        # # Otherwise, read from the file
        # if hasattr(obj, 'profile_image') and obj.profile_image:
        #     try:
        #         with obj.profile_image.open('rb') as image_file:
        #             return f"data:image/{obj.profile_image.name.split('.')[-1]};base64,{base64.b64encode(image_file.read()).decode()}"
        #     except Exception as e:
        #         logger.error(f"Error getting profile image: {str(e)}")
        #         return None
        return None

    def get_funds(self, obj):
        """Get the agent's funds."""
        try:
            wallet = obj.wallet
            funds = AgentFundsDAL.get_funds_for_wallet(wallet)
            return AgentFundsSerializer(funds, many=True).data
        except AgentWallet.DoesNotExist:
            return []
        except Exception as e:
            logger.error(f"Error getting agent funds: {str(e)}")
            return []
            
    def get_funds_usd_value(self, obj):
        """Get the total USD value of the agent's funds."""
        try:
            # Check if we have cached data in the context
            if self.context and 'funds_usd_values' in self.context and obj.id in self.context['funds_usd_values']:
                return self.context['funds_usd_values'][obj.id]
                
            # Otherwise, look for the latest portfolio snapshot
            latest_snapshot = PortfolioSnapshot.objects.filter(
                agent=obj
            ).order_by('-timestamp').first()
            
            if latest_snapshot:
                return {
                    'total_usd_value': float(latest_snapshot.total_usd_value),
                    'snapshot_timestamp': latest_snapshot.timestamp.isoformat()
                }
            return {'total_usd_value': 0, 'snapshot_timestamp': None}
        except Exception as e:
            logger.error(f"Error getting agent funds USD value: {str(e)}")
            return {'total_usd_value': 0, 'error': str(e)}
    
    def get_pnl_24h(self, obj):
        """Get the 24-hour PNL for the agent, but only in list view."""
        # Only return PNL data if the current view action is 'list'
        if self.context and 'view' in self.context and self.context['view'].action != 'list':
            return None
            
        # Check if we have cached data in the context
        if self.context and 'pnl_24h_values' in self.context and obj.id in self.context['pnl_24h_values']:
            return self.context['pnl_24h_values'][obj.id]
            
        # If no pre-calculated data is available, return zeros
        return {
            'absolute_pnl_usd': 0,
            'percentage_pnl': 0,
            'total_deposits': 0,
            'total_withdrawals': 0,
            'current_snapshot_timestamp': None
        }

    def validate_profile_image(self, value):
        """Validate and process base64 image data."""
        try:
            # Check if the string is base64 encoded
            if ';base64,' in value:
                format, imgstr = value.split(';base64,')
                ext = format.split('/')[-1]
                # Store the original base64 data for response
                self._profile_image_data = value
            else:
                imgstr = value
                ext = 'png'  # default extension
                # Store the formatted base64 data for response
                self._profile_image_data = f"data:image/png;base64,{value}"

            # Generate a unique filename
            filename = f"{uuid.uuid4()}.{ext}"
            
            # Convert base64 to file
            data = ContentFile(base64.b64decode(imgstr), name=filename)
            return data
        except Exception as e:
            raise serializers.ValidationError(f"Invalid image data: {str(e)}")

class AgentFundsSerializer(serializers.ModelSerializer):
    """Serializer for AgentFunds model."""
    class Meta:
        model = AgentFunds
        fields = ['id', 'token_name', 'token_symbol', 'token_address', 'amount', 'decimals']
        read_only_fields = ['id']


class AgentTradeSerializer(serializers.ModelSerializer):
    """Serializer for AgentTrade model."""
    class Meta:
        model = AgentTrade
        fields = ['id', 'from_token', 'to_token', 'amount_usd', 'transaction_hash', 'created_at']


class RebalancingTradeSerializer(serializers.ModelSerializer):
    """Serializer for RebalancingTrade model."""
    
    class Meta:
        model = RebalancingTrade
        fields = [
            'id', 'transaction_type', 'scenario_type', 'status',
            'pool_address', 'protocol', 'amount_wei', 'amount_formatted',
            'transaction_hash', 'block_number', 'executor_address',
            'gas_used', 'gas_cost_eth', 'allocation_index',
            'execution_timestamp', 'error_message', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']