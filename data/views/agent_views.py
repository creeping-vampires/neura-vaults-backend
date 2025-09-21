import logging
import ast
import asyncio
import requests
from rest_framework import viewsets, status, pagination, serializers
from rest_framework.validators import ValidationError
from rest_framework.decorators import api_view, action, permission_classes, parser_classes, authentication_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.conf import settings
from django.http import Http404
from django.core.exceptions import PermissionDenied
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer, OpenApiResponse, OpenApiExample, OpenApiParameter
from datetime import datetime, timedelta

from ..utils.rpc_utils import (
    fetch_all_token_balances, get_token_balance
)
from ..models import Agent, AgentTrade, Thought, AgentWallet, PortfolioSnapshot, User, RebalancingTrade
from ..serializers import AgentSerializer, AgentTradeSerializer, ThoughtSerializer, RebalancingTradeSerializer
from ..serializers.deposit_serializers import DepositSerializer
from ..authentication import PrivyAuthentication
from ..data_access_layer import AgentDAL, AgentWalletDAL, AgentFundsDAL, UserCreditsDAL, UserDAL
from ..utils.common import (
    generate_random_ethereum_address,
    calculate_agent_funds_usd_value,
    get_token_address
)
from rest_framework.parsers import JSONParser

from ..permissions import IsDefAIAdmin
from .utils import log_error
from django.utils import timezone
from ..utils.pnl_utils import AdjustedPnLCalculator


logger = logging.getLogger(__name__)

@extend_schema_view(
    create=extend_schema(
        summary="Create Agent",
        description="Create a new trading agent",
        request=inline_serializer(
            name='AgentCreateRequest',
            fields={
                'name': serializers.CharField(help_text="Name of the agent"),
                'profile_image': serializers.CharField(help_text="Base64 encoded image data (optional)"),
                'base_token': serializers.CharField(help_text="Base token for trading"),
                'min_trade_size': serializers.DecimalField(max_digits=20, decimal_places=8, help_text="Minimum trade size"),
                'max_trade_size': serializers.DecimalField(max_digits=20, decimal_places=8, help_text="Maximum trade size"),
                'whitelist_presets': serializers.CharField(help_text="List of whitelisted tokens"),
                'trade_frequency': serializers.IntegerField(help_text="Trade frequency in minutes"),
                'strategy_description': serializers.CharField(help_text="Description of the trading strategy"),
                'detailed_instructions': serializers.CharField(help_text="Detailed trading instructions"),
                'llm_model': serializers.CharField(help_text="LLM model to use"),
                'trading_system': serializers.CharField(help_text="Trading system to use")
            }
        ),
        responses={
            201: OpenApiResponse(
                description="Agent created successfully",
                examples=[
                    OpenApiExample(
                        "Agent Response",
                        value={
                            "id": 1,
                            "name": "ETH Trader Bot",
                            "profile_image_data": "data:image/png;base64,...",
                            "base_token": "ETH",
                            "min_trade_size": "0.1",
                            "max_trade_size": "1.0",
                            "whitelist_presets": "['USDT', 'USDC', 'DAI']",
                            "trade_frequency": 30,
                            "strategy_description": "Arbitrage trading between DEXes",
                            "detailed_instructions": "Monitor price differences between Uniswap and Sushiswap",
                            "llm_model": "gpt-4",
                            "trading_system": "arbitrage",
                            "user": "privy_1234...",
                            "wallet_address": "0x1234..."
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Invalid input data or insufficient credits"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        examples=[
            OpenApiExample(
                "Create Agent Example",
                value={
                    "name": "ETH Trader Bot",
                    "profile_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...",
                    "base_token": "ETH",
                    "min_trade_size": "0.1",
                    "max_trade_size": "1.0",
                    "whitelist_presets": "['USDT', 'USDC', 'DAI']",
                    "trade_frequency": 30,
                    "strategy_description": "Arbitrage trading between DEXes",
                    "detailed_instructions": "Monitor price differences between Uniswap and Sushiswap",
                    "llm_model": "gpt-4",
                    "trading_system": "arbitrage"
                },
                request_only=True
            )
        ],
        tags=["Agent"]
    ),
    retrieve=extend_schema(
        summary="Get Agent Details",
        description="Get details of a specific agent",
        responses={
            200: AgentSerializer,
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    ),
    list=extend_schema(
        summary="List Agents",
        description="Get a list of all agents for the authenticated user",
        responses={
            200: AgentSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    ),
    update=extend_schema(
        summary="Update Agent",
        description="Update an existing agent",
        responses={
            200: AgentSerializer,
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    ),
    partial_update=extend_schema(
        summary="Partially Update Agent",
        description="Update specific fields of an agent",
        responses={
            200: AgentSerializer,
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    ),
    destroy=extend_schema(
        summary="Delete Agent",
        description="Delete an agent",
        responses={
            204: OpenApiResponse(description="Agent deleted successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
)
class AgentViewSet(viewsets.ModelViewSet):
    """ViewSet for managing trading agents."""
    serializer_class = AgentSerializer
    authentication_classes = [PrivyAuthentication]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Get non-deleted agents for the authenticated user."""
        try:
            # Get agents for the authenticated user
            privy_address = self.request.user.privy_address
            if not privy_address:
                logger.warning("privy_address is empty")
                return Agent.objects.none()
                
            logger.info(f"Getting agents for user with privy_address: {privy_address}")
            agents = AgentDAL.get_agents_for_user(privy_address)
            logger.info(f"Found {agents.count()} agents for privy_address: {privy_address}")
            return agents
        except Exception as e:
            error_context = log_error(e, {
                'user': str(self.request.user),
                'user_attrs': dir(self.request.user),
                'endpoint': 'get_queryset'
            })
            logger.error(f"Error in get_queryset: {str(e)}")
            return Agent.objects.none()  # Return empty queryset instead of raising error

    def list(self, request, *args, **kwargs):
        """List agents with preloaded USD value and PNL data."""
        queryset = self.filter_queryset(self.get_queryset())

        # Prepare context with preloaded USD values and PNL data for all agents
        context = {'request': request}
        
        # Only preload if we have agents to avoid unnecessary calculations
        if queryset.exists():
            try:
                # Get the latest portfolio snapshots for all agents in the queryset
                from ..models import PortfolioSnapshot
                from django.utils import timezone
                from datetime import timedelta
                
                # Get agent IDs
                agent_ids = list(queryset.values_list('id', flat=True))
                
                # Get latest snapshots for all agents
                latest_snapshots = {}
                for snapshot in PortfolioSnapshot.objects.filter(agent__in=agent_ids).order_by('agent', '-timestamp'):
                    if snapshot.agent_id not in latest_snapshots:
                        latest_snapshots[snapshot.agent_id] = snapshot
                
                funds_usd_values = {}
                pnl_24h_values = {}
                
                for agent_id in agent_ids:
                    # USD value
                    if agent_id in latest_snapshots:
                        snapshot = latest_snapshots[agent_id]
                        funds_usd_values[agent_id] = {
                            'total_usd_value': float(snapshot.total_usd_value),
                            'snapshot_timestamp': snapshot.timestamp.isoformat()
                        }
                    else:
                        funds_usd_values[agent_id] = {'total_usd_value': 0, 'snapshot_timestamp': None}
                    
           
                    if agent_id in latest_snapshots:
                        latest = latest_snapshots[agent_id]
                        current_value = float(latest.total_usd_value)
                        adjusted_result = AdjustedPnLCalculator.calculate_adjusted_pnl(
                                    agent=queryset.get(id=agent_id),
                                    current_value=current_value,
                                )
                        pnl_24h_values[agent_id] = {
                                'absolute_pnl_usd': adjusted_result.get('absolute_pnl_usd', 0),
                                'percentage_pnl': adjusted_result.get('percentage_pnl', 0),
                                'total_deposits': adjusted_result.get('total_deposits', 0),
                                'total_withdrawals': adjusted_result.get('total_withdrawals', 0),
                                'current_snapshot_timestamp': latest.timestamp.isoformat()
                            }   

                    else:
                        pnl_24h_values[agent_id] = {
                            'absolute_pnl_usd': 0,
                            'percentage_pnl': 0,
                            'total_deposits': 0,
                            'total_withdrawals': 0,
                            'current_snapshot_timestamp': None
                        }
                
                # Add to context
                context['funds_usd_values'] = funds_usd_values
                context['pnl_24h_values'] = pnl_24h_values
                
            except Exception as e:
                logger.error(f"Error preloading USD values and PNL data: {str(e)}")
        
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        """Retrieve an agent with preloaded USD value and PNL data."""
        instance = self.get_object()
        
        # Prepare context with preloaded USD value and PNL data for this agent
        context = {'request': request}
        
        try:
            # Get the latest portfolio snapshot for this agent
            latest_snapshot = PortfolioSnapshot.objects.filter(agent=instance).order_by('-timestamp').first()
            
            if latest_snapshot:
                # USD value
                funds_usd_values = {
                    instance.id: {
                        'total_usd_value': float(latest_snapshot.total_usd_value),
                        'snapshot_timestamp': latest_snapshot.timestamp.isoformat()
                    }
                }
                
                # Calculate PNL using AdjustedPnLCalculator
                current_value = float(latest_snapshot.total_usd_value)
                adjusted_result = AdjustedPnLCalculator.calculate_adjusted_pnl(
                    agent=instance,
                    current_value=current_value,
                )
                
                pnl_24h_values = {
                    instance.id: {
                        'absolute_pnl_usd': adjusted_result.get('absolute_pnl_usd', 0),
                        'percentage_pnl': adjusted_result.get('percentage_pnl', 0),
                        'total_deposits': adjusted_result.get('total_deposits', 0),
                        'total_withdrawals': adjusted_result.get('total_withdrawals', 0),
                        'current_snapshot_timestamp': latest_snapshot.timestamp.isoformat()
                    }
                }
                
                # Use stored all-time PNL values from the snapshot if available
                if latest_snapshot.pnl_all_time_absolute is not None:
                    reference_snapshot = latest_snapshot.pnl_reference_snapshot_all_time
                    pnl_all_time_values = {
                        instance.id: {
                            'absolute_pnl_usd': float(latest_snapshot.pnl_all_time_absolute),
                            'percentage_pnl': float(latest_snapshot.pnl_all_time_percentage),
                            'current_snapshot_timestamp': latest_snapshot.timestamp.isoformat(),
                            'first_snapshot_timestamp': reference_snapshot.timestamp.isoformat() if reference_snapshot else None
                        }
                    }
                else:
                    # Fallback to old calculation method if PNL values are not stored
                    # Get the first snapshot for all-time PNL calculation
                    first_snapshot = PortfolioSnapshot.objects.filter(agent=instance).order_by('timestamp').first()
                    
                    # All-time PNL calculation
                    if first_snapshot and first_snapshot.id != latest_snapshot.id:
                        current_value = float(latest_snapshot.total_usd_value)
                        initial_value = float(first_snapshot.total_usd_value)
                        absolute_pnl = current_value - initial_value
                        percentage_pnl = (absolute_pnl / initial_value) * 100 if initial_value > 0 else 0
                        
                        pnl_all_time_values = {
                            instance.id: {
                                'absolute_pnl_usd': absolute_pnl,
                                'percentage_pnl': percentage_pnl,
                                'current_snapshot_timestamp': latest_snapshot.timestamp.isoformat(),
                                'first_snapshot_timestamp': first_snapshot.timestamp.isoformat()
                            }
                        }
                    else:
                        pnl_all_time_values = {
                            instance.id: {
                                'absolute_pnl_usd': 0,
                                'percentage_pnl': 0,
                                'current_snapshot_timestamp': latest_snapshot.timestamp.isoformat() if latest_snapshot else None,
                                'first_snapshot_timestamp': first_snapshot.timestamp.isoformat() if first_snapshot else None
                            }
                        }
                
                # Add to context
                context['funds_usd_values'] = funds_usd_values
                context['pnl_24h_values'] = pnl_24h_values
                context['pnl_all_time_values'] = pnl_all_time_values
            
        except Exception as e:
            logger.error(f"Error preloading USD value and PNL data: {str(e)}")
        
        serializer = self.get_serializer(instance, context=context)
        return Response(serializer.data)

    def get_object(self):
        """Get a single agent, ensuring it's not deleted and belongs to the current user."""
        try:
            agent_id = self.kwargs['pk']
            agent = AgentDAL.get_agent_by_id(agent_id)
            
            # Check if agent belongs to current user
            if agent.user.privy_address != self.request.user.privy_address:
                raise PermissionDenied("You don't have permission to access this agent")
                
            return agent
        except Agent.DoesNotExist:
            raise Http404("Agent not found")

    def _setup_agent_tokens(self, agent, wallet):
        """Set up tokens for an agent's wallet.
        
        Args:
            agent: The agent instance
            wallet: The agent's wallet instance
        """
        # Get token information from tokens.csv
        token_info = self._get_token_info()
        
        # Add HYPE token 
        hype_address = get_token_address('HYPE')
        if hype_address:
            hype_decimals = token_info.get('HYPE', {}).get('decimals', 18)
            AgentFundsDAL.create_fund(
                wallet=wallet,
                token_name='HYPE',
                token_symbol='HYPE',
                token_address=hype_address,
                amount=0,
                decimals=hype_decimals
            )
            logger.info(f"Added HYPE token to agent {agent.id}")
        
        # Add tokens from whitelist_presets
        try:
            # Handle the format "['uSOL','uFART']" by removing quotes and using ast.literal_eval
            whitelist_presets = agent.whitelist_presets.replace("'", '"') if agent.whitelist_presets else '[]'
            whitelist_tokens = ast.literal_eval(whitelist_presets)
            
            for token_symbol in whitelist_tokens:
                token_address = get_token_address(token_symbol)
                if token_address:
                    token_decimals = token_info.get(token_symbol, {}).get('decimals', 18)
                    AgentFundsDAL.create_fund(
                        wallet=wallet,
                        token_name=token_symbol,  # Using symbol as name for simplicity
                        token_symbol=token_symbol,
                        token_address=token_address,
                        amount=0,
                        decimals=token_decimals
                    )
                    logger.info(f"Added {token_symbol} token to agent {agent.id} with 0 amount and {token_decimals} decimals")
                else:
                    logger.warning(f"Token address not found for {token_symbol}")
        except (ValueError, SyntaxError) as e:
            logger.error(f"Error parsing whitelist_presets for agent {agent.id}: {str(e)}")

            
    def _get_token_info(self):
        """Read token information from tokens.csv file.
        
        Returns:
            dict: Dictionary mapping token symbols to their information (address, decimals)
        """
        token_info = {}
        try:
            import csv
            import os
            from django.conf import settings
            
            tokens_csv_path = os.path.join(settings.BASE_DIR, 'tokens.csv')
            
            if not os.path.exists(tokens_csv_path):
                logger.error(f"tokens.csv file not found at {tokens_csv_path}")
                return token_info
                
            with open(tokens_csv_path, 'r') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    token_symbol = row.get('Token')
                    if token_symbol:
                        token_info[token_symbol] = {
                            'address': row.get('Contract Address'),
                            'decimals': int(row.get('decimals', 18))
                        }
        except Exception as e:
            logger.error(f"Error reading tokens.csv: {str(e)}")
            
        return token_info
        
    def perform_create(self, serializer):
        """Create a new agent for the authenticated user."""
        try:
            logger.info(f"Creating agent for user: {self.request.user}")
            privy_address = self.request.user.privy_address
            logger.info(f"Found privy_address: {privy_address}")
            
            user = UserDAL.get_user_by_privy_address(privy_address)
            if not user.is_active:
                logger.warning(f"User not active: {privy_address}")
                raise ValidationError("User account is not active")
            
            # Check if user has sufficient credits before creating agent
            if not UserCreditsDAL.has_sufficient_credits(user):
                logger.warning(f"Insufficient credits for user: {privy_address}")
                raise ValidationError("Insufficient credits to create agent")
            
            # Create the agent
            agent = serializer.save(user=user, version=2)
            logger.info(f"Created agent: {agent.id}")
            
            # Deduct credits after successful agent creation
            try:
                UserCreditsDAL.deduct_credits(user)
                logger.info(f"Deducted 1 credit from user: {user.privy_address}, agent: {agent.id}")
            except Exception as e:
                # If credit deduction fails, delete the agent and raise error
                logger.error(f"Failed to deduct credits, deleting agent: {agent.id}, error: {str(e)}")
                agent.delete()
                raise ValidationError(f"Credit deduction failed: {str(e)}")
            
            # Check if we're in development mode
            if settings.ENVIRONMENT == 'development':
                # Generate a random Ethereum address for development
                logger.info(f"Development mode: Generating random Ethereum address for agent: {agent.id}")
                wallet_address = generate_random_ethereum_address()
                
                # Create the agent wallet with the random address
                AgentWalletDAL.create_wallet(
                    agent=agent,
                    address=wallet_address,
                    wallet_id="test_wallet_id"
                )
                logger.info(f"Development mode: Agent wallet created with address: {wallet_address}")
                
                # Set up tokens for the agent's wallet
                wallet = AgentWalletDAL.get_wallet_for_agent(agent)
                self._setup_agent_tokens(agent, wallet)
                
                # No need to invalidate caches as we're not caching agent APIs anymore
                
                return agent
            else:
                # Production mode: Call the trade API to create a wallet
                try:
                    logger.info(f"Production mode: Creating wallet via trade API for agent: {agent.id}")
                    response = requests.post(
                        f"{settings.TRADE_API_BASE_URL}/api/agent/wallet",
                        headers={
                            "Authorization": self.request.META.get('HTTP_AUTHORIZATION', '')
                        }
                    )
                    response.raise_for_status()
                    wallet_data = response.json()
                    logger.info(f"Wallet created successfully for agent: {agent.id}")
                    
                    # Create the agent wallet
                    AgentWalletDAL.create_wallet(
                        agent=agent,
                        address=wallet_data['data']['wallet']['address'],
                        wallet_id=wallet_data['data']['wallet']['id']
                    )
                    logger.info(f"Agent wallet record created for agent: {agent.id}")
                    
                    # Set up tokens for the agent's wallet
                    wallet = AgentWalletDAL.get_wallet_for_agent(agent)
                    self._setup_agent_tokens(agent, wallet)
                    
                    # No need to invalidate caches as we're not caching agent APIs anymore
                    
                    return agent
                except requests.RequestException as e:
                    error_context = log_error(e, {
                        'agent_id': agent.id,
                        'endpoint': 'perform_create_wallet',
                        'response': getattr(e.response, 'text', None) if hasattr(e, 'response') else None
                    })
                    # Delete the agent if wallet creation fails
                    AgentDAL.delete_agent(agent)
                    logger.error(f"Deleted agent {agent.id} due to wallet creation failure")
                    raise ValidationError(f"Failed to create agent wallet: {str(e)}")
            
        except User.DoesNotExist:
            error_msg = f"User not found for privy_address: {privy_address}"
            logger.error(error_msg)
            raise ValidationError(error_msg)
        except ValueError as e:
            # This will catch the InsufficientCreditsError from AgentDAL.create_agent
            logger.warning(f"Credit error: {str(e)}")
            raise ValidationError(str(e))
        except Exception as e:
            error_context = log_error(e, {
                'user': str(self.request.user),
                'privy_address': getattr(self.request.user, 'privy_address', None),
                'endpoint': 'perform_create'
            })
            raise ValidationError(f"Error creating agent: {str(e)}")
    
    def perform_update(self, serializer):
        """Update an agent, ensuring it's not deleted."""
        try:
            # Get the agent
            agent = self.get_object()
            
            # Check if whitelist_presets is being updated
            if 'whitelist_presets' in serializer.validated_data:
                old_whitelist = ast.literal_eval(agent.whitelist_presets) if agent.whitelist_presets else []
                new_whitelist = ast.literal_eval(serializer.validated_data['whitelist_presets']) if serializer.validated_data['whitelist_presets'] else []
                
                # If whitelist has changed, update the agent's funds
                if set(old_whitelist) != set(new_whitelist):
                    logger.info(f"Updating whitelist presets for agent {agent.id}: {old_whitelist} -> {new_whitelist}")
                    
                    # Update the agent first to save the new whitelist_presets
                    updated_agent = serializer.save()
                    
                    # Update the agent's funds based on the new whitelist
                    AgentFundsDAL.update_agent_preset_tokens(updated_agent, new_whitelist)
                    
                    logger.info(f"Updated agent {agent.id} funds with new whitelist presets")
                    return
            
            # If whitelist_presets is not being updated or hasn't changed, just save normally
            serializer.save()
            
            logger.info(f"Updated agent {agent.id}")
        except Exception as e:
            error_context = log_error(e, {
                'user': str(self.request.user),
                'endpoint': 'perform_update'
            })
            raise ValidationError(f"Error updating agent: {str(e)}")
    
    def destroy(self, request, *args, **kwargs):
        """Soft delete the agent if its funds USD value is less than 0.1."""
        try:
            # Get the agent instance
            instance = self.get_object()
            agent_id = instance.id
            logger.info(f"Checking funds before deleting agent: {agent_id}")
            
            # Use sync_to_async to run the async function in a synchronous context
            from asgiref.sync import sync_to_async
            import asyncio
            
            # Get the agent's funds USD value
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            funds_value = loop.run_until_complete(calculate_agent_funds_usd_value(instance))
            loop.close()
            
            total_usd_value = funds_value.get('total_usd_value', 0)
            
            # Only allow deletion if funds value is less than 0.1 USD
            if total_usd_value >= 0.1:
                logger.warning(f"Cannot delete agent {agent_id}: funds value ({total_usd_value} USD) is >= 0.1 USD")
                return Response(
                    {"detail": f"Your agent has a balance of {total_usd_value} USD. Please withdraw your funds before deleting the agent."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            logger.info(f"Agent {agent_id} funds value ({total_usd_value} USD) is < 0.1 USD, proceeding with deletion")
            AgentDAL.delete_agent(instance)
            
            # No need to invalidate caches as we're not caching agent APIs anymore
            
            logger.info(f"Successfully soft deleted agent: {agent_id}")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': kwargs.get('pk'),
                'endpoint': 'destroy'
            })
            return Response(
                {"detail": f"Error deleting agent: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


    @extend_schema(
        summary="Get Agent Transactions",
        description="Get all transactions for a specific agent with pagination",
        parameters=[
            OpenApiParameter(
                name='page',
                description='Page number for pagination',
                required=False,
                type=int,
                location=OpenApiParameter.QUERY
            ),
            OpenApiParameter(
                name='page_size',
                description='Number of items per page (default: 10, max: 100)',
                required=False,
                type=int,
                location=OpenApiParameter.QUERY
            )
        ],
        responses={
            200: inline_serializer(
                name='PaginatedAgentTradeResponse',
                fields={
                    'count': serializers.IntegerField(help_text="Total number of trades"),
                    'next': serializers.URLField(help_text="URL to the next page", allow_null=True),
                    'previous': serializers.URLField(help_text="URL to the previous page", allow_null=True),
                    'results': AgentTradeSerializer(many=True)
                }
            ),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - User not whitelisted"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        """Get all transactions for a specific agent by agent ID with pagination.
        
        Returns the most recent trades first, with pagination support.
        Default page size is 10 items per page.
        """
        try:
            logger.info(f"Getting transactions for agent: {pk}")
            
            # Get pagination parameters
            page = request.query_params.get('page', 1)
            try:
                page = int(page)
                if page < 1:
                    page = 1
            except (ValueError, TypeError):
                page = 1
                
            page_size = request.query_params.get('page_size', 10)
            try:
                page_size = int(page_size)
                if page_size < 1:
                    page_size = 10
                elif page_size > 100:  # Set a reasonable upper limit
                    page_size = 100
            except (ValueError, TypeError):
                page_size = 10
            
            # Directly fetch trades by agent ID, ordered by most recent first
            trades = AgentTrade.objects.filter(agent_id=pk).order_by('-created_at')
            total_count = trades.count()
            logger.info(f"Found {total_count} trades for agent: {pk}")
            
            # Calculate pagination values
            start_index = (page - 1) * page_size
            end_index = start_index + page_size
            paginated_trades = trades[start_index:end_index]
            
            # Prepare pagination metadata
            base_url = request.build_absolute_uri().split('?')[0]
            next_page = None
            previous_page = None
            
            if end_index < total_count:
                next_page = f"{base_url}?page={page + 1}&page_size={page_size}"
            
            if page > 1:
                previous_page = f"{base_url}?page={page - 1}&page_size={page_size}"
            
            # Serialize the paginated trades
            serializer = AgentTradeSerializer(paginated_trades, many=True)
            
            # Return paginated response
            response_data = {
                'count': total_count,
                'next': next_page,
                'previous': previous_page,
                'results': serializer.data
            }
            
            return Response(response_data, status=status.HTTP_200_OK)
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': pk,
                'endpoint': 'transactions',
                'page': request.query_params.get('page'),
                'page_size': request.query_params.get('page_size')
            })
            return Response(
                {"error": "Error retrieving transactions"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    
    @extend_schema(
        summary="Restore Deleted Agent",
        description="Restore a previously deleted agent",
        responses={
            200: AgentSerializer,
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - User not whitelisted"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['post'])
    def restore(self, request, pk=None):
        """Restore a soft-deleted agent."""
        try:
            logger.info(f"Attempting to restore agent: {pk}")
            agent = AgentDAL.restore_agent(pk)
            logger.info(f"Successfully restored agent: {pk}")
            
            serializer = self.get_serializer(agent)
            return Response(serializer.data)
        except ValueError as e:
            logger.warning(f"Restore error: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Http404:
            logger.warning(f"Agent not found: {pk}")
            return Response(
                {"error": "Agent not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': pk,
                'endpoint': 'restore'
            })
            return Response(
                {"error": "Error restoring agent"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="List Deleted Agents",
        description="Get a list of all deleted agents for the authenticated user",
        responses={
            200: AgentSerializer(many=True),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - User not whitelisted"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=False, methods=['get'])
    def deleted(self, request):
        """Get all deleted agents for the authenticated user."""
        try:
            logger.info(f"Getting deleted agents for user: {request.user}")
            privy_address = request.user.privy_address
            logger.info(f"Found privy_address: {privy_address}")
            
            agents = AgentDAL.get_deleted_agents_for_user(privy_address)
            logger.info(f"Found {agents.count()} deleted agents for privy_address: {privy_address}")
            
            serializer = self.get_serializer(agents, many=True)
            return Response(serializer.data)
        except Exception as e:
            error_context = log_error(e, {
                'user': str(request.user),
                'endpoint': 'deleted'
            })
            return Response(
                {"error": "Error retrieving deleted agents"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="Activate Agent",
        description="Verify an agent by ID and set its status from idle to running",
        request=None,  # No request body required
        responses={
            200: OpenApiResponse(
                description="Agent activated successfully",
                examples=[
                    OpenApiExample(
                        "Activation Response",
                        value={
                            "id": 1,
                            "name": "ETH Trader Bot",
                            "status": "running",
                            "message": "Agent activated successfully"
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Agent is not in idle state"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['patch'])
    def activate(self, request, pk=None):
        """Verify an agent by ID and set its status from idle to running."""
        try:
            logger.info(f"Activating agent: {pk}")
            agent = self.get_object()
            
            # Check if agent is in idle state
            if agent.status != Agent.StatusChoices.IDLE:
                logger.warning(f"Cannot activate agent {pk} because it is not in idle state. Current status: {agent.status}")
                return Response(
                    {"error": f"Agent is not in idle state. Current status: {agent.status}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            # Check if agent has a wallet
            try:
                wallet = agent.wallet
                wallet_address = wallet.address
            except AgentWallet.DoesNotExist:
                logger.warning(f"Cannot activate agent {pk} because it has no associated wallet")
                return Response(
                    {"error": "Agent has no associated wallet"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # HWTR token address
            hwtr_token_address = "0x5804Bf271D9e691611EEA1267B24C1f3D0723639"
            feusd_token_address = "0x02c6a2fA58cC01A18B8D9E00eA48d65E4dF26c70"
            
            # Check HYPE (native token) balance
            hype_balance = get_token_balance(wallet_address, "0x5555555555555555555555555555555555555555", False)
            # Check HWTR token balance
            hwtr_balance = get_token_balance(wallet_address, hwtr_token_address, False)
            # Check feUSD token balance
            feusd_balance = get_token_balance(wallet_address, feusd_token_address, False)

            hwtr_balance_wei = get_token_balance(wallet_address, hwtr_token_address, True)

            # Minimum required balances (1 token each)
            min_hype_required = settings.MIN_HYPE_REQUIRED
            min_hwtr_required = settings.MIN_HWTR_REQUIRED
            min_feusd_required = settings.MIN_FEUSD_REQUIRED
            
            logger.info(f"Agent {pk} wallet {wallet_address} balances - HYPE: {hype_balance}, HWTR: {hwtr_balance}")

            
            # Check if balances meet requirements
            if float(hype_balance) < float(min_hype_required):
                error_msg = f"Insufficient funds in agent wallet. " \
                           f"Required: {settings.MIN_HYPE_REQUIRED} HYPE. " \
                           f"Available: {hype_balance} HYPE "
                logger.warning(f"Cannot activate agent {pk}: {error_msg}")
                return Response(
                    {"error": error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if float(hwtr_balance) < float(min_hwtr_required):
                error_msg = f"Insufficient funds in agent wallet. " \
                           f"Required: {settings.MIN_HWTR_REQUIRED} HWTR. " \
                           f"Available: {hwtr_balance} HWTR "
                logger.warning(f"Cannot activate agent {pk}: {error_msg}")
                return Response(
                    {"error": error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if float(feusd_balance) < float(min_feusd_required):
                error_msg = f"Insufficient funds in agent wallet. " \
                           f"Required: {settings.MIN_FEUSD_REQUIRED} feUSD. " \
                           f"Available: {feusd_balance} feUSD "
                logger.warning(f"Cannot activate agent {pk}: {error_msg}")
                return Response(
                    {"error": error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # --- Fee deduction to fee wallet using withdrawal-like logic ---
            # Skip fee deduction in development environment
            if settings.ENVIRONMENT != 'development':
                import requests
                try:
                    fee_wallet_address = settings.FEE_WALLET_ADDRESS
                    if not fee_wallet_address:
                        logger.error("FEE_WALLET_ADDRESS not set in environment.")
                        return Response({"error": "Fee wallet address not configured."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

                    # Use the same withdrawal logic for HWTR token transfer
                    wallet_id = wallet.wallet_id if wallet.wallet_id else str(wallet.id)
                    token_address = hwtr_token_address
                    transfer_api_url = f"{settings.TRADE_API_BASE_URL}/api/agent/withdraw"
                    transfer_data = {
                        "to": fee_wallet_address,
                        "amount": str(int(hwtr_balance_wei)),
                        "tokenAddress": token_address,
                        "walletId": wallet_id
                    }
                    headers = {"x-api-key": settings.API_TOKEN_KEY}
                    logger.info(f"Deducting HWTR activation fee using withdraw API: {transfer_data}")
                    response = requests.post(transfer_api_url, json=transfer_data, headers=headers)
                    if response.status_code not in [200, 201]:
                        logger.error(f"Withdraw API call failed: {response.status_code}, {response.text}")
                        return Response({"error": "Failed to deduct activation fee."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    resp_json = response.json()
                    trx_hash = resp_json.get("trxHash")
                    if not (resp_json.get("success") and trx_hash):
                        logger.error(f"Withdraw API did not return success or trxHash: {resp_json}")
                        return Response({"error": "Failed to deduct activation fee (no hash)."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                    logger.info(f"Activation fee deducted, trx hash: {trx_hash}")
                except Exception as e:
                    logger.error(f"Exception during activation fee deduction: {str(e)}")
                    return Response({"error": "Exception during activation fee deduction."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                logger.info("Development environment detected: Skipping fee deduction")

            # --- Only now activate the agent ---
            agent.status = Agent.StatusChoices.RUNNING
            agent.save()
            logger.info(f"Successfully activated agent: {pk}")
            
            return Response({
                "id": agent.id,
                "name": agent.name,
                "status": agent.status,
                "message": "Agent activated successfully"
            }, status=status.HTTP_200_OK)
        except Http404:
            logger.warning(f"Agent not found: {pk}")
            return Response(
                {"error": "Agent not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': pk,
                'endpoint': 'activate'
            })
            return Response(
                {"error": "Error activating agent"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="Deactivate Agent",
        description="Stop an agent by changing its status from running to paused",
        request=None,  # No request body required
        responses={
            200: OpenApiResponse(
                description="Agent deactivated successfully",
                examples=[
                    OpenApiExample(
                        "Deactivation Response",
                        value={
                            "id": 1,
                            "name": "ETH Trader Bot",
                            "status": "paused",
                            "message": "Agent deactivated successfully"
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Agent is not in running state"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['patch'])
    def deactivate(self, request, pk=None):
        """Stop an agent by changing its status from running to paused."""
        try:
            logger.info(f"Deactivating agent: {pk}")
            agent = self.get_object()
            
            # Check if agent is in running state
            if agent.status != Agent.StatusChoices.RUNNING:
                logger.warning(f"Cannot deactivate agent {pk} because it is not in running state. Current status: {agent.status}")
                return Response(
                    {"error": f"Agent is not in running state. Current status: {agent.status}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            # Update agent status
            agent.status = Agent.StatusChoices.PAUSED
            agent.save()
            logger.info(f"Successfully deactivated agent: {pk}")
            
            return Response({
                "id": agent.id,
                "name": agent.name,
                "status": agent.status,
                "message": "Agent deactivated successfully"
            }, status=status.HTTP_200_OK)
        except Http404:
            logger.warning(f"Agent not found: {pk}")
            return Response(
                {"error": "Agent not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': pk,
                'endpoint': 'deactivate'
            })
            return Response(
                {"error": "Error deactivating agent"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="Resume Agent",
        description="Resume a paused agent by changing its status from paused to running",
        request=None,  # No request body required
        responses={
            200: OpenApiResponse(
                description="Agent resumed successfully",
                examples=[
                    OpenApiExample(
                        "Resume Response",
                        value={
                            "id": 1,
                            "name": "ETH Trader Bot",
                            "status": "running",
                            "message": "Agent resumed successfully"
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description="Bad request - Agent is not in paused state"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['patch'])
    def resume(self, request, pk=None):
        """Resume a paused agent by changing its status from paused to running."""
        try:
            logger.info(f"Resuming agent: {pk}")
            agent = self.get_object()
            
            # Check if agent is in paused state
            if agent.status != Agent.StatusChoices.PAUSED:
                logger.warning(f"Cannot resume agent {pk} because it is not in paused state. Current status: {agent.status}")
                return Response(
                    {"error": f"Agent is not in paused state. Current status: {agent.status}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            # Update agent status
            agent.status = Agent.StatusChoices.RUNNING
            agent.save()
            logger.info(f"Successfully resumed agent: {pk}")
            
            return Response({
                "id": agent.id,
                "name": agent.name,
                "status": agent.status,
                "message": "Agent resumed successfully"
            }, status=status.HTTP_200_OK)
        except Http404:
            logger.warning(f"Agent not found: {pk}")
            return Response(
                {"error": "Agent not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': pk,
                'endpoint': 'resume'
            })
            return Response(
                {"error": "Error resuming agent"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @extend_schema(
        summary="Get Agent Funds USD Value",
        description="Get the total USD value of all tokens in an agent's wallet",
        responses={
            200: OpenApiResponse(
                description="Agent funds USD value retrieved successfully",
                examples=[
                    OpenApiExample(
                        "Funds USD Value Response",
                        value={
                            "total_usd_value": 123.45,
                            "tokens": [
                                {"symbol": "ETH", "balance": "0.5", "usd_value": 100.0},
                                {"symbol": "USDC", "balance": "23.45", "usd_value": 23.45}
                            ]
                        }
                    )
                ]
            ),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['get'])
    async def funds_usd_value(self, request, pk=None):
        """Get the total USD value of all tokens in an agent's wallet."""
        try:
            agent = self.get_object()
            logger.info(f"Getting funds USD value for agent: {agent.id}")
            
            # Calculate the total USD value of the agent's funds
            result = await calculate_agent_funds_usd_value(agent)
            logger.info(f"Successfully retrieved funds USD value for agent: {agent.id}")
            
            return Response(result)
        except Exception as e:
            error_context = log_error(e, {
                'agent_id': pk,
                'endpoint': 'funds_usd_value'
            })
            return Response({"detail": f"Error getting agent funds USD value: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    
    # @extend_schema(
    #     summary="Get Agent 24h PNL",
    #     description="Get the 24-hour profit and loss (PNL) for an agent",
    #     responses={
    #         200: OpenApiResponse(
    #             description="Agent 24h PNL retrieved successfully",
    #             examples=[
    #                 OpenApiExample(
    #                     "24h PNL Response",
    #                     value={
    #                         "pnl_usd": 12.34,
    #                         "pnl_percentage": 5.67
    #                     }
    #                 )
    #             ]
    #         ),
    #         401: OpenApiResponse(description="Unauthorized - Authentication required"),
    #         404: OpenApiResponse(description="Not found - Agent not found"),
    #         500: OpenApiResponse(description="Internal server error")
    #     },
    #     tags=["Agent"]
    # )
    # @action(detail=True, methods=['get'])
    # async def pnl_24h(self, request, pk=None):
    #     """Get the 24-hour profit and loss (PNL) for an agent."""
    #     try:
    #         agent = self.get_object()
    #         result = await calculate_agent_24h_pnl(agent)
    #         return Response(result, status=200)
    #     except Exception as e:
    #         error_context = log_error(e, {
    #             'agent_id': pk,
    #             'endpoint': 'pnl_24h'
    #         })
    #         return Response({"detail": f"Error getting agent 24h PNL: {str(e)}"}, status=500)
    
    @extend_schema(
        summary="Get Agent Thoughts",
        description="Get the thoughts for an agent with pagination",
        parameters=[
            OpenApiParameter(name='page', description='Page number', required=False, type=int),
            OpenApiParameter(name='page_size', description='Number of results per page', required=False, type=int),
            OpenApiParameter(name='agent_role', description='Filter by agent role', required=False, type=str),
        ],
        responses={
            200: OpenApiResponse(description="Agent thoughts retrieved successfully"),
            401: OpenApiResponse(description="Unauthorized - Authentication required"),
            403: OpenApiResponse(description="Forbidden - You do not have permission to view this agent's thoughts"),
            404: OpenApiResponse(description="Not found - Agent not found"),
            500: OpenApiResponse(description="Internal server error")
        },
        tags=["Agent"]
    )
    @action(detail=True, methods=['get'])
    def thoughts(self, request, pk=None):
        """Get the thoughts for an agent with pagination."""
        try:
            # Get the agent - this already filters by user through get_queryset()
            # so we don't need an additional ownership check
            agent = self.get_object()
            
            # Log the request for debugging
            logger.info(f"Fetching thoughts for agent {agent.id} requested by user {request.user.privy_address}")
            
            # Note: The ModelViewSet's get_object() method already filters by the queryset
            # from get_queryset(), which filters agents by the current user.
            # This means only the agent owner can access this endpoint.
            
            # Get query parameters
            page_size = request.query_params.get('page_size', 10)
            agent_role = request.query_params.get('agent_role', None)
            
            # Filter thoughts by agent and optionally by role
            queryset = Thought.objects.filter(agent=agent)
            if agent_role:
                queryset = queryset.filter(agent_role=agent_role)
                
            # Order by creation date, newest first
            queryset = queryset.order_by('-createdAt')
            
            # Set up pagination
            paginator = pagination.PageNumberPagination()
            paginator.page_size = int(page_size)
            result_page = paginator.paginate_queryset(queryset, request)
            
            # Serialize the results
            serializer = ThoughtSerializer(result_page, many=True)
            
            # Return paginated response
            return paginator.get_paginated_response(serializer.data)
            
        except Agent.DoesNotExist:
            return Response({"detail": "Agent not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error getting agent thoughts: {str(e)}")
            return Response({"detail": f"Error getting agent thoughts: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


    @extend_schema(
        summary="Record a deposit",
        description="Record a deposit for an agent by verifying the transaction hash on-chain",
        request=DepositSerializer,
        responses={
            status.HTTP_201_CREATED: inline_serializer(
                name='DepositResponse',
                fields={
                    'id': serializers.IntegerField(),
                    'agent_id': serializers.IntegerField(),
                    'token_symbol': serializers.CharField(),
                    'amount': serializers.CharField(),
                    'usd_value': serializers.CharField(),
                    'transaction_hash': serializers.CharField(),
                    'timestamp': serializers.DateTimeField(),
                    'notes': serializers.CharField(),
                }
            ),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(description="Invalid data or transaction verification failed"),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(description="Agent not found"),
            status.HTTP_403_FORBIDDEN: OpenApiResponse(description="Not authorized to access this agent"),
        },
        examples=[
            OpenApiExample(
                name="Record Deposit Example",
                value={
                    "agent_id": 1,
                    "transaction_hash": "0x1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                    "token_address": "0x1234567890abcdef1234567890abcdef12345678",
                    "token_symbol": "USDC",
                    "notes": "Initial deposit"
                },
                request_only=True,
            ),
        ],
    )
    @action(detail=False, methods=['post'], url_path='record-deposit')
    def record_deposit(self, request):
        """
        Record a deposit for an agent by verifying the transaction hash on-chain.
        
        This endpoint:
        1. Validates the transaction hash on-chain
        2. Verifies the token transfer to the agent's wallet
        3. Records the deposit in the CapitalFlow model
        """
        try:
            # Create serializer with request context
            serializer = DepositSerializer(data=request.data, context={'request': request})
            
            # Validate data (this will also verify the transaction on-chain)
            if serializer.is_valid():
                # Create the deposit record (handled in serializer.create())
                result = serializer.save()
                
                logger.info(f"Deposit recorded successfully for agent {result['agent_id']}, "
                           f"amount: {result['amount']} {result['token_symbol']}, "
                           f"transaction: {result['transaction_hash']}")
                
                # do not create snapshot if deposited token is HWTR
                if result['token_symbol'] == 'HWTR':
                    return Response(result, status=status.HTTP_201_CREATED)

                # Create portfolio snapshot here after successful deposit
                try:
                    from ..utils.common import create_portfolio_value_snapshot_for_agent
                    from asgiref.sync import async_to_sync
                    
                    # Create a new snapshot using the dedicated function
                    snapshot_result = async_to_sync(create_portfolio_value_snapshot_for_agent)(result['agent_id'])
                    
                    if snapshot_result.get('success', False):
                        logger.info(f"Created portfolio snapshot for agent {result['agent_id']} after deposit with value {snapshot_result.get('total_usd_value', 0)}")
                    else:
                        logger.warning(f"Failed to create portfolio snapshot for agent {result['agent_id']} after deposit: {snapshot_result.get('error', 'Unknown error')}")
                        
                except Exception as e:
                    logger.error(f"Error creating portfolio snapshot for agent {result['agent_id']} after deposit: {str(e)}")
                
                return Response(result, status=status.HTTP_201_CREATED)
            else:
                logger.warning(f"Invalid deposit data: {serializer.errors}")
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            log_error(e, "Error recording deposit")
            return Response(
                {"detail": f"Error recording deposit: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@extend_schema(
    summary="Admin Deactivate Agents",
    description="Admin endpoint to deactivate multiple agents by their IDs, bypassing normal user permission checks",
    request=inline_serializer(
        name='AdminDeactivateAgentsRequest',
        fields={
            'agent_ids': serializers.ListField(child=serializers.IntegerField(), help_text='List of agent IDs to deactivate')
        }
    ),
    responses={
        200: OpenApiResponse(
            description="Agents deactivated successfully",
            examples=[
                OpenApiExample(
                    "Deactivation Response",
                    value={
                        "deactivated_agents": [1, 2, 3],
                        "failed_agents": {"5": "Agent not found", "8": "Agent already paused"},
                        "message": "Deactivation process completed"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Bad request - No agent IDs provided"),
        401: OpenApiResponse(description="Unauthorized - Authentication required"),
        403: OpenApiResponse(description="Forbidden - Not authorized as admin"),
        500: OpenApiResponse(description="Internal server error")
    },
    tags=["Admin"]
)
@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsDefAIAdmin])
def admin_deactivate_agents(request):
    """
    Admin endpoint to deactivate multiple agents by their IDs.
    Only accessible by admin user with ADMIN_PRIVY_ID.
    """
    try:
        
        # Get agent IDs from request
        agent_ids = request.data.get('agent_ids', [])
        if not agent_ids:
            return Response({"detail": "No agent IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        logger.info(f"Admin user {request.user.privy_address} attempting to deactivate agents: {agent_ids}")
        
        # Process each agent
        deactivated_agents = []
        failed_agents = {}
        
        for agent_id in agent_ids:
            try:
                # Get agent directly from database, bypassing permission checks
                agent = Agent.objects.get(id=agent_id)
                
                # Check if agent is already paused
                if agent.status != Agent.StatusChoices.RUNNING:
                    failed_agents[str(agent_id)] = f"Agent already {agent.status}"
                    continue
                
                # Update agent status to paused
                agent.status = Agent.StatusChoices.PAUSED
                agent.save()
                
                deactivated_agents.append(agent_id)
                logger.info(f"Admin successfully deactivated agent: {agent_id}")
                
            except Agent.DoesNotExist:
                failed_agents[str(agent_id)] = "Agent not found"
                logger.warning(f"Agent not found: {agent_id}")
            except Exception as e:
                failed_agents[str(agent_id)] = str(e)
                logger.error(f"Error deactivating agent {agent_id}: {str(e)}")
        
        # Return results
        return Response({
            "deactivated_agents": deactivated_agents,
            "failed_agents": failed_agents,
            "message": "Deactivation process completed"
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in admin_deactivate_agents: {str(e)}")
        return Response({"detail": f"Error deactivating agents: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    summary="Get Active Agent IDs",
    description="Get a list of all active (running) agent IDs",
    responses={
        200: OpenApiResponse(
            description="List of active agent IDs retrieved successfully",
            examples=[
                OpenApiExample(
                    "Active Agent IDs Response",
                    value={
                        "active_agent_ids": [1, 2, 3, 5, 8]
                    }
                )
            ]
        ),
        500: OpenApiResponse(description="Error retrieving active agent IDs")
    },
    tags=["Agent"]
)
@api_view(['GET'])
def get_active_agent_ids(request):
    """
    Get a list of all active (running) agent IDs.
    This endpoint is public and can be used to check which agents are currently active.
    """
    try:
        # Get all running agents that are not deleted
        active_agents = Agent.objects.filter(
            status=Agent.StatusChoices.RUNNING,
            is_deleted=False
        )
        
        # Extract just the IDs
        active_agent_ids = list(active_agents.values_list('id', flat=True))
        
        logger.info(f"Retrieved {len(active_agent_ids)} active agent IDs")
        
        return Response({"active_agent_ids": active_agent_ids}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error retrieving active agent IDs: {str(e)}")
        return Response({"detail": f"Error retrieving active agent IDs: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    summary="Update Agent Balances",
    description="Update balances for all agent funds by fetching current balances from the blockchain",
    request=inline_serializer(
        name='UpdateAgentBalancesRequest',
        fields={
            'agent_ids': serializers.ListField(child=serializers.IntegerField(), required=False, help_text="List of agent IDs to update balances for")
        }
    ),
    responses={
        200: OpenApiResponse(
            description="Balances updated successfully",
            examples=[
                OpenApiExample(
                    "Success Response",
                    value={
                        "success": True,
                        "message": "Updated 10 fund balances across 3 wallets"
                    }
                )
            ]
        ),
        404: OpenApiResponse(description="No wallets found to update"),
        500: OpenApiResponse(description="Error updating balances")
    },
    tags=["Agent"]
)
@api_view(['POST'])
@parser_classes([JSONParser])
def update_agent_balances(request):
    """
    Update balances for all agent funds by fetching current balances from the blockchain.
    This endpoint is public and can be called periodically by clients.
    
    Request body can optionally include:
    {
        "agent_ids": [1, 2, 3]  # Optional: specific agent IDs to update
    }
    
    If no agent_ids are provided, all agents' funds will be updated.
    All tokens for each agent will be updated.
    """
    try:
        # Get optional parameters
        agent_ids = request.data.get('agent_ids', [])

        print('agent_ids', agent_ids)
        
        # Get wallets to update based on agent IDs
        if agent_ids:
            wallets = AgentWallet.objects.filter(agent__id__in=agent_ids)

        print('wallets', wallets)
        
        if not wallets.exists():
            print('No wallets found to update')
            return Response({"message": "No wallets found to update"}, status=status.HTTP_404_NOT_FOUND)
        
        # Process wallets
        updated_wallets = 0
        updated_funds = 0
        
        # Run the async function in a synchronous context
        for wallet in wallets:
            print('wallet', wallet)
            # Get all tokens for this wallet
            funds = AgentFundsDAL.get_funds_for_wallet(wallet)
            #print fund id symbol balance and address
            for fund in funds:
                print('fund', fund.id, fund.token_symbol, fund.amount, fund.token_address)
            if not funds.exists():
                continue
            
            # Get token symbols for this wallet
            wallet_token_addresses = [fund.token_address for fund in funds]
            
            # Use asyncio to run the async function
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                balances = loop.run_until_complete(
                    fetch_all_token_balances(wallet.address, wallet_token_addresses)
                )
                print('balances', balances)
            finally:
                loop.close()
            
            # Update fund balances
            for fund in funds:
                if fund.token_address in balances:
                    fund.amount = balances[fund.token_address]
                    fund.save()
                    updated_funds += 1
            
            updated_wallets += 1
        
        # Dashboard cache will be automatically refreshed on next request
        
        return Response({
            "success": True,
            "message": f"Updated {updated_funds} fund balances across {updated_wallets} wallets"
        })
    except Exception as e:
        logger.error(f"Error updating agent balances: {str(e)}")
        return Response({"detail": f"Error updating agent balances: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    summary="Get Active Agent IDs",
    description="Get a list of all active (running) agent IDs",
    responses={
        200: OpenApiResponse(
            description="List of active agent IDs retrieved successfully",
            examples=[
                OpenApiExample(
                    "Active Agent IDs Response",
                    value={
                        "active_agent_ids": [1, 2, 3, 5, 8]
                    }
                )
            ]
        ),
        500: OpenApiResponse(description="Error retrieving active agent IDs")
    },
    tags=["Agent"]
)
@api_view(['GET'])
def get_active_agent_ids(request):
    """
    Get a list of all active (running) agent IDs.
    This endpoint is public and can be used to check which agents are currently active.
    """
    try:
        # Get all running agents that are not deleted
        active_agents = Agent.objects.filter(
            status=Agent.StatusChoices.RUNNING,
            is_deleted=False
        )
        
        # Extract just the IDs
        active_agent_ids = list(active_agents.values_list('id', flat=True))
        
        logger.info(f"Retrieved {len(active_agent_ids)} active agent IDs")
        
        return Response({"active_agent_ids": active_agent_ids}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error retrieving active agent IDs: {str(e)}")
        return Response({"detail": f"Error retrieving active agent IDs: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@parser_classes([JSONParser])
@permission_classes([IsDefAIAdmin])
def admin_deactivate_agents(request):
    """
    Admin endpoint to deactivate multiple agents by their IDs.
    Only accessible by admin user with ADMIN_PRIVY_ID.
    """
    try:
        
        # Get agent IDs from request
        agent_ids = request.data.get('agent_ids', [])
        if not agent_ids:
            return Response({"detail": "No agent IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        logger.info(f"Admin user {request.user.privy_address} attempting to deactivate agents: {agent_ids}")
        
        # Process each agent
        deactivated_agents = []
        failed_agents = {}
        
        for agent_id in agent_ids:
            try:
                # Get agent directly from database, bypassing permission checks
                agent = Agent.objects.get(id=agent_id)
                
                # Check if agent is already paused
                if agent.status != Agent.StatusChoices.RUNNING:
                    failed_agents[str(agent_id)] = f"Agent already {agent.status}"
                    continue
                
                # Update agent status to paused
                agent.status = Agent.StatusChoices.PAUSED
                agent.save()
                
                deactivated_agents.append(agent_id)
                logger.info(f"Admin successfully deactivated agent: {agent_id}")
                
            except Agent.DoesNotExist:
                failed_agents[str(agent_id)] = "Agent not found"
                logger.warning(f"Agent not found: {agent_id}")
            except Exception as e:
                failed_agents[str(agent_id)] = str(e)
                logger.error(f"Error deactivating agent {agent_id}: {str(e)}")
        
        # Return results
        return Response({
            "deactivated_agents": deactivated_agents,
            "failed_agents": failed_agents,
            "message": "Deactivation process completed"
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error in admin_deactivate_agents: {str(e)}")
        return Response({"detail": f"Error deactivating agents: {str(e)}"}, 
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@extend_schema(
    summary="Get Agent PNL Graph Data",
    description="Retrieve PNL graph data for an agent over a specified time period using adjusted PNL values",
    parameters=[
        OpenApiParameter(
            name='agent_id',
            description='ID of the agent to get PNL data for',
            required=True,
            type=int,
            location=OpenApiParameter.QUERY
        ),
        OpenApiParameter(
            name='days',
            description='Number of days to include in the graph data (default: 30, max: 90)',
            required=False,
            type=int,
            location=OpenApiParameter.QUERY
        )
    ],
    responses={
        200: OpenApiResponse(
            description="PNL graph data retrieved successfully",
            examples=[
                OpenApiExample(
                    "PNL Graph Data Response",
                    value={
                        "data_points": [
                            {
                                "date": "2023-07-01",
                                "portfolio_value": 1000.0,
                                "pnl_absolute": 10.0,
                                "pnl_percentage": 1.0
                            },
                            {
                                "date": "2023-07-02",
                                "portfolio_value": 1020.0,
                                "pnl_absolute": 20.0,
                                "pnl_percentage": 2.0
                            }
                        ],
                        "total_pnl_absolute": 30.0,
                        "total_pnl_percentage": 3.0,
                        "start_date": "2023-07-01",
                        "end_date": "2023-07-02"
                    }
                )
            ]
        ),
        400: OpenApiResponse(description="Bad request - Invalid parameters"),
        401: OpenApiResponse(description="Unauthorized - Authentication required"),
        403: OpenApiResponse(description="Forbidden - Not authorized to access this agent"),
        404: OpenApiResponse(description="Not found - Agent not found or no data available"),
        500: OpenApiResponse(description="Internal server error")
    },
    tags=["Agent"]
)
@api_view(['GET'])
@authentication_classes([PrivyAuthentication])
@permission_classes([IsAuthenticated])
def get_agent_pnl_graph_data(request):
    """
    Get PNL graph data for an agent over a specified time period using adjusted PNL values.
    
    This endpoint:
    1. Retrieves portfolio snapshots for the specified agent and time period
    2. Groups snapshots by day (taking the latest snapshot for each day)
    3. Calculates day-to-day PNL changes (both absolute and percentage)
    4. Returns formatted data suitable for graph visualization
    
    Query Parameters:
    - agent_id: ID of the agent to get PNL data for (required)
    - days: Number of days to include in the graph data (default: 30, max: 90)
    """
    try:
        # Get query parameters
        agent_id = request.query_params.get('agent_id')
        days_str = request.query_params.get('days', '30')
        
        # Validate agent_id
        if not agent_id:
            return Response({"detail": "agent_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            agent_id = int(agent_id)
        except ValueError:
            return Response({"detail": "agent_id must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate days
        try:
            days = int(days_str)
            if days < 1:
                days = 30
            elif days > 90:  # Limit to 90 days to prevent excessive data retrieval
                days = 90
        except ValueError:
            days = 30
        
        # Get the agent and verify ownership
        try:
            agent = Agent.objects.get(id=agent_id)
            
            # Check if agent belongs to current user
            if agent.user.privy_address != request.user.privy_address:
                logger.warning(f"User {request.user.privy_address} attempted to access agent {agent_id} owned by {agent.user.privy_address}")
                return Response({"detail": "You don't have permission to access this agent"}, status=status.HTTP_403_FORBIDDEN)
                
        except Agent.DoesNotExist:
            return Response({"detail": "Agent not found"}, status=status.HTTP_404_NOT_FOUND)
        
        # Calculate date range
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        # Get portfolio snapshots for the specified time period
        snapshots = PortfolioSnapshot.objects.filter(
            agent=agent,
            timestamp__gte=start_date,
            timestamp__lte=end_date
        ).order_by('timestamp')
        
        if not snapshots.exists():
            return Response({"detail": "No portfolio data available for the specified time period"}, status=status.HTTP_404_NOT_FOUND)
        
        # Group snapshots by day (taking the latest snapshot for each day)
        daily_snapshots = {}
        for snapshot in snapshots:
            # Convert to date (without time) for grouping
            date_key = snapshot.timestamp.date()
            
            # Store the snapshot if it's the first one for this day or later than the existing one
            if date_key not in daily_snapshots or snapshot.timestamp > daily_snapshots[date_key].timestamp:
                daily_snapshots[date_key] = snapshot
        
        # Sort the days
        sorted_dates = sorted(daily_snapshots.keys())
        
        # Prepare data points
        data_points = []
        prev_snapshot = None
        total_pnl_absolute = 0
        start_value = None
        
        for date in sorted_dates:
            snapshot = daily_snapshots[date]
            portfolio_value = float(snapshot.total_usd_value)
            
            # Set initial value if this is the first data point
            if prev_snapshot is None:
                start_value = portfolio_value
                pnl_absolute = 0
                pnl_percentage = 0
            else:
                # Use the absolute_pnl_usd value directly from the snapshot
                if snapshot.absolute_pnl_usd is not None:
                    pnl_absolute = float(snapshot.absolute_pnl_usd)
                    pnl_percentage = float(snapshot.percentage_pnl)
                else:
                    # Fallback to calculation only if the stored value is None
                    from ..utils.pnl_utils import AdjustedPnLCalculator
                    
                    adjusted_result = AdjustedPnLCalculator.calculate_adjusted_pnl(
                        agent=agent,
                        start_date=prev_snapshot.timestamp,
                        end_date=snapshot.timestamp
                    )
                    
                    if adjusted_result.get('success', False):
                        pnl_absolute = adjusted_result.get('adjusted_absolute_pnl_usd', 0)
                        pnl_percentage = adjusted_result.get('adjusted_percentage_pnl', 0)
                    else:
                        # Final fallback if everything else fails
                        pnl_absolute = portfolio_value - float(prev_snapshot.total_usd_value)
                        pnl_percentage = (pnl_absolute / float(prev_snapshot.total_usd_value)) * 100 if float(prev_snapshot.total_usd_value) > 0 else 0
                
                # Add to total PNL
                total_pnl_absolute += pnl_absolute
            
            # Add data point
            data_points.append({
                'date': date.isoformat(),
                'portfolio_value': round(portfolio_value, 2),
                'pnl_absolute': round(pnl_absolute, 2),
                'pnl_percentage': round(pnl_percentage, 2)
            })
            
            # Update previous snapshot for next iteration
            prev_snapshot = snapshot
        
        # Calculate total percentage PNL for the entire period
        total_pnl_percentage = 0
        if start_value and start_value > 0:
            end_value = float(daily_snapshots[sorted_dates[-1]].total_usd_value)
            total_pnl_percentage = ((end_value - start_value) / start_value) * 100
        
        # Return formatted response
        response_data = {
            'data_points': data_points,
            'total_pnl_absolute': round(total_pnl_absolute, 2),
            'total_pnl_percentage': round(total_pnl_percentage, 2),
            'start_date': sorted_dates[0].isoformat() if sorted_dates else None,
            'end_date': sorted_dates[-1].isoformat() if sorted_dates else None
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
        
    except Exception as e:
        error_context = log_error(e, {
            'agent_id': request.query_params.get('agent_id'),
            'days': request.query_params.get('days'),
            'endpoint': 'get_agent_pnl_graph_data'
        })
        logger.error(f"Error retrieving PNL graph data: {str(e)}")
        return Response({"detail": f"Error retrieving PNL graph data: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

# DEPRECATED: RebalancingTradeViewSet has been replaced by VaultRebalanceViewSet
# The following code is kept for reference but is no longer in use
#
# @extend_schema_view(
#     list=extend_schema(
#         summary="List Rebalancing Trades",
#         description="Get a paginated list of all rebalancing trades (public endpoint)",
#         parameters=[
#             OpenApiParameter(
#                 name='scenario_type',
#                 type=str,
#                 location=OpenApiParameter.QUERY,
#                 description='Filter by scenario type (IDLE_DEPLOYMENT or REBALANCING)',
#                 enum=['IDLE_DEPLOYMENT', 'REBALANCING']
#             ),
# DEPRECATED: Replaced by VaultRebalanceViewSet in vault_rebalance_views.py
# class RebalancingTradeViewSet(viewsets.ReadOnlyModelViewSet):
#     """
#     Public API endpoint for retrieving rebalancing trades.
#     No authentication required - this is a public endpoint.
#     """
#     serializer_class = RebalancingTradeSerializer
#     pagination_class = pagination.PageNumberPagination
#     permission_classes = []  # No authentication required
#     
#     def get_queryset(self):
#         """
#         Filter rebalancing trades based on query parameters.
#         """
#         from ..models import RebalancingTrade
#         from datetime import datetime
#         
#         queryset = RebalancingTrade.objects.all().order_by('-execution_timestamp')
#         
#         # Filter by scenario type
#         scenario_type = self.request.query_params.get('scenario_type')
#         if scenario_type:
#             queryset = queryset.filter(scenario_type=scenario_type)
#         
#         # Filter by transaction type
#         transaction_type = self.request.query_params.get('transaction_type')
#         if transaction_type:
#             queryset = queryset.filter(transaction_type=transaction_type)
#         
#         # Filter by status
#         status = self.request.query_params.get('status')
#         if status:
#             queryset = queryset.filter(status=status)
#         
#         # Filter by protocol
#         protocol = self.request.query_params.get('protocol')
#         if protocol:
#             queryset = queryset.filter(protocol__icontains=protocol)
#         
#         # Filter by date range
#         from_date = self.request.query_params.get('from_date')
#         to_date = self.request.query_params.get('to_date')
#         
#         if from_date:
#             try:
#                 from_date_obj = datetime.strptime(from_date, '%Y-%m-%d').date()
#                 queryset = queryset.filter(execution_timestamp__date__gte=from_date_obj)
#             except ValueError:
#                 pass  # Invalid date format, ignore filter
#         
#         if to_date:
#             try:
#                 to_date_obj = datetime.strptime(to_date, '%Y-%m-%d').date()
#                 queryset = queryset.filter(execution_timestamp__date__lte=to_date_obj)
#             except ValueError:
#                 pass  # Invalid date format, ignore filter
#         
#         return queryset
#     
#     def list(self, request, *args, **kwargs):
#         """
#         List rebalancing trades with filtering and pagination.
#         """
#         try:
#             queryset = self.filter_queryset(self.get_queryset())
#             
#             # Apply pagination
#             page = self.paginate_queryset(queryset)
#             if page is not None:
#                 serializer = self.get_serializer(page, many=True)
#                 return self.get_paginated_response(serializer.data)
#             
#             serializer = self.get_serializer(queryset, many=True)
#             return Response(serializer.data)
#             
#         except Exception as e:
#             logger.error(f"Error retrieving rebalancing trades: {str(e)}")
#             return Response(
#                 {"detail": "Error retrieving rebalancing trades"},
#                 status=status.HTTP_500_INTERNAL_SERVER_ERROR
#             )
