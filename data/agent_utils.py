from web3 import Web3
from django.conf import settings
import logging
import asyncio
import os
from data.data_access_layer import OptimizationResultDAO
from data.utils.common import _fetch_all_token_prices_async
from typing import Optional
logger = logging.getLogger(__name__)

def fetch_token_balance_sync(wallet_address: str, token_address: str) -> float:
    """
    Synchronously fetch token balance for a wallet address using RPC call.
    If token_address is 0x5555555555555555555555555555555555555555, fetch ETH balance instead.
    
    Args:
        wallet_address (str): The wallet address to check balance for
        token_address (str): The token contract address
        
    Returns:
        float: The token balance as a float, or None if there was an error
    """
    try:
        # Connect to the RPC endpoint
        w3 = Web3(Web3.HTTPProvider(settings.BLOCKCHAIN_RPC_URL))
        
        # Special case for ETH (native token)
        ETH_ADDRESS = "0x5555555555555555555555555555555555555555"
        if token_address.lower() == ETH_ADDRESS.lower():
            # Get ETH balance
            balance_wei = w3.eth.get_balance(Web3.to_checksum_address(wallet_address))
            # ETH has 18 decimals
            balance = float(balance_wei) / (10 ** 18)
            return balance
        
        # For ERC20 tokens
        # ERC20 ABI for balanceOf function
        abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }
        ]
        
        # Create contract instance
        contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=abi)
        
        # Call balanceOf function
        balance_wei = contract.functions.balanceOf(Web3.to_checksum_address(wallet_address)).call()
        
        # Get token decimals (default to 18 if not available)
        decimals = 18
        try:
            decimals_abi = [
                {
                    "constant": True,
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "type": "function"
                }
            ]
            decimals_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address), abi=decimals_abi)
            decimals = decimals_contract.functions.decimals().call()
        except Exception as e:
            logger.warning(f"Could not get decimals for token {token_address}, using default 18: {str(e)}")
        
        # Convert to float with proper decimal places
        balance = float(balance_wei) / (10 ** decimals)
        
        return balance
    except Exception as e:
        logger.error(f"Error fetching token balance for {token_address}, wallet {wallet_address}: {str(e)}")
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

def fetch_agent_portfolio(agent_id: Optional[int] = None) -> str:
    """Fetch the agent's portfolio data directly.
    
    This replicates the logic from get_agent_funds_tool but allows us
    to pre-fetch the data and pass it as context to multiple agents.
    
    Args:
        agent_id: The ID of the agent to fetch portfolio data for (optional for agent-agnostic mode)
        
    Returns:
        str: JSON string with the agent's portfolio data
    """
    from data.data_access_layer import AgentDAL, AgentFundsDAL
    from data.models import AgentWallet
    import json
    
    try:
        # Handle agent-agnostic mode
        if agent_id is None:
            logger.info("Running in agent-agnostic mode - returning mock portfolio data")
            return json.dumps({
                "success": True,
                "agent_agnostic_mode": True,
                "message": "Agent-agnostic mode - no specific agent portfolio data available",
                "funds": [],
                "total_usd_value": 0.0
            })
        
        agent = AgentDAL.get_agent_by_id(agent_id)
        if not agent:
            return json.dumps({"error": f"Agent with ID {agent_id} not found."})
            
        try:
            agent_wallet = AgentWallet.objects.get(agent=agent)
            if not agent_wallet.address:
                return json.dumps({"error": f"No wallet address found for agent {agent_id}"})
        except AgentWallet.DoesNotExist:
            return json.dumps({"error": f"No wallet found for agent {agent_id}"})
            
        # Get token information from the model
        funds = AgentFundsDAL.get_funds_for_agent(agent)
        if not funds.exists():
            return json.dumps({"error": f"No funds found for agent {agent_id}."})

        token_symbols = [fund.token_symbol for fund in funds]
        token_prices = fetch_all_token_prices(token_symbols)
        # Create summary with actual balances
        summary = []
        for fund in funds:
            if fund.token_address:  # Only fetch balance if we have a token address
                balance = fetch_token_balance_sync(agent_wallet.address, fund.token_address)
                
                # For HYPE token, subtract 0.1 for gas fees
                if fund.token_address == "0x5555555555555555555555555555555555555555":
                    if balance is not None and balance > 0.1:
                        balance = balance - 0.1
                    else:
                        balance = 0
                    # new agent version will not include HYPE in portfolio if agent risk profile is not moderate 
                    # new agents will now have HYPE token in whitelisted tokens in moderate risk profile
                    if agent.version == 1 or (agent.version == 2 and agent.risk_profile == 'moderate'):
                        summary.append({
                            "token_symbol": 'HYPE',
                            "token_address": fund.token_address,
                            "amount": str(balance),
                            "price": token_prices.get(fund.token_symbol, 0)
                        })
                else:
                    summary.append({
                        "token_symbol": fund.token_symbol,
                        "token_address": fund.token_address,
                        "amount": str(balance) if balance is not None else "0",
                        "price": token_prices.get(fund.token_symbol, 0)
                    })

        # Prepare the final output structure
        output = {
            "funds": summary,
            "min_trade_size": str(agent.min_trade_size),
            "max_trade_size": str(agent.max_trade_size)
        }

        return json.dumps(output)
    except Exception as e:
        return json.dumps({"error": f"Error retrieving funds for agent {agent_id}: {str(e)}"})

def fetch_latest_apy_data() -> dict:
    """Fetch the agent's APY data directly from YieldReport table.
    
    This replicates the logic from the updated get_recent_pool_apy_results endpoint
    to fetch USDe yield data from unique pool addresses.
    
    Returns:
        List: List of yield report data for USDe token
    """
    try:
        from data.models import YieldReport
        
        # Get all unique pool addresses for USDe token (excluding null/empty addresses)
        unique_pools = YieldReport.objects.filter(
            pool_address__isnull=False,
            pool_address__gt='',
            token='USDe'
        ).values('pool_address').distinct()
        
        results_data = []
        
        # For each unique pool address, get the latest 2 records for USDe token
        for pool in unique_pools:
            pool_results = YieldReport.objects.filter(
                pool_address=pool['pool_address'],
                token='USDe'
            ).order_by('-created_at')[:2]
            
            # Convert QuerySet to list of dictionaries for this pool
            for result in pool_results:
                results_data.append({
                    'id': result.id,
                    'created_at': result.created_at.isoformat(),
                    'token': result.token,
                    'protocol': result.protocol,
                    'apy': float(result.apy),
                    'tvl': float(result.tvl),
                    'token_address': result.token_address,
                    'pool_address': result.pool_address,
                    'is_current_best': result.is_current_best
                })
        
        # Sort all results by created_at descending to maintain chronological order
        results_data.sort(key=lambda x: x['created_at'], reverse=True)
        
        if len(results_data) == 0:
            return []
        
        return results_data
    except Exception as e:
        return {"error": f"Error retrieving APY data: {str(e)}"}

def fetch_protocol_status() -> dict:
    """
    Fetch the current status of the YieldAllocatorVault protocol.
    
    This function provides information about:
    - Idle asset balance in the vault
    - Total assets (including those in pools)
    - Pending withdrawal requests
    - Pool balances and allocations
    - Liquidity and withdrawal coverage ratios
    
    Returns:
        dict: Protocol status information for agent decision-making
    """
    try:
        from data.utils.rpc_utils import get_web3_provider
        from data.utils.abis.yield_allocator_abi import yield_allocator_abi
        from data.utils.abis.whitelist_registry import whitelist_registry_abi
        from django.conf import settings
        import json
        
        # Get Web3 instance
        w3 = get_web3_provider()
        if not w3:
            return {"error": "Failed to connect to blockchain"}
        
        # Get contract addresses from settings
        vault_address =  os.getenv('YIELD_ALLOCATOR_VAULT_ADDRESS')
        whitelist_registry_address = os.getenv('WHITELIST_REGISTRY_ADDRESS')
        
        if not vault_address or not whitelist_registry_address:
            return {"error": "Contract addresses not configured"}
        
        # Create contract instances
        vault_contract = w3.eth.contract(
            address=Web3.to_checksum_address(vault_address),
            abi=yield_allocator_abi
        )
        
        whitelist_contract = w3.eth.contract(
            address=Web3.to_checksum_address(whitelist_registry_address),
            abi=whitelist_registry_abi
        )
        
        # Get asset token address
        asset_address = vault_contract.functions.asset().call()
        
        # Create asset token contract (assuming ERC20)
        erc20_abi = [
            {"constant": True, "inputs": [], "name": "symbol", "outputs": [{"name": "", "type": "string"}], "type": "function"},
            {"constant": True, "inputs": [], "name": "decimals", "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
            {"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}
        ]
        
        asset_contract = w3.eth.contract(
            address=Web3.to_checksum_address(asset_address),
            abi=erc20_abi
        )
        
        # Get asset token info
        asset_symbol = asset_contract.functions.symbol().call()
        asset_decimals = asset_contract.functions.decimals().call()
        
        # Get vault balances
        idle_balance = asset_contract.functions.balanceOf(vault_address).call()
        total_assets = vault_contract.functions.totalAssets().call()
        allocated_assets = total_assets - idle_balance
        
        # Convert to human-readable format
        idle_balance_formatted = idle_balance / (10 ** asset_decimals)
        total_assets_formatted = total_assets / (10 ** asset_decimals)
        allocated_assets_formatted = allocated_assets / (10 ** asset_decimals)
        
        # Get whitelisted pools
        whitelisted_pools = whitelist_contract.functions.getWhitelistedPools().call()
        
        # Get pool balances
        pool_balances = []
        for i, pool_address in enumerate(whitelisted_pools):
            try:
                pool_balance = vault_contract.functions.poolPrincipal(pool_address).call()
                pool_balance_formatted = pool_balance / (10 ** asset_decimals)
                percentage = (pool_balance_formatted / total_assets_formatted * 100) if total_assets_formatted > 0 else 0
                
                pool_balances.append({
                    'address': pool_address,
                    'balance': pool_balance_formatted,
                    'percentage': round(percentage, 2),
                    'balance_raw': pool_balance
                })
            except Exception as e:
                logger.warning(f"Failed to get balance for pool {pool_address}: {e}")
                pool_balances.append({
                    'address': pool_address,
                    'balance': 0,
                    'percentage': 0,
                    'balance_raw': 0,
                    'error': str(e)
                })
        
        # Try to get pending withdrawal information
        pending_withdrawals = []
        total_withdrawal_needed = 0
        
        try:
            # Get pending withdrawers (this might fail if array is empty or method doesn't exist)
            withdrawer_count = 0
            while True:
                try:
                    withdrawer = vault_contract.functions.pendingWithdrawers(withdrawer_count).call()
                    # Get withdrawal request details
                    request = vault_contract.functions.withdrawalRequests(withdrawer).call()
                    if len(request) > 0 and request[1]:  # Assuming [assets, exists, ...]
                        assets_needed = request[0] / (10 ** asset_decimals)
                        total_withdrawal_needed += assets_needed
                        pending_withdrawals.append({
                            'withdrawer': withdrawer,
                            'assets_needed': assets_needed,
                            'assets_raw': request[0]
                        })
                    withdrawer_count += 1
                except:
                    break
        except Exception as e:
            logger.info(f"No pending withdrawals or error reading: {e}")
        
        # Calculate ratios
        liquidity_ratio = (idle_balance_formatted / total_assets_formatted * 100) if total_assets_formatted > 0 else 0
        withdrawal_coverage = (idle_balance_formatted / total_withdrawal_needed * 100) if total_withdrawal_needed > 0 else 100
        
        # Determine status indicators
        liquidity_status = "healthy"
        if liquidity_ratio < 5:
            liquidity_status = "low"
        elif liquidity_ratio > 50:
            liquidity_status = "high"
        
        withdrawal_status = "sufficient" if withdrawal_coverage >= 100 else "insufficient"
        
        return {
            'success': True,
            'timestamp': w3.eth.get_block('latest')['timestamp'],
            'vault_address': vault_address,
            'asset': {
                'address': asset_address,
                'symbol': asset_symbol,
                'decimals': asset_decimals
            },
            'balances': {
                'idle_balance': idle_balance_formatted,
                'total_assets': total_assets_formatted,
                'allocated_assets': allocated_assets_formatted,
                'idle_balance_raw': idle_balance,
                'total_assets_raw': total_assets,
                'allocated_assets_raw': allocated_assets
            },
            'pools': {
                'count': len(whitelisted_pools),
                'balances': pool_balances
            },
            'withdrawals': {
                'pending_count': len(pending_withdrawals),
                'total_needed': total_withdrawal_needed,
                'requests': pending_withdrawals
            },
            'ratios': {
                'liquidity_ratio': round(liquidity_ratio, 2),
                'withdrawal_coverage': round(withdrawal_coverage, 2),
                'liquidity_status': liquidity_status,
                'withdrawal_status': withdrawal_status
            }
        }
        
    except Exception as e:
        logger.error(f"Error fetching protocol status: {e}")
        return {"error": f"Error fetching protocol status: {str(e)}"}

def execute_pool_investment(amount: int, pool_address: str) -> dict:
    """
    Execute investment transaction to a specific pool using AiAgent contract.
    
    Args:
        amount (int): Amount to invest in wei
        pool_address (str): Pool contract address to invest in
    
    Returns:
        dict: Transaction result with hash, status, and details
    """
    try:
        from data.utils.rpc_utils import get_web3_provider
        from data.utils.abis.ai_agent_abi import ai_agent_abi
        from django.conf import settings
        import os
        from web3 import Web3
        
        # Get Web3 instance
        w3 = get_web3_provider()
        if not w3:
            return {"success": False, "error": "Failed to connect to blockchain"}
        
        # Get contract addresses and private key from environment
        ai_agent_address = os.getenv('AI_AGENT_ADDRESS')
        compounding_wallet_private_key = os.getenv('COMPOUNDING_WALLET_PRIVATE_KEY')
        
        if not ai_agent_address or not compounding_wallet_private_key:
            return {"success": False, "error": "AI Agent address or compounding wallet private key not configured"}
        
        # Get executor address from private key
        executor_account = w3.eth.account.from_key(compounding_wallet_private_key)
        executor_address = executor_account.address
        
        # Create AI Agent contract instance
        ai_agent_contract = w3.eth.contract(
            address=Web3.to_checksum_address(ai_agent_address),
            abi=ai_agent_abi
        )
        
        # Validate pool address
        pool_address_checksum = Web3.to_checksum_address(pool_address)
        
        logger.info(f"=== Pool Investment Transaction ===")
        logger.info(f"Pool Address: {pool_address_checksum}")
        logger.info(f"Amount: {w3.from_wei(amount, 'ether'):.6f} tokens")
        logger.info(f"Executor: {executor_address}")
        
        # Get current nonce and gas price
        nonce = w3.eth.get_transaction_count(executor_address)
        gas_price = w3.eth.gas_price
        
        # Build deposit transaction using AiAgent contract
        deposit_tx = ai_agent_contract.functions.depositToPool(
            pool_address_checksum,
            amount  
        ).build_transaction({
            'from': executor_address,
            'gas': 300000,  # Conservative gas limit
            'gasPrice': gas_price,
            'nonce': nonce,
        })
        
        logger.info(f"Transaction built with gas: {deposit_tx['gas']}, gasPrice: {gas_price}")
        
        # Sign transaction
        signed_tx = w3.eth.account.sign_transaction(deposit_tx, compounding_wallet_private_key)
        
        # Get raw transaction data (handle different web3 versions)
        raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
        
        if not raw_tx:
            return {"success": False, "error": "Failed to get raw transaction data"}
        
        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()
        
        logger.info(f"Investment transaction sent: {tx_hash_hex}")
        
        # Wait for transaction receipt
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            if receipt.status == 1:
                logger.info(f"Investment transaction successful")
                
                # Calculate gas used and cost
                gas_used = receipt.gasUsed
                gas_cost_wei = gas_used * gas_price
                gas_cost_eth = w3.from_wei(gas_cost_wei, 'ether')
                
                return {
                    "success": True,
                    "transaction_hash": tx_hash_hex,
                    "pool_address": pool_address_checksum,
                    "amount_invested": amount,
                    "amount_invested_formatted": f"{w3.from_wei(amount, 'ether'):.6f}",
                    "gas_used": gas_used,
                    "gas_cost_wei": gas_cost_wei,
                    "gas_cost_eth": f"{gas_cost_eth:.6f}",
                    "block_number": receipt.blockNumber,
                    "executor_address": executor_address
                }
            else:
                logger.error(f"Investment transaction failed - status: {receipt.status}")
                return {
                    "success": False,
                    "error": "Transaction failed",
                    "transaction_hash": tx_hash_hex,
                    "receipt_status": receipt.status
                }
                
        except Exception as receipt_error:
            logger.error(f"Error waiting for transaction receipt: {receipt_error}")
            return {
                "success": False,
                "error": f"Transaction receipt error: {str(receipt_error)}",
                "transaction_hash": tx_hash_hex
            }
            
    except Exception as e:
        logger.error(f"Error executing pool investment: {e}")
        return {
            "success": False,
            "error": f"Investment execution error: {str(e)}"
        }

def execute_pool_withdrawal(amount: int, pool_address: str) -> dict:
    """
    Execute withdrawal transaction from a specific pool using AiAgent contract.
    
    Args:
        amount (int): Amount to withdraw in wei
        pool_address (str): Pool contract address to withdraw from
    
    Returns:
        dict: Transaction result with hash, status, and details
    """
    try:
        from data.utils.rpc_utils import get_web3_provider
        from data.utils.abis.ai_agent_abi import ai_agent_abi
        from django.conf import settings
        import os
        from web3 import Web3
        
        # Get Web3 instance
        w3 = get_web3_provider()
        if not w3:
            return {"success": False, "error": "Failed to connect to blockchain"}
        
        # Get contract addresses and private key from environment
        ai_agent_address = os.getenv('AI_AGENT_ADDRESS')
        compounding_wallet_private_key = os.getenv('COMPOUNDING_WALLET_PRIVATE_KEY')
        
        if not ai_agent_address or not compounding_wallet_private_key:
            return {"success": False, "error": "AI Agent address or compounding wallet private key not configured"}
        
        # Get executor address from private key
        executor_account = w3.eth.account.from_key(compounding_wallet_private_key)
        executor_address = executor_account.address
        
        # Create AI Agent contract instance
        ai_agent_contract = w3.eth.contract(
            address=Web3.to_checksum_address(ai_agent_address),
            abi=ai_agent_abi
        )
        
        # Validate pool address
        pool_address_checksum = Web3.to_checksum_address(pool_address)
        
        logger.info(f"=== Pool Withdrawal Transaction ===")
        logger.info(f"Pool Address: {pool_address_checksum}")
        logger.info(f"Amount: {w3.from_wei(amount, 'ether'):.6f} tokens")
        logger.info(f"Executor: {executor_address}")
        
        # Get current nonce and gas price
        nonce = w3.eth.get_transaction_count(executor_address)
        gas_price = w3.eth.gas_price
        
        # Build withdrawal transaction using AiAgent contract
        withdraw_tx = ai_agent_contract.functions.withdrawFromPool(
            pool_address_checksum,
            amount
        ).build_transaction({
            'from': executor_address,
            'gas': 300000,  # Conservative gas limit
            'gasPrice': gas_price,
            'nonce': nonce,
        })
        
        logger.info(f"Withdrawal transaction built with gas: {withdraw_tx['gas']}, gasPrice: {gas_price}")
        
        # Sign transaction
        signed_tx = w3.eth.account.sign_transaction(withdraw_tx, compounding_wallet_private_key)
        
        # Get raw transaction data (handle different web3 versions)
        raw_tx = getattr(signed_tx, 'raw_transaction', None) or getattr(signed_tx, 'rawTransaction', None)
        
        if not raw_tx:
            return {"success": False, "error": "Failed to get raw transaction data"}
        
        # Send transaction
        tx_hash = w3.eth.send_raw_transaction(raw_tx)
        tx_hash_hex = tx_hash.hex()
        
        logger.info(f"Withdrawal transaction sent: {tx_hash_hex}")
        
        # Wait for transaction receipt
        try:
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            if receipt.status == 1:
                logger.info(f"Withdrawal transaction successful")
                
                # Calculate gas used and cost
                gas_used = receipt.gasUsed
                gas_cost_wei = gas_used * gas_price
                gas_cost_eth = w3.from_wei(gas_cost_wei, 'ether')
                
                return {
                    "success": True,
                    "transaction_hash": tx_hash_hex,
                    "pool_address": pool_address_checksum,
                    "amount_withdrawn": amount,
                    "amount_withdrawn_formatted": f"{w3.from_wei(amount, 'ether'):.6f}",
                    "gas_used": gas_used,
                    "gas_cost_wei": gas_cost_wei,
                    "gas_cost_eth": f"{gas_cost_eth:.6f}",
                    "block_number": receipt.blockNumber,
                    "executor_address": executor_address
                }
            else:
                logger.error(f"Withdrawal transaction failed - status: {receipt.status}")
                return {
                    "success": False,
                    "error": "Transaction failed",
                    "transaction_hash": tx_hash_hex,
                    "receipt_status": receipt.status
                }
                
        except Exception as receipt_error:
            logger.error(f"Error waiting for transaction receipt: {receipt_error}")
            return {
                "success": False,
                "error": f"Transaction receipt error: {str(receipt_error)}",
                "transaction_hash": tx_hash_hex
            }
            
    except Exception as e:
        logger.error(f"Error executing pool withdrawal: {e}")
        return {
            "success": False,
            "error": f"Withdrawal execution error: {str(e)}"
        }