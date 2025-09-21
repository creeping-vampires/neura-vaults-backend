"""
Yield Monitor Worker - Automated Yield Claiming and Reinvestment
Monitors smart contract yields and automatically claims and reinvests when above threshold
Based on the TypeScript implementation for claim-and-reinvest-yield.ts
"""
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import json


# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Configure Django BEFORE importing any Django models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

import django
django.setup()

from web3 import Web3
from data.utils.rpc_utils import get_web3_provider
from data.data_access_layer import OptimizationResultDAO
from data.models import YieldMonitorRun, YieldMonitorPoolSnapshot, YieldMonitorTransaction, YieldMonitorMetrics

# Import the correct ABIs
from data.utils.abis.ai_agent_abi import ai_agent_abi
from data.utils.abis.yield_allocator_abi import yield_allocator_abi
from data.utils.abis.whitelist_registry import whitelist_registry_abi

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class YieldMonitorWorker:
    """
    Worker that monitors yield farming positions and automatically claims/reinvests
    Uses the same logic as the TypeScript claim-and-reinvest-yield.ts script
    """
    
    def __init__(self):
        """Initialize the yield monitor worker"""
        # Load environment variables
        self.rpc_url = os.getenv('RPC_URL')
        self.executor_private_key = os.getenv('EXECUTOR_PRIVATE_KEY')
        self.whitelist_registry_address = os.getenv('WHITELIST_REGISTRY_ADDRESS')
        # USDe vault
        self.yield_allocator_vault_address = os.getenv('YIELD_ALLOCATOR_VAULT_ADDRESS')
        self.ai_agent_address = os.getenv('AI_AGENT_ADDRESS')
        # USDT0 vault
        self.yield_allocator_vault_address_usdt0 = os.getenv('YIELD_ALLOCATOR_VAULT_ADDRESS_USDT0')
        self.ai_agent_address_usdt0 = os.getenv('AI_AGENT_ADDRESS_USDT0')
        
        # Log all environment variables for debugging
        logger.info("=== Environment Variables ===")
        logger.info(f"RPC_URL: {self.rpc_url}")
        logger.info(f"COMPOUNDING_WALLET_PRIVATE_KEY: {'***' if self.executor_private_key else 'NOT SET'}")
        logger.info(f"WHITELIST_REGISTRY_ADDRESS: {self.whitelist_registry_address}")
        logger.info(f"YIELD_ALLOCATOR_VAULT_ADDRESS: {self.yield_allocator_vault_address}")
        logger.info(f"AI_AGENT_ADDRESS: {self.ai_agent_address}")

        logger.info(f"YIELD_ALLOCATOR_VAULT_ADDRESS_USDT0: {self.yield_allocator_vault_address_usdt0}")
        logger.info(f"AI_AGENT_ADDRESS_USDT0: {self.ai_agent_address_usdt0}")
        
        # Validate addresses are proper hex format
        addresses_to_validate = [
            ("WHITELIST_REGISTRY_ADDRESS", self.whitelist_registry_address),
            ("YIELD_ALLOCATOR_VAULT_ADDRESS", self.yield_allocator_vault_address),
            ("AI_AGENT_ADDRESS", self.ai_agent_address),
            ("YIELD_ALLOCATOR_VAULT_ADDRESS_USDT0", self.yield_allocator_vault_address_usdt0),
            ("AI_AGENT_ADDRESS_USDT0", self.ai_agent_address_usdt0)
        ]
        
        for name, address in addresses_to_validate:
            if address:
                logger.info(f"Validating {name}: {address}")
                if not address.startswith('0x'):
                    logger.error(f"{name} does not start with 0x: {address}")
                    raise ValueError(f"Invalid address format for {name}: {address}")
                if len(address) != 42:
                    logger.error(f"{name} is not 42 characters long: {address} (length: {len(address)})")
                    raise ValueError(f"Invalid address length for {name}: {address}")
                try:
                    # Test hex conversion
                    int(address, 16)
                    logger.info(f"{name} is valid hex format")
                except ValueError as e:
                    logger.error(f"{name} contains non-hex characters: {address}")
                    raise ValueError(f"Invalid hex format for {name}: {address}")
            else:
                logger.error(f"{name} is not set")
                raise ValueError(f"Missing required environment variable: {name}")
        
        # Configuration parameters
        self.yield_threshold = float(os.getenv('YIELD_THRESHOLD', '0.00001'))  # 0.1% default (lower for frequent claiming)
        self.min_claim_amount_usd = float(os.getenv('MIN_CLAIM_AMOUNT', '0.1'))  # $1 minimum (lower for testing)
        self.gas_price_gwei = int(os.getenv('GAS_PRICE_GWEI', '20'))
        self.max_gas_cost_usd = float(os.getenv('MAX_GAS_COST_USD', '5'))  # $5 maximum gas cost
        
        logger.info("=== Configuration Parameters ===")
        logger.info(f"Yield threshold: {self.yield_threshold*100}%")
        logger.info(f"Min claim amount: ${self.min_claim_amount_usd}")
        logger.info(f"Max gas cost: ${self.max_gas_cost_usd}")
        
        # Initialize Web3 connection
        logger.info("=== Initializing Web3 Connection ===")
        self.web3 = self._setup_web3_connection()
        
        # Initialize account
        logger.info("=== Setting up Account ===")
        self.executor_account = self.web3.eth.account.from_key(self.executor_private_key)
        self.executor_address = self.executor_account.address
        logger.info(f"Executor account address: {self.executor_address}")
        
        # Initialize DAO
        self.dao = OptimizationResultDAO()
        
        logger.info(f"Yield Monitor Worker initialized")
        logger.info(f"Executor address: {self.executor_address}")
        logger.info(f"Registry: {self.whitelist_registry_address}")
        logger.info(f"Vault USDe: {self.yield_allocator_vault_address}")
        logger.info(f"AI Agent USDe: {self.ai_agent_address}")
        logger.info(f"Vault USDT0: {self.yield_allocator_vault_address_usdt0}")
        logger.info(f"AI Agent USDT0: {self.ai_agent_address_usdt0}")
    
    def _setup_web3_connection(self) -> Web3:
        """Setup Web3 connection using existing rpc_utils"""
        try:
            web3 = get_web3_provider()
            
            if not web3.is_connected():
                logger.error("Failed to connect to blockchain via rpc_utils")
                raise ConnectionError("Could not connect to blockchain")
                
            logger.info(f"Connected to blockchain via rpc_utils")
            return web3
            
        except Exception as e:
            logger.error(f"Error setting up Web3 connection: {str(e)}")
            raise
    
    def get_contract_abis(self) -> Dict[str, List[Dict]]:
        """Get ABIs for all required contracts from the utils/abis folder"""
        return {
            'AIAgent': ai_agent_abi,
            'WhitelistRegistry': whitelist_registry_abi,
            'YieldAllocatorVault': yield_allocator_abi,
            'ERC20': [
                {
                    "inputs": [{"name": "account", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "stateMutability": "view",
                    "type": "function"
                },
                {
                    "inputs": [],
                    "name": "symbol",
                    "outputs": [{"name": "", "type": "string"}],
                    "stateMutability": "view",
                    "type": "function"
                },
                {
                    "inputs": [],
                    "name": "decimals",
                    "outputs": [{"name": "", "type": "uint8"}],
                    "stateMutability": "view",
                    "type": "function"
                }
            ]
        }
    
    def get_whitelisted_pools(self) -> List[str]:
        """Get all whitelisted pools from the registry"""
        try:
            abis = self.get_contract_abis()
            registry_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.whitelist_registry_address),
                abi=abis['WhitelistRegistry']
            )
            
            pools = registry_contract.functions.getWhitelistedPools().call()
            logger.info(f"Found {len(pools)} whitelisted pools")
            return pools
            
        except Exception as e:
            logger.error(f"Error getting whitelisted pools: {str(e)}")
            return []
    
    def calculate_vault_yield_info(self, pools: List[str], vault_address: str) -> Dict:
        """Calculate vault-level yield information"""
        try:
            abis = self.get_contract_abis()
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(vault_address),
                abi=abis['YieldAllocatorVault']
            )
            
            # Get asset token info
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=abis['ERC20']
            )
            
            asset_symbol = asset_contract.functions.symbol().call()
            asset_decimals = asset_contract.functions.decimals().call()
            
            # Get current total value (including yield)
            current_total_value = vault_contract.functions.totalAssets().call()
            
            # Get idle assets (part of principal)
            idle_assets = asset_contract.functions.balanceOf(
                self.web3.to_checksum_address(vault_address)
            ).call()
            
            # Calculate total principal deposited (sum of all poolPrincipal + idle)
            total_principal_deposited = idle_assets
            pool_principals = {}
            
            for pool in pools:
                pool_checksum = self.web3.to_checksum_address(pool)
                principal = vault_contract.functions.poolPrincipal(pool_checksum).call()
                pool_principals[pool] = principal
                total_principal_deposited += principal
            
            # Calculate total yield at vault level
            total_yield_generated = max(0, current_total_value - total_principal_deposited)
            total_yield_percentage = (total_yield_generated * 10000 // total_principal_deposited) / 100 if total_principal_deposited > 0 else 0
            
            logger.info(f"=== Vault-Level Yield Analysis ===")
            logger.info(f"Asset: {asset_symbol} ({asset_decimals} decimals)")
            logger.info(f"Total principal deposited: {self.web3.from_wei(total_principal_deposited, 'ether'):.6f} {asset_symbol}")
            logger.info(f"Current total value: {self.web3.from_wei(current_total_value, 'ether'):.6f} {asset_symbol}")
            logger.info(f"Total yield generated: {self.web3.from_wei(total_yield_generated, 'ether'):.6f} {asset_symbol}")
            logger.info(f"Total yield percentage: {total_yield_percentage:.4f}%")
            logger.info(f"Idle assets: {self.web3.from_wei(idle_assets, 'ether'):.6f} {asset_symbol}")
            
            return {
                'asset_address': asset_address,
                'asset_symbol': asset_symbol,
                'asset_decimals': asset_decimals,
                'current_total_value': current_total_value,
                'total_principal_deposited': total_principal_deposited,
                'total_yield_generated': total_yield_generated,
                'total_yield_percentage': total_yield_percentage,
                'idle_assets': idle_assets,
                'pool_principals': pool_principals
            }
            
        except Exception as e:
            logger.error(f"Error calculating vault yield info: {str(e)}")
            return {}

    def should_claim_yield(self, yield_info: Dict) -> Tuple[bool, str]:
        """Determine if yield should be claimed based on vault-level analysis"""
        if not yield_info:
            return False, "No yield info available"
        
        total_yield = yield_info.get('total_yield_generated', 0)
        yield_percentage = yield_info.get('total_yield_percentage', 0)
        
        if total_yield == 0:
            return False, "No yield generated"
        
        # Check yield threshold
        if yield_percentage < self.yield_threshold * 100:
            return False, f"Yield {yield_percentage:.4f}% below threshold {self.yield_threshold * 100}%"
        
        # Check minimum claim amount in USD
        yield_eth = float(self.web3.from_wei(total_yield, 'ether'))
        eth_price_usd = float(os.getenv('ETH_PRICE_USD', '4500'))
        yield_usd = yield_eth * eth_price_usd
        
        if yield_usd < self.min_claim_amount_usd:
            return False, f"Yield ${yield_usd:.2f} below minimum ${self.min_claim_amount_usd}"
        
        # Check gas cost
        gas_cost = self.estimate_gas_cost_usd()
        if gas_cost > self.max_gas_cost_usd:
            return False, f"Gas cost ${gas_cost:.2f} exceeds maximum ${self.max_gas_cost_usd}"
        
        return True, f"Yield {yield_percentage:.4f}% meets criteria for claiming"

    def withdraw_and_reinvest_yield(self, yield_info: Dict, vault_address: str, agent_address: str) -> Dict:
        """Withdraw yield proportionally from pools and reinvest"""
        try:
            abis = self.get_contract_abis()
            ai_agent_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(agent_address),
                abi=abis['AIAgent']
            )
            
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(yield_info['asset_address']),
                abi=abis['ERC20']
            )
            
            total_yield = yield_info['total_yield_generated']
            total_principal = yield_info['total_principal_deposited']
            pool_principals = yield_info['pool_principals']
            asset_symbol = yield_info['asset_symbol']
            
            logger.info(f"=== Yield Withdrawal and Reinvestment ===")
            logger.info(f"Total yield available: {self.web3.from_wei(total_yield, 'ether'):.6f} {asset_symbol}")
            
            total_withdrawn = 0
            total_reinvested = 0
            pool_results = {}
            
            for pool_address, principal in pool_principals.items():
                if principal == 0:
                    continue
                
                # Calculate this pool's share of total principal
                pool_share = (principal * 10000 // total_principal) / 100 if total_principal > 0 else 0
                pool_yield_share = (total_yield * principal) // total_principal if total_principal > 0 else 0
                
                if pool_yield_share == 0:
                    continue
                
                logger.info(f"\nPool {pool_address}:")
                logger.info(f"  Principal: {self.web3.from_wei(principal, 'ether'):.6f} {asset_symbol}")
                logger.info(f"  Share of total principal: {pool_share:.2f}%")
                logger.info(f"  Share of yield: {self.web3.from_wei(pool_yield_share, 'ether'):.6f} {asset_symbol}")
                
                try:
                    # Get vault balance before withdrawal
                    vault_balance_before = asset_contract.functions.balanceOf(
                        self.web3.to_checksum_address(vault_address)
                    ).call()
                    
                    # Build withdrawal transaction
                    nonce = self.web3.eth.get_transaction_count(self.executor_address)
                    gas_price = self.web3.eth.gas_price
                    
                    withdraw_tx = ai_agent_contract.functions.withdrawFromPool(
                        self.web3.to_checksum_address(pool_address),
                        pool_yield_share
                    ).build_transaction({
                        'from': self.executor_address,
                        'gas': 300000,
                        'gasPrice': gas_price,
                        'nonce': nonce,
                    })
                    
                    # Sign and send withdrawal transaction
                    signed_withdraw_tx = self.web3.eth.account.sign_transaction(withdraw_tx, self.executor_private_key)
                    raw_tx = getattr(signed_withdraw_tx, 'raw_transaction', None) or getattr(signed_withdraw_tx, 'rawTransaction', None)
                    withdraw_tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
                    
                    logger.info(f"  Withdrawal transaction: {withdraw_tx_hash.hex()}")
                    withdraw_receipt = self.web3.eth.wait_for_transaction_receipt(withdraw_tx_hash, timeout=300)
                    
                    if withdraw_receipt.status != 1:
                        logger.error(f"  Withdrawal transaction failed")
                        pool_results[pool_address] = {'success': False, 'error': 'Withdrawal failed'}
                        continue
                    
                    # Get vault balance after withdrawal
                    vault_balance_after = asset_contract.functions.balanceOf(
                        self.web3.to_checksum_address(vault_address)
                    ).call()
                    
                    actual_withdrawn = vault_balance_after - vault_balance_before
                    logger.info(f"  Actually withdrawn: {self.web3.from_wei(actual_withdrawn, 'ether'):.6f} {asset_symbol}")
                    
                    if actual_withdrawn > 0:
                        # Build reinvestment transaction
                        nonce = self.web3.eth.get_transaction_count(self.executor_address)
                        
                        deposit_tx = ai_agent_contract.functions.depositToPool(
                            self.web3.to_checksum_address(pool_address),
                            actual_withdrawn
                        ).build_transaction({
                            'from': self.executor_address,
                            'gas': 300000,
                            'gasPrice': gas_price,
                            'nonce': nonce,
                        })
                        
                        # Sign and send reinvestment transaction
                        signed_deposit_tx = self.web3.eth.account.sign_transaction(deposit_tx, self.executor_private_key)
                        raw_tx = getattr(signed_deposit_tx, 'raw_transaction', None) or getattr(signed_deposit_tx, 'rawTransaction', None)
                        deposit_tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
                        
                        logger.info(f"  Reinvestment transaction: {deposit_tx_hash.hex()}")
                        deposit_receipt = self.web3.eth.wait_for_transaction_receipt(deposit_tx_hash, timeout=300)
                        
                        if deposit_receipt.status == 1:
                            logger.info(f"  Successfully reinvested: {self.web3.from_wei(actual_withdrawn, 'ether'):.6f} {asset_symbol}")
                            total_withdrawn += actual_withdrawn
                            total_reinvested += actual_withdrawn
                            
                            pool_results[pool_address] = {
                                'success': True,
                                'withdrawn': actual_withdrawn,
                                'reinvested': actual_withdrawn,
                                'withdraw_tx': withdraw_tx_hash.hex(),
                                'deposit_tx': deposit_tx_hash.hex()
                            }
                        else:
                            logger.error(f"  Reinvestment transaction failed")
                            pool_results[pool_address] = {'success': False, 'error': 'Reinvestment failed'}
                    else:
                        logger.info(f"  No yield was actually withdrawn from the pool")
                        pool_results[pool_address] = {'success': False, 'error': 'No yield withdrawn'}
                        
                except Exception as e:
                    logger.error(f"  Error processing pool {pool_address}: {str(e)}")
                    pool_results[pool_address] = {'success': False, 'error': str(e)}
            
            logger.info(f"\n=== Summary ===")
            logger.info(f"Total yield calculated: {self.web3.from_wei(total_yield, 'ether'):.6f} {asset_symbol}")
            logger.info(f"Total yield withdrawn: {self.web3.from_wei(total_withdrawn, 'ether'):.6f} {asset_symbol}")
            logger.info(f"Total yield reinvested: {self.web3.from_wei(total_reinvested, 'ether'):.6f} {asset_symbol}")
            
            return {
                'success': total_withdrawn > 0,
                'total_yield_calculated': total_yield,
                'total_withdrawn': total_withdrawn,
                'total_reinvested': total_reinvested,
                'pool_results': pool_results
            }
            
        except Exception as e:
            logger.error(f"Error in yield withdrawal and reinvestment: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def estimate_gas_cost_usd(self, gas_limit: int = 200000) -> float:
        """Estimate gas cost for a transaction in USD"""
        try:
            gas_price = self.web3.eth.gas_price
            gas_cost_wei = gas_price * gas_limit
            gas_cost_eth = self.web3.from_wei(gas_cost_wei, 'ether')
            
            # Convert to USD (simplified - in production use price oracle)
            eth_price_usd = float(os.getenv('ETH_PRICE_USD', '4500'))
            gas_cost_usd = float(gas_cost_eth) * eth_price_usd
            
            return gas_cost_usd
            
        except Exception as e:
            logger.error(f"Error estimating gas cost: {str(e)}")
            return self.max_gas_cost_usd
    
    def find_block_by_timestamp(self, target_timestamp: int, tolerance: int = 1800) -> Optional[int]:
        """
        Binary search to find a block number close to the target timestamp.
        
        Args:
            target_timestamp: Unix timestamp to search for
            tolerance: Acceptable time difference in seconds (default 30 minutes)
            
        Returns:
            Block number or None if not found within tolerance
        """
        try:
            # Get current block as upper bound
            latest_block = self.web3.eth.get_block('latest')
            high = latest_block.number
            low = max(0, high - 100000)  # Search within last ~100k blocks
            
            logger.info(f"Searching for block near timestamp {target_timestamp} between blocks {low}-{high}")
            
            best_block = None
            best_diff = float('inf')
            
            while low <= high:
                mid = (low + high) // 2
                try:
                    block = self.web3.eth.get_block(mid)
                    block_timestamp = block.timestamp
                    diff = abs(block_timestamp - target_timestamp)
                    
                    if diff < best_diff:
                        best_diff = diff
                        best_block = mid
                    
                    if diff <= tolerance:
                        logger.info(f"Found block {mid} with timestamp {block_timestamp} (diff: {diff}s)")
                        return mid
                    elif block_timestamp < target_timestamp:
                        low = mid + 1
                    else:
                        high = mid - 1
                        
                except Exception as e:
                    logger.warning(f"Error fetching block {mid}: {str(e)}")
                    # Skip this block and continue search
                    if block_timestamp < target_timestamp:
                        low = mid + 1
                    else:
                        high = mid - 1
            
            # For very new blockchains, be more flexible with tolerance
            # Accept any block within the available history (up to 24 hours difference)
            if best_block and best_diff <= 86400:
                logger.info(f"Returning best match block {best_block} with {best_diff}s difference (flexible tolerance for new blockchain)")
                return best_block
                
            logger.warning(f"Could not find block within tolerance. Best match: block {best_block}, diff: {best_diff}s")
            return None
            
        except Exception as e:
            logger.error(f"Error in find_block_by_timestamp: {str(e)}")
            return None
    
    def calculate_vault_apr_apy(self, vault_address: str, window_days: int = 1) -> Dict:
        """
        Calculate APR and APY for a vault using price per share method.
        
        Args:
            vault_address: Address of the vault contract
            window_days: Number of days to look back for calculation
            
        Returns:
            Dictionary with calculation results and metadata
        """
        try:
            logger.info(f"Calculating APR/APY for vault {vault_address} over {window_days} days")
            
            # Get vault contract
            vault_contract = self.web3.eth.contract(
                address=vault_address,
                abi=yield_allocator_abi
            )
            
            # Get current block and timestamp
            current_block = self.web3.eth.get_block('latest')
            current_timestamp = current_block.timestamp
            
            # Calculate target timestamp (window_days ago)
            seconds_in_day = 24 * 60 * 60
            target_timestamp = current_timestamp - (window_days * seconds_in_day)
            
            # Find block near target timestamp
            start_block_num = self.find_block_by_timestamp(target_timestamp)
            if not start_block_num:
                return {
                    'success': False,
                    'error': f'Could not find block for timestamp {window_days} days ago',
                    'vault_address': vault_address,
                    'window_days': window_days
                }
            
            # Get current price per share (totalAssets / totalSupply)
            try:
                current_total_assets = vault_contract.functions.totalAssets().call()
                current_total_supply = vault_contract.functions.totalSupply().call()
                
                if current_total_supply == 0:
                    return {
                        'success': False,
                        'error': 'Vault has zero total supply',
                        'vault_address': vault_address,
                        'window_days': window_days
                    }
                
                current_pps = current_total_assets / current_total_supply
                
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Error getting current vault data: {str(e)}',
                    'vault_address': vault_address,
                    'window_days': window_days
                }
            
            # Get historical price per share
            try:
                start_total_assets = vault_contract.functions.totalAssets().call(block_identifier=start_block_num)
                start_total_supply = vault_contract.functions.totalSupply().call(block_identifier=start_block_num)
                
                if start_total_supply == 0:
                    return {
                        'success': False,
                        'error': 'Vault had zero total supply at start of period',
                        'vault_address': vault_address,
                        'window_days': window_days
                    }
                
                start_pps = start_total_assets / start_total_supply
                
            except Exception as e:
                return {
                    'success': False,
                    'error': f'Error getting historical vault data: {str(e)}',
                    'vault_address': vault_address,
                    'window_days': window_days
                }
            
            # Calculate period return
            if start_pps == 0:
                return {
                    'success': False,
                    'error': 'Start price per share is zero',
                    'vault_address': vault_address,
                    'window_days': window_days
                }
            
            period_return = (current_pps - start_pps) / start_pps
            
            # Calculate APR (simple interest)
            days_in_year = 365
            apr = period_return * (days_in_year / window_days)
            
            # Calculate APY (compound interest)
            # APY = (1 + period_return)^(365/window_days) - 1
            apy = ((1 + period_return) ** (days_in_year / window_days)) - 1
            
            logger.info(f"APR calculation successful:")
            logger.info(f"  Period: {window_days} days")
            logger.info(f"  Start PPS: {start_pps:.18f}")
            logger.info(f"  Current PPS: {current_pps:.18f}")
            logger.info(f"  Period Return: {period_return*100:.6f}%")
            logger.info(f"  APR: {apr*100:.6f}%")
            logger.info(f"  APY: {apy*100:.6f}%")
            
            return {
                'success': True,
                'vault_address': vault_address,
                'window_days': window_days,
                'pps_start': start_pps,
                'pps_end': current_pps,
                'block_start': start_block_num,
                'block_end': current_block.number,
                'period_return': period_return,
                'apr': apr,
                'apy': apy,
                'rpc_url': self.rpc_url
            }
            
        except Exception as e:
            logger.error(f"Error calculating vault APR/APY: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'vault_address': vault_address,
                'window_days': window_days
            }
    
    def save_pool_apr_data(self, apr_data: Dict):
        """
        Save APR/APY calculation results to the PoolAPR table.
        
        Args:
            apr_data: Dictionary containing APR calculation results
        """
        try:
            from data.models import PoolAPR
            from decimal import Decimal
            
            # Determine calculation status
            status = 'success' if apr_data.get('success', False) else 'failed'
            
            # Create PoolAPR record
            pool_apr = PoolAPR(
                pool_address=apr_data.get('vault_address', ''),
                pool_name='YieldAllocatorVault',  # Default name for the vault
                calculation_window_days=apr_data.get('window_days', 7),
                calculation_status=status,
                rpc_url=apr_data.get('rpc_url', self.rpc_url)
            )
            
            if status == 'success':
                # Set successful calculation data
                pool_apr.pps_start = Decimal(str(apr_data['pps_start']))
                pool_apr.pps_end = Decimal(str(apr_data['pps_end']))
                pool_apr.block_start = apr_data['block_start']
                pool_apr.block_end = apr_data['block_end']
                pool_apr.period_return = Decimal(str(apr_data['period_return']))
                pool_apr.apr = Decimal(str(apr_data['apr']))
                pool_apr.apy = Decimal(str(apr_data['apy']))
            else:
                # Set error data for failed calculations
                pool_apr.error_message = apr_data.get('error', 'Unknown error')
                # Set default values for required fields
                pool_apr.pps_start = Decimal('0')
                pool_apr.pps_end = Decimal('0')
                pool_apr.block_start = 0
                pool_apr.block_end = 0
                pool_apr.period_return = Decimal('0')
                pool_apr.apr = Decimal('0')
                pool_apr.apy = Decimal('0')
            
            pool_apr.save()
            
            logger.info(f"Saved PoolAPR record with status: {status}")
            if status == 'success':
                logger.info(f"  APR: {apr_data['apr']*100:.4f}%, APY: {apr_data['apy']*100:.4f}%")
            else:
                logger.info(f"  Error: {apr_data.get('error', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"Error saving PoolAPR data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    def save_monitoring_results(self, yield_info: Dict, result: Dict, start_time: float):
        """Save comprehensive monitoring results to database"""
        try:
            from datetime import datetime
            from django.utils import timezone
            
            end_time = time.time()
            execution_duration = end_time - start_time
            
            # Determine run status
            if result.get('success', False):
                if result.get('total_withdrawn', 0) > 0:
                    status = YieldMonitorRun.StatusChoices.SUCCESS
                else:
                    status = YieldMonitorRun.StatusChoices.SKIPPED
            else:
                status = YieldMonitorRun.StatusChoices.FAILED
            
            # Create the main run record
            monitor_run = YieldMonitorRun.objects.create(
                status=status,
                vault_address=self.yield_allocator_vault_address,
                asset_address=yield_info.get('asset_address', ''),
                asset_symbol=yield_info.get('asset_symbol', ''),
                asset_decimals=yield_info.get('asset_decimals', 18),
                total_principal_deposited=yield_info.get('total_principal_deposited', 0),
                current_total_value=yield_info.get('current_total_value', 0),
                total_yield_generated=yield_info.get('total_yield_generated', 0),
                total_yield_percentage=yield_info.get('total_yield_percentage', 0),
                idle_assets=yield_info.get('idle_assets', 0),
                total_withdrawn=result.get('total_withdrawn', 0),
                total_reinvested=result.get('total_reinvested', 0),
                pools_processed=len(yield_info.get('pool_principals', {})),
                pools_with_yield=len([p for p in result.get('pool_results', {}).values() if p.get('success', False)]),
                yield_threshold_used=self.yield_threshold,
                min_claim_amount_usd=self.min_claim_amount_usd,
                max_gas_cost_usd=self.max_gas_cost_usd,
                error_message=result.get('error') if not result.get('success', False) else None,
                execution_duration_seconds=execution_duration
            )
            
            # Create pool snapshots
            pool_principals = yield_info.get('pool_principals', {})
            total_principal = yield_info.get('total_principal_deposited', 1)  # Avoid division by zero
            total_yield = yield_info.get('total_yield_generated', 0)
            
            for pool_address, principal in pool_principals.items():
                # Calculate pool's share of yield
                pool_yield_share = (total_yield * principal) // total_principal if total_principal > 0 else 0
                principal_percentage = (principal * 10000 // total_principal) / 100 if total_principal > 0 else 0
                yield_percentage = (pool_yield_share * 10000 // principal) / 100 if principal > 0 else 0
                
                # Check if pool was processed
                pool_result = result.get('pool_results', {}).get(pool_address, {})
                was_processed = pool_result.get('success', False)
                skip_reason = pool_result.get('error') if not was_processed else None
                
                pool_snapshot = YieldMonitorPoolSnapshot.objects.create(
                    monitor_run=monitor_run,
                    pool_address=pool_address,
                    principal_deposited=principal,
                    principal_percentage=principal_percentage,
                    calculated_yield_share=pool_yield_share,
                    yield_percentage=yield_percentage,
                    was_processed=was_processed,
                    skip_reason=skip_reason
                )
                
                # Create transaction records if pool was processed
                if was_processed and pool_result.get('success', False):
                    # Withdrawal transaction
                    if pool_result.get('withdraw_tx'):
                        YieldMonitorTransaction.objects.create(
                            monitor_run=monitor_run,
                            pool_snapshot=pool_snapshot,
                            transaction_type=YieldMonitorTransaction.TransactionType.WITHDRAWAL,
                            transaction_hash=pool_result['withdraw_tx'],
                            amount_wei=pool_result.get('withdrawn', 0),
                            amount_formatted=float(self.web3.from_wei(pool_result.get('withdrawn', 0), 'ether')),
                            status=YieldMonitorTransaction.TransactionStatus.SUCCESS
                        )
                    
                    # Deposit transaction
                    if pool_result.get('deposit_tx'):
                        YieldMonitorTransaction.objects.create(
                            monitor_run=monitor_run,
                            pool_snapshot=pool_snapshot,
                            transaction_type=YieldMonitorTransaction.TransactionType.DEPOSIT,
                            transaction_hash=pool_result['deposit_tx'],
                            amount_wei=pool_result.get('reinvested', 0),
                            amount_formatted=float(self.web3.from_wei(pool_result.get('reinvested', 0), 'ether')),
                            status=YieldMonitorTransaction.TransactionStatus.SUCCESS
                        )
            
            # Update daily metrics
            self.update_daily_metrics(monitor_run, yield_info, result)
            
            logger.info(f"✅ Saved monitoring results to database (Run ID: {monitor_run.id})")
            logger.info(f"   - Status: {status}")
            logger.info(f"   - Pools processed: {monitor_run.pools_processed}")
            logger.info(f"   - Pools with yield: {monitor_run.pools_with_yield}")
            logger.info(f"   - Total transactions: {monitor_run.transactions.count()}")
            logger.info(f"   - Execution time: {execution_duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Error saving monitoring results: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

    def update_daily_metrics(self, monitor_run: 'YieldMonitorRun', yield_info: Dict, result: Dict):
        """Update or create daily aggregated metrics"""
        try:
            from datetime import date
            from django.db.models import F
            
            today = date.today()
            vault_address = self.yield_allocator_vault_address
            
            # Get or create daily metrics
            metrics, created = YieldMonitorMetrics.objects.get_or_create(
                date=today,
                vault_address=vault_address,
                defaults={
                    'total_runs': 0,
                    'successful_runs': 0,
                    'failed_runs': 0,
                    'total_yield_claimed': 0,
                    'total_yield_reinvested': 0,
                    'average_yield_percentage': 0,
                    'total_transactions': 0,
                    'total_gas_cost_usd': 0,
                    'average_execution_time': 0,
                    'daily_growth_percentage': 0,
                }
            )
            
            # Update run counts
            metrics.total_runs = F('total_runs') + 1
            if monitor_run.status == YieldMonitorRun.StatusChoices.SUCCESS:
                metrics.successful_runs = F('successful_runs') + 1
            else:
                metrics.failed_runs = F('failed_runs') + 1
            
            # Update yield metrics
            if result.get('success', False):
                metrics.total_yield_claimed = F('total_yield_claimed') + result.get('total_withdrawn', 0)
                metrics.total_yield_reinvested = F('total_yield_reinvested') + result.get('total_reinvested', 0)
            
            # Update transaction count
            metrics.total_transactions = F('total_transactions') + monitor_run.transactions.count()
            
            # Update execution time (simple average - could be improved with weighted average)
            if monitor_run.execution_duration_seconds:
                current_avg = metrics.average_execution_time or 0
                new_avg = (current_avg * (metrics.total_runs - 1) + monitor_run.execution_duration_seconds) / metrics.total_runs
                metrics.average_execution_time = new_avg
            
            # Set vault values for growth calculation
            current_value = yield_info.get('current_total_value', 0)
            if not metrics.vault_value_start:
                metrics.vault_value_start = current_value
            metrics.vault_value_end = current_value
            
            # Calculate daily growth percentage
            if metrics.vault_value_start and metrics.vault_value_start > 0:
                growth = ((metrics.vault_value_end - metrics.vault_value_start) * 10000 // metrics.vault_value_start) / 100
                metrics.daily_growth_percentage = growth
            
            metrics.save()
            
            logger.info(f"📊 Updated daily metrics for {today}")
            
        except Exception as e:
            logger.error(f"Error updating daily metrics: {str(e)}")

    
    def get_best_apy(self, underlying_token_symbol: str):
        """
        Get the best APY for a given token from HyperLend and HypurrFi
        """
        from data.models import YieldReport
        
        hyperlend_reports = YieldReport.objects.filter(
            token__icontains=underlying_token_symbol,
            protocol__icontains='HyperLend'
        ).order_by('-created_at')
        hypurrfi_reports = YieldReport.objects.filter(
            token__icontains=underlying_token_symbol,
            protocol__icontains='HypurrFi'
        ).order_by('-created_at')
        felix_reports = YieldReport.objects.filter(
            token__icontains=underlying_token_symbol,
            protocol__icontains='Felix'
        ).order_by('-created_at')
        
        # Initialize variables to track highest APY and its protocol
        highest_apy = Decimal('0')
        highest_apy_protocol = None
        
        # Check HyperLend APY
        if hyperlend_reports.exists():
            latest_hyperlend = hyperlend_reports.first()
            logger.info(f"Latest HyperLend APY: {latest_hyperlend.apy}%")
            if latest_hyperlend.apy > highest_apy:
                highest_apy = latest_hyperlend.apy
                highest_apy_protocol = latest_hyperlend.protocol
        else:
            logger.warning("No HyperLend yield reports found")
            
        # Check HypurrFi APY
        if hypurrfi_reports.exists():
            latest_hypurrfi = hypurrfi_reports.first()
            logger.info(f"Latest HypurrFi APY: {latest_hypurrfi.apy}%")
            if latest_hypurrfi.apy > highest_apy:
                highest_apy = latest_hypurrfi.apy
                highest_apy_protocol = latest_hypurrfi.protocol
        else:
            logger.warning("No HypurrFi yield reports found")
            
        # Check Felix APY
        if felix_reports.exists():
            latest_felix = felix_reports.first()
            logger.info(f"Latest Felix APY: {latest_felix.apy}%")
            if latest_felix.apy > highest_apy:
                highest_apy = latest_felix.apy
                highest_apy_protocol = latest_felix.protocol
        else:
            logger.warning("No Felix yield reports found")
            
        # Log the highest APY found
        if highest_apy_protocol:
            logger.info(f"Highest APY: {highest_apy_protocol} with {highest_apy}%")
            return highest_apy, highest_apy_protocol
        else:
            logger.warning("No yield reports found for HyperLend or HypurrFi or Felix")
            return Decimal('0'), None
            
    
    def calculate_and_store_vault_price(self, underlying_token_symbol: str, vault_address: str):
        """
        Calculate and store vault price data:
        1. Get highest APY from HyperLend and HypurrFi
        2. Calculate share price from vault contract
        3. Store results in VaultPrice model
        """
        from data.models import YieldReport, VaultPrice
        from decimal import Decimal
        import logging

        logger = logging.getLogger(__name__)
        logger.info("Calculating and storing vault price data...")

        try:
            # 1. Get highest APY from HyperLend and HypurrFi
            pool_apy, highest_apy_protocol = self.get_best_apy(underlying_token_symbol)

            # 2. Calculate share price from vault contract
            abis = self.get_contract_abis()
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(vault_address),
                abi=abis['YieldAllocatorVault']
            )
      
            
            # Get share price from vault contract
            share_price = vault_contract.functions.sharePrice().call()
            total_assets = vault_contract.functions.totalAssets().call()
            total_supply = vault_contract.functions.totalSupply().call()
            asset_address = vault_contract.functions.asset().call()

            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=abis['ERC20']
            )

            asset_decimals = asset_contract.functions.decimals().call()
            
            # Format share price for display (divide by 10^18 to get human-readable value)
            share_price_formatted = share_price / Decimal(10 ** 18)

            total_assets_formatted = total_assets / Decimal(10 ** asset_decimals)
            total_supply_formatted = total_supply / Decimal(10 ** asset_decimals)
            
            
            # 3. Store results in VaultPrice model
            vault_price = VaultPrice.objects.create(
                vault_address=vault_address,
                token=underlying_token_symbol,
                protocol=highest_apy_protocol,
                pool_apy=pool_apy,
                share_price=str(share_price),
                share_price_formatted=share_price_formatted,
                total_assets=str(total_assets_formatted),
                total_supply=str(total_supply_formatted)
            )
            
            logger.info(f"Stored vault price data (ID: {vault_price.id})")
            return True
            
        except Exception as e:
            logger.error(f"Error calculating vault price: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False


    def calculate_and_store_24hr_and_7day_apy(self, vault_address: str):
        """
        Calculate and store 24hr and 7day APY for all vaults
        """
        from data.models import YieldReport, VaultPrice, VaultAPY
        from decimal import Decimal
        import logging
        import math
        from datetime import datetime, timezone

        logger = logging.getLogger(__name__)
        logger.info("Calculating and storing 24hr and 7day APY for all vaults...")

        try:
            # calculate today's midnight UTC as timestamp
            today_midnight_timestamp = int(time.time() / 86400) * 86400
            
            # Convert timestamp to datetime object for Django ORM
            today_midnight_utc = datetime.fromtimestamp(today_midnight_timestamp, tz=timezone.utc)

            # Calculate hours elapsed since midnight
            hours_elapsed = (time.time() - today_midnight_timestamp) / 3600
            days_elapsed = hours_elapsed / 24
            logger.info(f"hours_elapsed since midnight: {hours_elapsed}")
            logger.info(f"days_elapsed: {days_elapsed}")
            
            # Skip 24-hour APY calculation if less than 3 hours have elapsed since midnight
            if hours_elapsed < 3:
                logger.info("Skipping 24-hour APY calculation: less than 3 hours since midnight")
                return False
            
            exponential = 365 / (days_elapsed/2)

            # query vault price nearby today_midnight_utc
            midnight_vault_price = VaultPrice.objects.filter(vault_address=vault_address, created_at__lte=today_midnight_utc).order_by('-created_at').first()
            midnight_share_price = midnight_vault_price.share_price_formatted

            # query current vault price
            current_vault_price = VaultPrice.objects.filter(vault_address=vault_address).order_by('-created_at').first()
            current_share_price = current_vault_price.share_price_formatted
            token = current_vault_price.token

            logger.info(f"midnight_share_price: {midnight_share_price}")
            logger.info(f"current_share_price: {current_share_price}")
            if midnight_share_price == 0:
                logger.info("midnight_share_price is 0")
                return False
            
            apy_24h = math.pow(float(current_share_price/midnight_share_price), exponential) - 1
            logger.info(f"projected 24hr APY: {apy_24h}")

            # Initialize VaultAPY object with 24-hour data
            vault_apy = VaultAPY(
                vault_address=vault_address,
                token=token,
                apy_24h=Decimal(str(apy_24h)),
                midnight_share_price=midnight_share_price,
                current_share_price=current_share_price,
                days_elapsed=Decimal(str(days_elapsed)),
                exponential=Decimal(str(exponential))
            )

            # Check if we should calculate 7-day APY
            # Get the latest 7-day APY calculation for this vault
            latest_7d_apy = VaultAPY.objects.filter(
                vault_address=vault_address,
                token=token,
                apy_7d__isnull=False
            ).order_by('-calculation_time').first()
            
            calculate_7d_apy = True
            
            if latest_7d_apy:
                # Calculate hours elapsed since last 7-day APY calculation
                last_calc_time = latest_7d_apy.calculation_time
                hours_since_last_calc = (datetime.now(timezone.utc) - last_calc_time).total_seconds() / 3600
                
                # Only calculate 7-day APY if at least 24 hours have elapsed since last calculation
                if hours_since_last_calc < 24:
                    logger.info(f"Skipping 7-day APY calculation: only {hours_since_last_calc:.2f} hours since last calculation")
                    calculate_7d_apy = False
            
            # If we should calculate 7-day APY
            if calculate_7d_apy:
                # 7 day APY calculation
                seven_days_ago = today_midnight_utc - timedelta(days=7)
                logger.info(f"seven_days_ago: {seven_days_ago}")
                seven_days_ago_vault_price = VaultPrice.objects.filter(vault_address=vault_address, created_at__lte=seven_days_ago).order_by('-created_at').first()
                
                if seven_days_ago_vault_price is None:
                    logger.info("seven_days_ago_vault_price is None")
                    # Still save the 24-hour APY data
                    vault_apy.save()
                    logger.info(f"Saved 24-hour APY data for {vault_address} (ID: {vault_apy.id})")
                    return True
                    
                seven_days_ago_share_price = seven_days_ago_vault_price.share_price_formatted

                logger.info(f"seven_days_ago_share_price: {seven_days_ago_share_price}")
                if seven_days_ago_share_price == 0:
                    logger.info("seven_days_ago_share_price is 0")
                    # Still save the 24-hour APY data
                    vault_apy.save()
                    logger.info(f"Saved 24-hour APY data for {vault_address} (ID: {vault_apy.id})")
                    return True
                
                apy_7d = math.pow(float(current_share_price/seven_days_ago_share_price), exponential) - 1
                logger.info(f"projected 7day APY: {apy_7d}")
                
                # Add 7-day data to the VaultAPY object
                vault_apy.apy_7d = Decimal(str(apy_7d))
                vault_apy.seven_day_share_price = seven_days_ago_share_price
                
                # Save the complete APY data
                vault_apy.save()
                logger.info(f"Saved 24-hour and 7-day APY data for {vault_address} (ID: {vault_apy.id})")
            else:
                # Save only the 24-hour APY data
                vault_apy.save()
                logger.info(f"Saved 24-hour APY data for {vault_address} (ID: {vault_apy.id})")
            
            return True
            
        except Exception as e:
            logger.error(f"Error calculating 24hr and 7day APY: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def run_monitoring_cycle(self):
        """Run one complete monitoring cycle"""
        start_time = time.time()
        
        logger.info("=" * 80)
        logger.info("Starting yield monitoring cycle")
        logger.info("=" * 80)
        
        # Calculate and store vault price data
        self.calculate_and_store_vault_price('USDe', self.yield_allocator_vault_address)
        self.calculate_and_store_vault_price('USDT0', self.yield_allocator_vault_address_usdt0)
        
        # Calculate and store 24hr and 7day APY
        self.calculate_and_store_24hr_and_7day_apy(self.yield_allocator_vault_address)
        self.calculate_and_store_24hr_and_7day_apy(self.yield_allocator_vault_address_usdt0)

        
        yield_info = None
        result = {'success': False, 'error': 'Unknown error', 'total_withdrawn': 0, 'total_reinvested': 0, 'pool_results': {}}

        if True:
            logger.info("Skipping claim and reinvest")
            return    
        try:
            # Initialize monitoring run record
            monitor_run = YieldMonitorRun.objects.create(
                vault_address=self.yield_allocator_vault_address,
                status='running',
                asset_symbol='USDE',  # Default asset symbol
                asset_decimals=18,    # Default decimals for USDE
                total_principal_deposited=0,  # Will be updated later
                current_total_value=0,        # Will be updated later
                total_yield_generated=0,      # Will be updated later
                total_yield_percentage=0,     # Will be updated later
                idle_assets=0,                # Will be updated later
                yield_threshold_used=Decimal(str(self.yield_threshold)),
                min_claim_amount_usd=Decimal(str(self.min_claim_amount_usd)),
                max_gas_cost_usd=Decimal(str(self.max_gas_cost_usd))
            )
            
            # Get whitelisted pools
            pools = self.get_whitelisted_pools()
            if not pools:
                logger.warning("No whitelisted pools found")
                result = {'success': False, 'error': 'No whitelisted pools found', 'total_withdrawn': 0, 'total_reinvested': 0, 'pool_results': {}}
                return
            
            # Calculate vault yield info
            yield_info = self.calculate_vault_yield_info(pools)
            if not yield_info:
                logger.error("Failed to calculate vault yield info")
                monitor_run.status = 'failed'
                monitor_run.error_message = 'Failed to calculate vault yield info'
                monitor_run.save()
                result = {'success': False, 'error': 'Failed to calculate vault yield info', 'total_withdrawn': 0, 'total_reinvested': 0, 'pool_results': {}}
                return
            
            # Calculate APR/APY for the vault
            logger.info("Calculating vault APR/APY...")
            apr_data = self.calculate_vault_apr_apy(self.yield_allocator_vault_address, window_days=1)
            
            # Save APR data to database
            if apr_data.get('success', False):
                self.save_pool_apr_data(apr_data)
                logger.info(f"APR calculation successful: APR={apr_data['apr']*100:.4f}%, APY={apr_data['apy']*100:.4f}%")
            else:
                logger.warning(f"APR calculation failed: {apr_data.get('error', 'Unknown error')}")
                # Still save the failed calculation for tracking
                self.save_pool_apr_data(apr_data)
            
            # Check if yield should be claimed
            should_claim, reason = self.should_claim_yield(yield_info)
            if not should_claim:
                logger.info(f"Skipping yield claiming: {reason}")
                result = {'success': True, 'skipped': True, 'reason': reason, 'total_withdrawn': 0, 'total_reinvested': 0, 'pool_results': {}}
                return
            
            # Withdraw and reinvest yield
            result = self.withdraw_and_reinvest_yield(yield_info)
            if not result['success']:
                logger.error(f"Error withdrawing and reinvesting yield: {result.get('error', 'Unknown error')}")
                return
            
            logger.info("Successfully claimed and reinvested yield")
            
        except Exception as e:
            logger.error(f"Error in monitoring cycle: {str(e)}")
            result = {'success': False, 'error': str(e), 'total_withdrawn': 0, 'total_reinvested': 0, 'pool_results': {}}
            raise
        finally:
            # Always save results, even if there was an error or skip
            try:
                if yield_info:
                    self.save_monitoring_results(yield_info, result, start_time)
                else:
                    # Create minimal yield_info for failed runs
                    minimal_yield_info = {
                        'asset_address': '',
                        'asset_symbol': 'UNKNOWN',
                        'asset_decimals': 18,
                        'total_principal_deposited': 0,
                        'current_total_value': 0,
                        'total_yield_generated': 0,
                        'total_yield_percentage': 0,
                        'idle_assets': 0,
                        'pool_principals': {}
                    }
                    self.save_monitoring_results(minimal_yield_info, result, start_time)
            except Exception as save_error:
                logger.error(f"Error saving monitoring results: {str(save_error)}")
                import traceback
                logger.error(f"Save error traceback: {traceback.format_exc()}")

def main():
    """Main entry point for the yield monitor worker"""
    try:
        worker = YieldMonitorWorker()
        worker.run_monitoring_cycle()
        
    except Exception as e:
        logger.error(f"Fatal error in yield monitor worker: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
