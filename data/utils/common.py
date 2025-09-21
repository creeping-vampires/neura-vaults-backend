import requests
import logging
import secrets
import csv
import os
import boto3
from django.conf import settings
from .rpc_utils import fetch_all_token_balances
from ..models import AgentWallet, AgentFunds, AgentTrade
from decimal import Decimal
import asyncio
from ..models import Agent, PortfolioSnapshot
from django.utils import timezone
from django.db import connections
import json
from asgiref.sync import sync_to_async
from ..utils.pnl_utils import SnapshotPnLUpdater

logger = logging.getLogger(__name__)

def generate_random_ethereum_address():
    """
    Generate a random 42-character hexadecimal string that begins with "0x" for development purposes.
    This simulates an Ethereum address without actually creating a wallet.
    """
    # Generate a random 40-character hex string (without the 0x prefix)
    random_hex = secrets.token_hex(20)  # 20 bytes = 40 hex characters
    
    # Add the 0x prefix to make it a valid Ethereum address format
    address = f"0x{random_hex}"
    
    return address

def get_wallet_address_from_privy(privy_id):
    """
    Fetch the wallet address associated with a Privy ID.
    Returns the first Ethereum wallet address found, or None if not found.
    """
    try:
        # Construct the API URL
        url = f"{settings.PRIVY_API_URL}/users/{privy_id}"
        
        # Make the request to Privy API
        response = requests.get(
            url,
            auth=(settings.PRIVY_APP_ID, settings.PRIVY_API_KEY),
            headers={"privy-app-id": settings.PRIVY_APP_ID}
        )
        response.raise_for_status()
        
        # Parse the response
        data = response.json()
        
        # Find the first Ethereum wallet in linked_accounts
        for account in data.get('linked_accounts', []):
            if account.get('type') == 'wallet' and account.get('chain_type') == 'ethereum':
                return account.get('address')
                
        logger.warning(f"No Ethereum wallet found for Privy ID: {privy_id}")
        return None
        
    except requests.RequestException as e:
        logger.error(f"Error fetching wallet address from Privy: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching wallet address: {str(e)}")
        return None


def get_token_address(token_symbol):
    """
    Get the contract address for a token symbol from the tokens.csv file.
    Returns the contract address if found, None otherwise.
    """
    try:
        # Path to the tokens.csv file
        tokens_csv_path = os.path.join(settings.BASE_DIR, 'tokens.csv')
        
        # Check if the file exists
        if not os.path.exists(tokens_csv_path):
            logger.error(f"tokens.csv file not found at {tokens_csv_path}")
            return None
        
        # Read the CSV file
        with open(tokens_csv_path, 'r') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row['Token'] == token_symbol:
                    return row['Contract Address']
        
        logger.warning(f"Token symbol not found in tokens.csv: {token_symbol}")
        return None
    except Exception as e:
        logger.error(f"Error reading tokens.csv: {str(e)}")
        return None




# Cache for token prices with expiration time (2 minutes)
# token_price_cache = {}
CACHE_EXPIRATION_SECONDS = 120  # 2 minutes

async def fetch_token_price(token_symbol):
    """
    Fetch the current USD price for a token using CoinGecko API with caching.
    Uses the coingecko_mappings module to map token symbols to CoinGecko IDs.
    
    Args:
        token_symbol: The token symbol to get price for
        
    Returns:
        float: The token price in USD, or None if there was an error
    """
    import time
    try:

        url = f"{settings.TRADE_API_BASE_URL}/api/token-price/{token_symbol}"
        response = requests.get(url, headers={"x-api-key": settings.API_TOKEN_KEY})
        response.raise_for_status()
        data = response.json()
        
        # Extract price from response
        price = data['data'].get('price')

        # token_price_cache[token_symbol] = (price, time.time())


        if price is None:
            logger.warning(f"No price data found for token: {token_symbol}")
            return None
        
        price_float = float(price)
        
        return price_float
    except Exception as e:
        logger.error(f"Error fetching token price: {str(e)}")
        return None


def fetch_all_token_prices(token_symbols):
    """
    Fetch prices for multiple tokens concurrently with efficient batching.
    
    Args:
        token_symbols: List of token symbols to get prices for
    
    Returns:
        dict: Dictionary mapping token symbols to their USD prices
    """
    return asyncio.run(_fetch_all_token_prices_async(token_symbols))


 # cache this function response for 5 min

async def _fetch_all_token_prices_async(token_symbols):
    """
    Fetch prices for multiple tokens concurrently with efficient batching.
    Uses caching to minimize API calls.
    
    Args:
        token_symbols: List of token symbols to get prices for
        
    Returns:
        dict: Dictionary mapping token symbols to their USD prices
    """
    import time
    
    # Check which tokens need fresh prices
    # current_time = time.time()
    # tokens_to_fetch = []
    prices = {}
    
    # First check cache
    # for symbol in token_symbols:
    #     if symbol in token_price_cache:
    #         cached_price, timestamp = token_price_cache[symbol]
    #         if current_time - timestamp < CACHE_EXPIRATION_SECONDS:
    #             prices[symbol] = cached_price
    #             continue
    #     tokens_to_fetch.append(symbol)
    
    # Only fetch prices for tokens not in cache or with expired cache
    if token_symbols:
        tasks = [fetch_token_price(symbol) for symbol in token_symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, symbol in enumerate(token_symbols):
            if isinstance(results[i], Exception):
                logger.error(f"Error fetching price for {symbol}: {str(results[i])}")
                prices[symbol] = 0
            else:
                prices[symbol] = results[i] or 0
    
    return prices

def approve_token_spending(token_address: str, api_key: str) -> dict:
    """
    Approve token spending for a given token address using the token API.

    Args:
        token_address (str): The address of the token to approve.
        api_key (str): The API key to use for authorization.

    Returns:
        dict: The JSON response from the token API.

    Raises:
        Exception: If the approval request fails.
    """
    url = f"{settings.TOKEN_API_BASE_URL}/token/approve"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"tokenAddress": token_address}
    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()

def process_agent_transactions(agent, transactions: list):
    """
    Process a list of token conversion transactions for an agent:
    - Checks if the agent has enough of the from_token.
    - Updates the funds accordingly.
    - Adds a row in the AgentTrade table for each successful transaction.

    Args:
        agent (Agent): The agent instance.
        transactions (list): List of dicts, each with keys:
            - from_token (str)
            - to_token (str)
            - amount_from (float or str)
            - amount_to (float or str)
            - (optional) amount_usd, transaction_hash, from_token_address, to_token_address, etc.

    Returns:
        list: List of successful transaction dicts.

    Raises:
        ValueError: If any transaction fails (insufficient funds or missing fund).
    """
    wallet = AgentWallet.objects.get(agent=agent)
    results = []

    for tx in transactions:
        from_token = tx["from_token"]
        to_token = tx["to_token"]
        amount_from = Decimal(str(tx["amount_from"]))
        amount_to = Decimal(str(tx["amount_to"]))

        try:
            from_fund = AgentFunds.objects.get(wallet=wallet, token_symbol=from_token)
            to_fund, _ = AgentFunds.objects.get_or_create(wallet=wallet, token_symbol=to_token, defaults={"amount": Decimal("0")})

            if from_fund.amount < amount_from:
                raise ValueError(f"Insufficient balance for {from_token}: required {amount_from}, available {from_fund.amount}")

            # Perform the transfer
            from_fund.amount -= amount_from
            to_fund.amount += amount_to
            from_fund.save()
            to_fund.save()
            tx_hash = tx.get("transaction_hash")

            # Add transaction record
            AgentTrade.objects.create(
                agent=agent,
                from_token=from_token,
                to_token=to_token,
                amount_usd=tx.get("amount_usd", 0),
                transaction_hash=tx_hash,
                # add other fields as needed
            )
            
            # Create a portfolio snapshot after the trade
            try:
                # Use the dedicated function to create a snapshot
                # Use async_to_sync since we're in a synchronous context
                from asgiref.sync import async_to_sync
                snapshot_result = async_to_sync(create_portfolio_value_snapshot_for_agent)(agent.id)
                
                if snapshot_result.get('success', False):
                    logger.info(f"Created portfolio snapshot for agent {agent.id} after trade with value {snapshot_result.get('total_usd_value', 0)}")
                else:
                    logger.warning(f"Failed to create portfolio snapshot for agent {agent.id} after trade: {snapshot_result.get('error', 'Unknown error')}")
                    
            except Exception as e:
                logger.error(f"Error creating portfolio snapshot for agent {agent.id} after trade: {str(e)}")
                # Don't fail the whole process if snapshot update fails
            
            # Clear dashboard cache to ensure fresh data
            from data.cache_utils import clear_dashboard_cache
            try:
                clear_dashboard_cache()
            except Exception as cache_error:
                logger.warning(f"Failed to clear dashboard cache: {cache_error}")

            results.append({**tx, "transaction_hash": tx_hash})
        except AgentFunds.DoesNotExist:
            raise ValueError(f"No fund for {from_token} in agent's wallet")
        except Exception as e:
            raise ValueError(f"Transaction failed: {str(e)}")

    return results


async def calculate_agent_funds_usd_value(agent):
    """
    Calculate the total USD value of all tokens in an agent's wallet using on-chain balances.
    
    Args:
        agent: The agent instance
        
    Returns:
        dict: Dictionary with total USD value and breakdown by token
    """
    from ..models import AgentWallet, AgentFunds
    from decimal import Decimal
    from asgiref.sync import sync_to_async
    
    try:
        # Get the agent's wallet (sync operation)
        wallet = await sync_to_async(AgentWallet.objects.get)(agent=agent)
        wallet_address = wallet.address
        
        # Get all funds for this wallet to know which tokens to check (sync operation)
        funds_list = await sync_to_async(list)(AgentFunds.objects.filter(wallet=wallet))
        
        # If no funds, return zero value
        if not funds_list:
            return {
                'total_usd_value': 0,
                'token_values': {}
            }
        
        # Get unique token addresses and create a mapping from address to symbol
        # Try to access risk_profile attribute, but handle the case where it might not exist
        try:
            # Only filter HYPE token if risk_profile exists and is not moderate
            if hasattr(agent, 'risk_profile') and agent.risk_profile != 'moderate':
                funds_list = [fund for fund in funds_list if fund.token_address != '0x5555555555555555555555555555555555555555']
        except Exception as e:
            # If there's any error accessing the attribute, log it and continue without filtering
            logger.warning(f"Could not access risk_profile for agent {agent.id}: {str(e)}")
            
        token_addresses = set(fund.token_address for fund in funds_list)
        address_to_symbol = {fund.token_address: fund.token_symbol for fund in funds_list}
        
        # Fetch on-chain balances for all tokens
        on_chain_balances = await fetch_all_token_balances(wallet_address, token_addresses)
        
        # Fetch all token prices efficiently in one batch directly using the async function
        token_symbols = set(fund.token_symbol for fund in funds_list)
        token_prices = await _fetch_all_token_prices_async(token_symbols)
        
        # Calculate USD value for each token and total
        total_usd_value = Decimal('0')
        token_values = {}
        
        # Process each token address and map it back to its symbol
        for token_address in token_addresses:
            token_symbol = address_to_symbol.get(token_address)
            if not token_symbol:
                continue
                
            # Use on-chain balance instead of database amount
            amount = on_chain_balances.get(token_address, 0)
            price = token_prices.get(token_symbol, 0)
            
            # Calculate USD value for this token
            usd_value = float(amount) * price
            token_values[token_symbol] = {
                'amount': float(amount),
                'price_usd': price,
                'value_usd': usd_value
            }
            
            total_usd_value += Decimal(str(usd_value))
        
        return {
            'total_usd_value': float(total_usd_value),
            'token_values': token_values
        }
        
    except AgentWallet.DoesNotExist:
        return {
            'total_usd_value': 0,
            'token_values': {}
        }
    except Exception as e:
        logger.error(f"Error calculating agent funds USD value: {str(e)}")
        return {
            'total_usd_value': 0,
            'token_values': {},
            'error': str(e)
        }


async def calculate_all_agents_funds_usd_value():
    """
    Calculate the total USD value of funds for all agents using on-chain balances.
    
    Returns:
        dict: Dictionary mapping agent IDs to their fund values
    """
    from ..models import Agent
    from asgiref.sync import sync_to_async
    
    try:
        # Get all active agents (sync operation)
        agents = await sync_to_async(list)(Agent.objects.filter(deleted_at__isnull=True))
        
        # Calculate USD value for each agent
        results = {}
        for agent in agents:
            # This will use the updated function that fetches on-chain balances
            agent_value = await calculate_agent_funds_usd_value(agent)
            results[agent.id] = {
                'agent_name': agent.name,
                'total_usd_value': agent_value['total_usd_value'],
                'token_values': agent_value['token_values']
            }
        
        return results
    except Exception as e:
        logger.error(f"Error calculating all agents funds USD value: {str(e)}")
        return {}


# async def calculate_agent_24h_pnl(agent):
#     """
#     Calculate the 24-hour PNL for an agent by comparing current portfolio value
#     with the value 24 hours ago, using on-chain balances for current value.
    
#     Args:
#         agent: The agent instance
        
#     Returns:
#         dict: Dictionary with PNL information
#     """
#     from ..models import AgentWallet, AgentFunds, AgentTrade
#     from django.utils import timezone
#     from datetime import timedelta
#     import json
#     from asgiref.sync import sync_to_async
    
#     try:
#         # Get current portfolio value using on-chain balances
#         current_value = await calculate_agent_funds_usd_value(agent)
#         current_total_usd = current_value['total_usd_value']
        
#         # Get timestamp for 24 hours ago
#         twenty_four_hours_ago = timezone.now() - timedelta(hours=24)
        
#         # Get all trades in the last 24 hours (sync operation)
#         recent_trades = await sync_to_async(list)(
#             AgentTrade.objects.filter(
#                 agent=agent,
#                 created_at__gte=twenty_four_hours_ago
#             )
#         )
        
#         # Calculate net deposits/withdrawals in the last 24 hours
#         # This is a simplified approach - in a real system, you'd track deposits/withdrawals separately
#         net_flow = 0
#         for trade in recent_trades:
#             # If this is a deposit or withdrawal (could be tracked differently in your system)
#             if hasattr(trade, 'is_deposit') and trade.is_deposit:
#                 net_flow += float(trade.amount_usd)
#             elif hasattr(trade, 'is_withdrawal') and trade.is_withdrawal:
#                 net_flow -= float(trade.amount_usd)
        
#         # Try to get the portfolio value from 24 hours ago from a historical record
#         try:
#             from ..models import PortfolioSnapshot
#             # Try to get snapshot from 24 hours ago (sync operation)
#             old_snapshot = await sync_to_async(lambda: PortfolioSnapshot.objects.filter(
#                 agent=agent,
#                 timestamp__lte=twenty_four_hours_ago
#             ).order_by('-timestamp').first())()
            
#             if old_snapshot:
#                 old_value = float(old_snapshot.total_usd_value)
#                 logger.info(f"Using 24-hour old snapshot for agent {agent.id} from {old_snapshot.timestamp}")
#             else:
#                 # If no 24-hour snapshot exists, try to get the first recorded snapshot
#                 first_snapshot = await sync_to_async(lambda: PortfolioSnapshot.objects.filter(
#                     agent=agent
#                 ).order_by('timestamp').first())()
                
#                 if first_snapshot:
#                     old_value = float(first_snapshot.total_usd_value)
#                     logger.info(f"Using first available snapshot for agent {agent.id} from {first_snapshot.timestamp}")
#                 else:
#                     # If no snapshot exists at all, estimate based on current holdings and recent trades
#                     old_value = current_total_usd - net_flow
#                     logger.info(f"No snapshots found for agent {agent.id}, estimating PNL based on trades")

                
#         except Exception as snapshot_error:
#             logger.error(f"Error getting historical snapshot: {str(snapshot_error)}")
#             # If the PortfolioSnapshot model doesn't exist or there's an error
#             # Estimate based on current value and recent trades
#             old_value = current_total_usd - net_flow
        
#         # Calculate absolute and percentage PNL
#         absolute_pnl = current_total_usd - old_value - net_flow
#         percentage_pnl = (absolute_pnl / old_value) * 100 if old_value > 0 else 0
        
#         return {
#             'current_value_usd': current_total_usd,
#             'value_24h_ago_usd': old_value,
#             'absolute_pnl_usd': absolute_pnl,
#             'percentage_pnl': percentage_pnl,
#             'net_flow_usd': net_flow
#         }
        
#     except Exception as e:
#         logger.error(f"Error calculating agent 24h PNL: {str(e)}")
#         return {
#             'current_value_usd': 0,
#             'value_24h_ago_usd': 0,
#             'absolute_pnl_usd': 0,
#             'percentage_pnl': 0,
#             'net_flow_usd': 0,
#             'error': str(e)
#         }


# async def calculate_all_agents_24h_pnl():
#     """
#     Calculate the 24-hour PNL for all agents.
    
#     Returns:
#         dict: Dictionary mapping agent IDs to their PNL information
#     """
#     from ..models import Agent
    
#     try:
#         # Get all active agents
#         agents = Agent.objects.filter(deleted_at__isnull=True)
        
#         # Calculate PNL for each agent
#         results = {}
#         for agent in agents:
#             agent_pnl = await calculate_agent_24h_pnl(agent)
#             results[agent.id] = {
#                 'agent_name': agent.name,
#                 'current_value_usd': agent_pnl['current_value_usd'],
#                 'absolute_pnl_usd': agent_pnl['absolute_pnl_usd'],
#                 'percentage_pnl': agent_pnl['percentage_pnl']
#             }
        
#         return results
#     except Exception as e:
#         logger.error(f"Error calculating all agents 24h PNL: {str(e)}")
#         return {}


async def create_portfolio_value_snapshot_for_agent(agent_id):
    """
    Create a snapshot of a specific agent's portfolio value for historical tracking.
    
    Args:
        agent_id: The ID of the agent to create a snapshot for
        
    Returns:
        dict: A dictionary with success status and snapshot information
    """
    
    
    try:
        # Close any existing connections before starting
        await sync_to_async(connections.close_all)()
        
        # Get the agent by ID
        agent = await sync_to_async(lambda: Agent.objects.filter(
            id=agent_id,
            deleted_at__isnull=True,  # Not soft-deleted
            is_deleted=False          # Not marked as deleted
        ).first())()
        
        if not agent:
            logger.warning(f"Agent with ID {agent_id} not found or is deleted")
            return {
                'success': False,
                'error': f"Agent with ID {agent_id} not found or is deleted"
            }
        
        logger.info(f"Creating portfolio snapshot for agent {agent.id} ({agent.name})")
        
        # Calculate current portfolio value
        portfolio_value = await calculate_agent_funds_usd_value(agent)
        
        # Create snapshot (sync operation)
        snapshot = await sync_to_async(PortfolioSnapshot.objects.create)(
            agent=agent,
            timestamp=timezone.now(),
            total_usd_value=portfolio_value['total_usd_value'],
            token_values_json=json.dumps(portfolio_value['token_values'])
        )
        
       
        await sync_to_async(SnapshotPnLUpdater.update_snapshot_pnl)(snapshot)
        
        logger.info(f"Successfully created portfolio snapshot for agent {agent.id}")
        
        return {
            'success': True,
            'snapshot_id': snapshot.id,
            'agent_id': agent.id,
            'total_usd_value': portfolio_value['total_usd_value']
        }
    except Exception as e:
        logger.error(f"Error creating portfolio value snapshot for agent {agent_id}: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        # Always close connections when done
        await sync_to_async(connections.close_all)()

async def create_portfolio_value_snapshots():
    """
    Create snapshots of all agents' portfolio values for historical tracking.
    This should be run periodically (e.g., hourly) to maintain historical data for PnL calculations.
    Only processes active agents (not deleted and not in 'deleted' status).
    """
    from ..models import Agent
    from django.db import connections
    from asgiref.sync import sync_to_async
    
    try:
        # Close any existing connections before starting
        await sync_to_async(connections.close_all)()
        
        # Get all active agents (sync operation)
        # Filter for agents that are not deleted and not in 'deleted' status
        agents = await sync_to_async(list)(
            Agent.objects.filter(
                deleted_at__isnull=True,  # Not soft-deleted
                is_deleted=False,        # Not marked as deleted
                status=Agent.StatusChoices.RUNNING  # Only include running agents
            )
        )
        
        logger.info(f"Creating portfolio snapshots for {len(agents)} active agents")
        
        # Create snapshots for each agent
        snapshots_created = 0
        for agent in agents:
            result = await create_portfolio_value_snapshot_for_agent(agent.id)
            if result.get('success', False):
                snapshots_created += 1
            
        logger.info(f"Successfully created {snapshots_created} portfolio snapshots")
        
        return {
            'success': True,
            'snapshots_created': snapshots_created
        }
    except Exception as e:
        logger.error(f"Error creating portfolio value snapshots: {str(e)}")
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        # Always close connections when done
        await sync_to_async(connections.close_all)()