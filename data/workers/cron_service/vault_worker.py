"""
Vault Worker - Automated Batch Deposit Fulfillment
Monitors deposit queue and automatically fulfills pending deposits using the AIAgent contract
Based on the TypeScript implementation for fulfill-batch-deposits.ts
"""
import os
import sys
import time
import logging
import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal

# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from data.utils.optimizer import find_most_profitable_reallocation, parse_cron_struct, CronPoolData
from data.utils.strategy_summarizer import summarize_strategy_with_gpt

# Configure Django BEFORE importing any Django models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

import django
django.setup()


import requests
import uuid
from web3 import Web3
from data.utils.rpc_utils import get_web3_provider
from data.models import VaultDepositRun, VaultDepositTransaction, VaultWithdrawalRun, VaultWithdrawalTransaction, VaultRebalance

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

class VaultWorker:
    """
    Worker that monitors deposit queue and fulfills pending deposits
    Uses the same logic as the TypeScript fulfill-batch-deposits.ts script
    """
    
    def __init__(self, underlying_token_symbol: str, vault_address: str, ai_agent_address: str, whitelist_registry_address: str, executor_private_key: str, max_batch_size: int):
        """Initialize the vault worker"""

        logger.info(f"=== Initializing Vault Worker for {underlying_token_symbol} ===")
        self.rpc_url = os.getenv('RPC_URL')
        self.executor_private_key = executor_private_key
        self.whitelist_registry_address = whitelist_registry_address
        self.yield_allocator_vault_address = vault_address
        self.ai_agent_address = ai_agent_address
        self.max_batch_size = max_batch_size
        self.underlying_token_symbol = underlying_token_symbol

        # Configuration parameters
        self.gas_price_gwei = int(os.getenv('GAS_PRICE_GWEI', '20'))
        
        logger.info("=== Configuration Parameters ===")
        logger.info(f"Maximum batch size: {self.max_batch_size}")
        logger.info(f"Gas price (Gwei): {self.gas_price_gwei}")
        
        # Log all environment variables for debugging (mask private key)
        logger.info("=== Environment Variables ===")
        logger.info(f"RPC_URL: {self.rpc_url}")
        logger.info(f"EXECUTOR_PRIVATE_KEY: {'***' if self.executor_private_key else 'NOT SET'}")
        logger.info(f"WHITELIST_REGISTRY_ADDRESS: {self.whitelist_registry_address}")
        logger.info(f"YIELD_ALLOCATOR_VAULT_ADDRESS: {self.yield_allocator_vault_address}")
        logger.info(f"AI_AGENT_ADDRESS: {self.ai_agent_address}")
        
        # Validate addresses are proper hex format
        addresses_to_validate = [
            ("WHITELIST_REGISTRY_ADDRESS", self.whitelist_registry_address),
            ("YIELD_ALLOCATOR_VAULT_ADDRESS", self.yield_allocator_vault_address),
            ("AI_AGENT_ADDRESS", self.ai_agent_address)
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
        
        # Initialize Web3 connection
        logger.info("=== Initializing Web3 Connection ===")
        self.web3 = self._setup_web3_connection()
        
        # Initialize account
        logger.info("=== Setting up Account ===")
        self.executor_account = self.web3.eth.account.from_key(self.executor_private_key)
        self.executor_address = self.executor_account.address
        logger.info(f"Executor account address: {self.executor_address}")
        
        logger.info(f"Vault Worker initialized")
        logger.info(f"Executor address: {self.executor_address}")
        logger.info(f"Registry: {self.whitelist_registry_address}")
        logger.info(f"Vault: {self.yield_allocator_vault_address}")
        logger.info(f"AI Agent: {self.ai_agent_address}")
    
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
    
    def format_with_decimals(self, value, decimals):
        """Format a value based on the token's decimal places
        
        This is a custom implementation to handle tokens with any number of decimals,
        not just the standard units supported by web3.from_wei()
        """
        if decimals == 18:
            # For tokens with 18 decimals, we can use the standard 'ether' unit
            return self.web3.from_wei(value, 'ether')
        elif decimals == 6:
            # For tokens with 6 decimals (like USDC, USDT), we can use 'mwei'
            return self.web3.from_wei(value, 'mwei')
        elif decimals == 8:
            # For tokens with 8 decimals (like WBTC), we can use 'gwei' and multiply
            return self.web3.from_wei(value, 'gwei') * 100
        else:
            # For any other decimal places, use a generic approach
            from decimal import Decimal
            return Decimal(value) / Decimal(10 ** decimals)
            
    def get_pool_apy(self, pool_address):
        """Get APY for a pool from the database
        
        Args:
            pool_address: Address of the pool to get APY for
            
        Returns:
            Float APY value or None if not found
        """
        try:
            from data.models import YieldReport, PoolAPR
            
            # First try to get from PoolAPR (most accurate)
            try:
                latest_apr = PoolAPR.objects.filter(
                    pool_address=pool_address,
                    calculation_status='success'
                ).order_by('-timestamp').first()
                
                if latest_apr:
                    return float(latest_apr.apy) * 100  # Convert to percentage
            except Exception as e:
                logger.warning(f"Error getting APY from PoolAPR: {str(e)}")
            
            # Fallback to YieldReport
            try:
                latest_report = YieldReport.objects.filter(
                    pool_address=pool_address
                ).order_by('-created_at').first()
                
                if latest_report:
                    return float(latest_report.apy)
            except Exception as e:
                logger.warning(f"Error getting APY from YieldReport: {str(e)}")
            
            # If we couldn't find the APY, return None
            return None
        except Exception as e:
            logger.error(f"Error getting pool APY: {str(e)}")
            return None
    
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
    
    def get_latest_pool_apys(self, underlying_token_symbol: str):
        """
        Get the latest yield reports for a given token from HyperLend, HypurrFi, and Felix
        
        Returns:
            Tuple of (latest_hyperlend, latest_hypurrfi, latest_felix) where each item
            is either a YieldReport object or None if no reports were found
        """
        from data.models import YieldReport
        
        # Initialize variables to None to avoid UnboundLocalError
        latest_hyperlend = None
        latest_hypurrfi = None
        latest_felix = None
        
        # Initialize variables to track highest APY and its protocol
        highest_apy = Decimal('0')
        highest_apy_protocol = None
        highest_apy_pool_address = None
        
        try:
            # Query HyperLend reports
            hyperlend_reports = YieldReport.objects.filter(
                token__icontains=underlying_token_symbol,
                protocol__icontains='HyperLend'
            ).order_by('-created_at')
            
            # Check HyperLend APY
            if hyperlend_reports.exists():
                latest_hyperlend = hyperlend_reports.first()
                if latest_hyperlend.apy > highest_apy:
                    highest_apy = latest_hyperlend.apy
                    highest_apy_protocol = latest_hyperlend.protocol
                    highest_apy_pool_address = latest_hyperlend.pool_address
            else:
                logger.warning("No HyperLend yield reports found")
        except Exception as e:
            logger.error(f"Error retrieving HyperLend yield reports: {str(e)}")
            
        try:
            # Query HypurrFi reports
            hypurrfi_reports = YieldReport.objects.filter(
                token__icontains=underlying_token_symbol,
                protocol__icontains='HypurrFi'
            ).order_by('-created_at')
            
            # Check HypurrFi APY
            if hypurrfi_reports.exists():
                latest_hypurrfi = hypurrfi_reports.first()
                if latest_hypurrfi.apy > highest_apy:
                    highest_apy = latest_hypurrfi.apy
                    highest_apy_protocol = latest_hypurrfi.protocol
                    highest_apy_pool_address = latest_hypurrfi.pool_address
            else:
                logger.warning("No HypurrFi yield reports found")
        except Exception as e:
            logger.error(f"Error retrieving HypurrFi yield reports: {str(e)}")
            
        try:
            # Query Felix reports
            felix_reports = YieldReport.objects.filter(
                token__icontains=underlying_token_symbol,
                protocol__icontains='Felix'
            ).order_by('-created_at')
            
            # Check Felix APY
            if felix_reports.exists():
                latest_felix = felix_reports.first()
                if latest_felix.apy > highest_apy:
                    highest_apy = latest_felix.apy
                    highest_apy_protocol = latest_felix.protocol
                    highest_apy_pool_address = latest_felix.pool_address
            else:
                logger.warning("No Felix yield reports found")
        except Exception as e:
            logger.error(f"Error retrieving Felix yield reports: {str(e)}")
        
        # Log the highest APY found if any
        if highest_apy_protocol:
            logger.info(f"Highest APY: {highest_apy_protocol} with {highest_apy}%")
        else:
            logger.warning("No yield reports found for any protocol")
            
        return latest_hyperlend, latest_hypurrfi, latest_felix
        
    def prepare_optimizer_data(self, latest_hyperlend, latest_hypurrfi, latest_felix, pool_allocations):
        """
        Prepare data for the optimizer from YieldReport objects
        
        Args:
            latest_hyperlend: Latest HyperLend YieldReport object
            latest_hypurrfi: Latest HypurrFi YieldReport object
            latest_felix: Latest Felix YieldReport object
            pool_allocations: List of pool balances from protocol_info
            
        Returns:
            Tuple of (cron_struct, current_position) for the optimizer
        """
        # Create cron_struct with pool addresses as keys
        cron_struct = {}
        
        # Add HyperLend pool data if available
        if hasattr(latest_hyperlend, 'pool_address') and latest_hyperlend.pool_address:
            hyperlend_address = latest_hyperlend.pool_address.lower()
            hyperlend_params = json.loads(latest_hyperlend.params) if latest_hyperlend.params else {}
            
            # Extract required parameters or use defaults
            cron_struct[hyperlend_address] = {
                "protocol": "HyperLend",
                "current_apr": float(latest_hyperlend.apy) / 100,  # Convert percentage to decimal
                "tvl": float(latest_hyperlend.tvl),
                "utilization": float(latest_hyperlend.params.get('utilization', 0)) / 100,  # Convert percentage to decimal
                "kink": float(latest_hyperlend.params.get('kink', 0.8)),
                "slope1": float(latest_hyperlend.params.get('slope1', 0.05)),
                "slope2": float(latest_hyperlend.params.get('slope2', 1.0)),
                "reserve_factor": float(latest_hyperlend.params.get('reserve_factor', 0.2))
            }
        
        # Add HypurrFi pool data if available
        if hasattr(latest_hypurrfi, 'pool_address') and latest_hypurrfi.pool_address:
            hypurrfi_address = latest_hypurrfi.pool_address.lower()
            hypurrfi_params = json.loads(latest_hypurrfi.params) if latest_hypurrfi.params else {}
            
            cron_struct[hypurrfi_address] = {
                "protocol": "HyperFi",  # Use HyperFi as the normalized name for optimizer
                "current_apr": float(latest_hypurrfi.apy) ,
                "tvl": float(latest_hypurrfi.params.get('tvl', 0)),
                "utilization": float(latest_hypurrfi.params.get('utilization', 0)) / 100,
                "kink": float(latest_hypurrfi.params.get('kink', 0.8)),
                "slope1": float(latest_hypurrfi.params.get('slope1', 0.12)),
                "slope2": float(latest_hypurrfi.params.get('slope2', 0.6)),
                "reserve_factor": float(latest_hypurrfi.params.get('reserve_factor', 0.2))
            }
            
        # Add Felix pool data if available
        if hasattr(latest_felix, 'pool_address') and latest_felix.pool_address:
            felix_address = latest_felix.pool_address.lower()
            felix_params = json.loads(latest_felix.params) if latest_felix.params else {}

            # Felix params    
            # {"curve_steepness": "4.00000000", "adjustment_speed": "50.00000000", "target_utilization": "0.90000000", "initial_rate_at_target": "0.04000000", "min_rate_at_target": "0.00100000", "max_rate_at_target": "2.00000000", "utilization": 0.8853610826202732, "reserve_factor": 0.1}    
            cron_struct[felix_address] = {
                "protocol": "Felix",
                "current_apy": float(latest_felix.apy),
                "tvl": float(felix_params.get('tvl', 0)),
                "utilization": float(felix_params.get('utilization', 0)) * 100,
                "curve_steepness": float(felix_params.get('curve_steepness',4.0)),
                "adjustment_speed": float(felix_params.get('adjustment_speed', 50.0)),
                "target_utilization": float(felix_params.get('target_utilization', 0.9)),
                "initial_rate_at_target": float(felix_params.get('initial_rate_at_target', 0.04)),
                "min_rate_at_target": float(felix_params.get('min_rate_at_target', 0.001)),
                "max_rate_at_target": float(felix_params.get('max_rate_at_target', 2.0)),
                "reserve_factor": float(felix_params.get('reserve_factor', 0.1))
            }
        
        # Create current_position with pool addresses as keys
        current_position = {}
        for pool in pool_allocations:
            pool_address = pool.get('address', '').lower()
            if pool_address and pool_address in cron_struct:
                current_position[pool_address] = float(pool.get('balance', 0))
        
        return cron_struct, current_position
    
    def verify_executor_permissions(self) -> bool:
        """Verify that the executor has the necessary permissions"""
        try:
            abis = self.get_contract_abis()
            
            # Get AI Agent contract
            ai_agent_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.ai_agent_address),
                abi=abis['AIAgent']
            )
            
            # Get YieldAllocatorVault contract
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=abis['YieldAllocatorVault']
            )
            
            # Get EXECUTOR role
            executor_role = ai_agent_contract.functions.EXECUTOR().call()
            
            # Check if executor has EXECUTOR role on AIAgent
            has_executor_role = ai_agent_contract.functions.hasRole(
                executor_role, 
                self.executor_address
            ).call()
            
            if not has_executor_role:
                logger.error("Executor wallet does not have the EXECUTOR role on AIAgent")
                return False
            
            logger.info("✅ Executor wallet has the EXECUTOR role on AIAgent")
            
            # Check if AIAgent has EXECUTOR role on YieldAllocatorVault
            has_exec_vault = vault_contract.functions.hasRole(
                executor_role,
                self.web3.to_checksum_address(self.ai_agent_address)
            ).call()
            
            if not has_exec_vault:
                logger.error("AIAgent does not have the EXECUTOR role on YieldAllocatorVault")
                return False
            
            logger.info("✅ AIAgent has the EXECUTOR role on YieldAllocatorVault")
            
            return True
            
        except Exception as e:
            logger.error(f"Error verifying executor permissions: {str(e)}")
            return False
    
    def verify_pool_is_whitelisted(self, pool_address: str) -> bool:
        """Verify that the pool is whitelisted"""
        try:
            abis = self.get_contract_abis()
            
            # Get WhitelistRegistry contract
            registry_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.whitelist_registry_address),
                abi=abis['WhitelistRegistry']
            )
            
            # Check if pool is whitelisted
            is_whitelisted = registry_contract.functions.isWhitelisted(
                self.web3.to_checksum_address(pool_address)
            ).call()
            
            if not is_whitelisted:
                logger.error(f"Pool {pool_address} is not whitelisted")
                return False
            
            logger.info(f"✅ Pool {pool_address} is whitelisted")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying pool whitelist status: {str(e)}")
            return False
    
    def get_deposit_queue_info(self) -> Dict:
        """Get information about the deposit queue"""
        try:
            abis = self.get_contract_abis()
            
            # Get YieldAllocatorVault contract
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=abis['YieldAllocatorVault']
            )
            
            # Get asset token details
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=abis['ERC20']
            )
            
            # Get asset details
            try:
                asset_symbol = asset_contract.functions.symbol().call()
                asset_decimals = asset_contract.functions.decimals().call()
            except Exception:
                # Fallback values if contract calls fail
                asset_symbol = "USDe"
                asset_decimals = 18
                logger.warning(f"Using default symbol and decimals for asset token")
            
            logger.info(f"Asset token address: {asset_address}")
            logger.info(f"Asset token: {asset_symbol} ({asset_decimals} decimals)")
            
            # Check current idle asset balance in vault
            idle_asset_balance = asset_contract.functions.balanceOf(
                self.web3.to_checksum_address(self.yield_allocator_vault_address)
            ).call()
            
            logger.info(f"Idle asset balance in vault: {self.format_with_decimals(idle_asset_balance, asset_decimals)} {asset_symbol}")
            
            # Get the length of the deposit queue
            queue_length = vault_contract.functions.depositQueueLength().call()
            logger.info(f"Deposit queue length: {queue_length}")
            
            # If queue is empty, return early
            if queue_length == 0:
                logger.info("No pending deposit requests in the queue")
                return {
                    'queue_length': 0,
                    'asset_address': asset_address,
                    'asset_symbol': asset_symbol,
                    'asset_decimals': asset_decimals,
                    'idle_asset_balance': idle_asset_balance,
                    'deposit_requests': []
                }
            
            # Examine the first few items in the queue (up to max batch size)
            items_to_examine = min(int(queue_length), self.max_batch_size)
            logger.info(f"Examining first {items_to_examine} items in the queue:")
            
            deposit_requests = []
            total_assets_to_deposit = 0
            
            for i in range(items_to_examine):
                try:
                    # Get the deposit request at index i
                    controller, assets = vault_contract.functions.depositQueueAt(i).call()

                    # Get deposit request details from the mapping
                    deposit_request = vault_contract.functions.depositRequests(controller).call()

                    # Format for readability
                    formatted_assets = self.format_with_decimals(deposit_request[0], asset_decimals)

                    logger.info(f"Queue position {i + 1}:")
                    logger.info(f"  Controller: {controller}")
                    logger.info(f"  Pending assets: {formatted_assets} {asset_symbol}")
                    logger.info(f"  Receiver: {deposit_request[1]}")

                    deposit_requests.append({
                        'controller': controller,
                        'assets': deposit_request[0],
                        'receiver': deposit_request[1],
                        'exists': deposit_request[2],
                        'formatted_assets': formatted_assets
                    })

                    total_assets_to_deposit += int(deposit_request[0])
                except Exception as e:
                    logger.error(f"Error examining queue item {i}: {str(e)}")
                    break
            
            # Debug vault state
            total_assets = vault_contract.functions.totalAssets().call()
            logger.info(f"Total assets: {self.format_with_decimals(total_assets, asset_decimals)} {asset_symbol}")
            
            return {
                'queue_length': queue_length,
                'asset_address': asset_address,
                'asset_symbol': asset_symbol,
                'asset_decimals': asset_decimals,
                'idle_asset_balance': idle_asset_balance,
                'total_assets': total_assets,
                'deposit_requests': deposit_requests,
                'total_assets_to_deposit': total_assets_to_deposit
            }
            
        except Exception as e:
            logger.error(f"Error getting deposit queue info: {str(e)}")
            return {'queue_length': 0, 'error': str(e)}
    
    def fulfill_batch_deposits(self, best_pool: str, batch_size: int = 5) -> Dict:
        """Fulfill a batch of deposit requests"""
        try:
            abis = self.get_contract_abis()
            
            # Get AI Agent contract
            ai_agent_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.ai_agent_address),
                abi=abis['AIAgent']
            )
            
            # Get YieldAllocatorVault contract for verification
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=abis['YieldAllocatorVault']
            )
            
            # Verify there are pending requests
            current_queue_length = vault_contract.functions.depositQueueLength().call()
            if current_queue_length == 0:
                logger.info("No pending requests in the queue to fulfill")
                return {'success': False, 'error': 'No pending requests'}
            
            # Determine the batch size based on queue length
            current_batch_size = min(batch_size, int(current_queue_length))
            logger.info(f"Processing {current_queue_length} requests with batch size {current_batch_size}")
            
            # Call AIAgent to fulfill the next batch
            logger.info(f"Executing fullfillBatchDeposits({current_batch_size}, {best_pool}) on AIAgent")
            
            # Build transaction
            nonce = self.web3.eth.get_transaction_count(self.executor_address)
            gas_price = self.web3.eth.gas_price
            
            fulfill_tx = ai_agent_contract.functions.fullfillBatchDeposits(
                current_batch_size,
                self.web3.to_checksum_address(best_pool)
            ).build_transaction({
                'from': self.executor_address,
                # 'gas': 3000000,  # Higher gas limit for batch operations
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            
            # Sign and send transaction
            try:
                signed_tx = self.web3.eth.account.sign_transaction(fulfill_tx, self.executor_private_key)
                # Check if we're using web3.py v5 or v6
                if hasattr(signed_tx, 'rawTransaction'):
                    # web3.py v5
                    tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                else:
                    # web3.py v6
                    tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            except AttributeError as e:
                logger.error(f"Transaction signing error: {str(e)}")
                # Try alternative attribute name (for different web3.py versions)
                if hasattr(signed_tx, 'raw_transaction'):
                    tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
                else:
                    raise ValueError(f"Cannot find raw transaction data in signed transaction: {str(signed_tx)}")
            
            logger.info(f"Transaction sent: {tx_hash.hex()}")
            logger.info(f"Waiting for transaction confirmation...")
            
            # Wait for transaction receipt
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            if receipt.status == 1:
                logger.info(f"✅ Transaction successful! Gas used: {receipt.gasUsed}")
                
                # Check updated queue length
                updated_queue_length = vault_contract.functions.depositQueueLength().call()
                processed_count = current_queue_length - updated_queue_length
                
                logger.info(f"Updated deposit queue length: {updated_queue_length}")
                logger.info(f"Processed {processed_count} deposit requests")
                
                # Get best pool name from address
                best_pool_name = self.get_pool_name_from_address(best_pool)
                logger.info(f"Best pool selected for deposit: {best_pool_name} ({best_pool})")
                
                return {
                    'success': True,
                    'tx_hash': tx_hash.hex(),
                    'gas_used': receipt.gasUsed,
                    'processed_count': processed_count,
                    'remaining_count': updated_queue_length,
                    'best_pool_address': best_pool,
                    'best_pool_name': best_pool_name
                }
            else:
                logger.error(f"❌ Transaction failed!")
                return {'success': False, 'error': 'Transaction failed', 'tx_hash': tx_hash.hex()}
            
        except Exception as e:
            logger.error(f"Error fulfilling batch deposits: {str(e)}")
            return {'success': False, 'error': str(e)}
            
    def fulfill_batch_withdrawals(self, batch_size: int = 5) -> Dict:
        """Fulfill a batch of withdrawal requests and track total withdrawal amount"""
        try:
            abis = self.get_contract_abis()
            
            # Get AI Agent contract
            ai_agent_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.ai_agent_address),
                abi=abis['AIAgent']
            )
            
            # Get YieldAllocatorVault contract for verification
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=abis['YieldAllocatorVault']
            )
            
            # Get WhitelistRegistry contract
            whitelist_registry_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.whitelist_registry_address),
                abi=abis['WhitelistRegistry']
            )
            
            # Get asset token info
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=abis['ERC20']
            )
            
            try:
                asset_symbol = asset_contract.functions.symbol().call()
                asset_decimals = asset_contract.functions.decimals().call()
            except Exception:
                # Fallback values if contract calls fail
                logger.warning("Using default symbol and decimals for asset token")
                asset_symbol = "USDe"
                asset_decimals = 18
            
            # Get vault balance before withdrawal (idle assets)
            idle_asset_balance = asset_contract.functions.balanceOf(self.yield_allocator_vault_address).call()
            logger.info(f"Idle asset balance in vault: {self.format_with_decimals(idle_asset_balance, asset_decimals)} {asset_symbol}")
            
            # Get the withdrawal queue length and calculate total assets needed
            withdrawal_queue_length = 0
            total_assets_needed = 0
            safe_users = []
            unsafe_users = []
            
            try:
                # Keep checking indices until we get an error (no more withdrawers)
                i = 0
                while True:
                    try:
                        # Get the controller address (user)
                        controller = vault_contract.functions.pendingWithdrawers(i).call()
                        if controller == '0x0000000000000000000000000000000000000000':
                            break
                        
                        # Get withdrawal request details
                        withdrawal_request = vault_contract.functions.withdrawalRequests(controller).call()
                        assets_needed = withdrawal_request[1]  # assetsAtRequest
                        
                        logger.info(f"Queue position {i + 1}:")
                        logger.info(f"  Controller: {controller}")
                        logger.info(f"  Assets needed: {self.format_with_decimals(assets_needed, asset_decimals)} {asset_symbol}")
                        
                        # Check if user has non-zero userShares to prevent division by zero
                        user_shares = vault_contract.functions.userShares(controller).call()
                        if user_shares == 0:
                            logger.warning(f"⚠️ User {controller} has zero userShares. This would cause division by zero.")
                            unsafe_users.append(controller)
                        else:
                            safe_users.append(i)
                            total_assets_needed += assets_needed
                            
                        i += 1
                    except Exception as e:
                        logger.error(f"Error examining queue item {i}: {str(e)}")
                        break
                        
                withdrawal_queue_length = i
            except Exception as e:
                # We've reached the end of the array
                logger.error(f"Error reading withdrawal queue: {str(e)}")
                withdrawal_queue_length = i
            
            logger.info(f"Withdrawal queue length: {withdrawal_queue_length}")
            logger.info(f"Safe requests (non-zero userShares): {len(safe_users)}")
            logger.info(f"Unsafe requests (zero userShares): {len(unsafe_users)}")
            logger.info(f"Total assets needed: {self.format_with_decimals(total_assets_needed, asset_decimals)} {asset_symbol}")
            
            # Verify there are pending withdrawal requests
            if withdrawal_queue_length == 0:
                logger.info("No pending withdrawal requests to fulfill")
                return {'success': False, 'error': 'No pending withdrawals'}
            
            # Check if there are any safe requests to process
            if len(safe_users) == 0:
                logger.warning("No safe withdrawal requests to process")
                logger.warning("All users in the queue have zero userShares, which would cause division by zero errors")
                return {'success': False, 'error': 'No safe withdrawal requests to process'}
            
            # Check if we need to withdraw from pools to cover the shortfall
            shortfall = 0
            if total_assets_needed > idle_asset_balance:
                shortfall = total_assets_needed - idle_asset_balance
                logger.info(f"⚠️ Shortfall: {self.format_with_decimals(shortfall, asset_decimals)} {asset_symbol}")
                logger.info("Need to withdraw from pools to cover withdrawal requests...")
                
                # Get whitelisted pools
                try:
                    whitelisted_pools = whitelist_registry_contract.functions.getWhitelistedPools().call()
                    logger.info(f"Found {len(whitelisted_pools)} whitelisted pools")
                except Exception as e:
                    logger.error(f"Error fetching whitelisted pools: {str(e)}")
                    return {'success': False, 'error': f"Error fetching whitelisted pools: {str(e)}"}
                
                # Check pool balances and get pool kinds
                pool_balances = []
                for pool_address in whitelisted_pools:
                    try:
                        # Get pool balance (principal)
                        pool_balance = vault_contract.functions.poolPrincipal(pool_address).call()
                        
                        # Get pool kind from WhitelistRegistry
                        pool_kind_value = whitelist_registry_contract.functions.getPoolKind(pool_address).call()
                        pool_kind_name = "AAVE" if pool_kind_value == 0 else "ERC4626"
                        
                        # Use poolPrincipal as withdrawable assets
                        withdrawable_assets = vault_contract.functions.poolPrincipal(pool_address).call()
                        
                        # Get pool name
                        pool_name = self.get_pool_name_from_address(pool_address)
                        
                        logger.info(f"Pool {pool_address} [{pool_kind_name}]: {self.format_with_decimals(pool_balance, asset_decimals)} {asset_symbol} (principal), {self.format_with_decimals(withdrawable_assets, asset_decimals)} {asset_symbol} (withdrawable)")
                        
                        pool_balances.append({
                            'pool': pool_address,
                            'pool_kind': pool_kind_value,
                            'balance': pool_balance,
                            'withdrawable_assets': withdrawable_assets,
                            'pool_name': pool_name
                        })
                    except Exception as e:
                        logger.error(f"Error getting balance for pool {pool_address}: {str(e)}")
                
                # Sort pools by withdrawable assets (largest first)
                pool_balances.sort(key=lambda x: x['withdrawable_assets'], reverse=True)
                
                logger.info("Pools sorted by liquidity (highest first):")
                for pool_info in pool_balances:
                    pool_kind_name = "AAVE" if pool_info['pool_kind'] == 0 else "ERC4626"
                    logger.info(f"  Pool {pool_info['pool']} [{pool_kind_name}]: {self.format_with_decimals(pool_info['withdrawable_assets'], asset_decimals)} {asset_symbol}")
                
                # Withdraw from pools to cover shortfall
                remaining_shortfall = shortfall
                withdrawal_txs = []
                
                for pool_info in pool_balances:
                    if remaining_shortfall <= 0:
                        break
                    if pool_info['withdrawable_assets'] == 0:
                        continue
                    
                    withdraw_amount = min(remaining_shortfall, pool_info['withdrawable_assets'])
                    
                    logger.info(f"🔄 Withdrawing {self.format_with_decimals(withdraw_amount, asset_decimals)} {asset_symbol} from pool {pool_info['pool']}...")
                    
                    try:
                        # Execute withdrawal from pool
                        withdrawal_result = self.execute_withdrawal_from_pool(
                            rebalance_id=str(uuid.uuid4()),  # Generate a unique ID for this withdrawal
                            pool_address=pool_info['pool'],
                            amount=withdraw_amount,
                            protocol=pool_info['pool_name']
                        )
                        
                        if withdrawal_result.get("success"):
                            logger.info(f"✅ Successfully withdrew from pool: {withdrawal_result.get('transaction_hash')}")
                            remaining_shortfall -= withdraw_amount
                            withdrawal_txs.append(withdrawal_result.get('transaction_hash'))
                        else:
                            logger.error(f"Failed to withdraw from pool {pool_info['pool']}: {withdrawal_result.get('error')}")
                    except Exception as e:
                        logger.error(f"Error withdrawing from pool {pool_info['pool']}: {str(e)}")
                
                # Check updated idle balance after withdrawals
                updated_idle_balance = asset_contract.functions.balanceOf(self.yield_allocator_vault_address).call()
                logger.info(f"Updated idle asset balance: {self.format_with_decimals(updated_idle_balance, asset_decimals)} {asset_symbol}")
                
                if remaining_shortfall > 0:
                    logger.warning(f"Could not withdraw enough assets. Still need {self.format_with_decimals(remaining_shortfall, asset_decimals)} {asset_symbol}")
                    logger.warning("Some withdrawal requests may not be fulfilled")
                    logger.warning("Skipping withdrawal execution due to insufficient assets")
                    return {
                        'success': False, 
                        'error': f'Insufficient assets to fulfill withdrawal. Shortfall: {self.format_with_decimals(remaining_shortfall, asset_decimals)} {asset_symbol}',
                        'asset_symbol': asset_symbol,
                        'asset_decimals': asset_decimals,
                        'withdrawal_txs': withdrawal_txs if 'withdrawal_txs' in locals() else []
                    }
            else:
                logger.info("✅ Sufficient idle assets available to fulfill all requests")
            
            # Get vault balance before batch withdrawal
            vault_balance_before = asset_contract.functions.balanceOf(self.yield_allocator_vault_address).call()
            
            # Determine the batch size based on safe users
            # Process only one safe request at a time to minimize risk
            current_batch_size = min(1, len(safe_users))
            logger.info(f"Processing withdrawal requests with batch size {current_batch_size}")
            
            # Call AIAgent to fulfill the next batch of withdrawals
            logger.info(f"Executing fulfillBatchWithdrawals({current_batch_size}) on AIAgent")
            
            # Build transaction
            nonce = self.web3.eth.get_transaction_count(self.executor_address)
            gas_price = self.web3.eth.gas_price
            
            # Use explicit gas limit to avoid estimate_gas failures
            gas_limit = 3000000  # Higher gas limit for batch operations
            
            fulfill_tx = ai_agent_contract.functions.fulfillBatchWithdrawals(
                current_batch_size
            ).build_transaction({
                'from': self.executor_address,
                # 'gas': gas_limit,  # Explicit gas limit
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            
            # Sign and send transaction
            try:
                signed_tx = self.web3.eth.account.sign_transaction(fulfill_tx, self.executor_private_key)
                # Check if we're using web3.py v5 or v6
                if hasattr(signed_tx, 'rawTransaction'):
                    # web3.py v5
                    tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
                else:
                    # web3.py v6
                    tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            except AttributeError as e:
                logger.error(f"Transaction signing error: {str(e)}")
                # Try alternative attribute name (for different web3.py versions)
                if hasattr(signed_tx, 'raw_transaction'):
                    tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
                else:
                    raise ValueError(f"Cannot find raw transaction data in signed transaction: {str(signed_tx)}")
            
            logger.info(f"Transaction sent: {tx_hash.hex()}")
            logger.info(f"Waiting for transaction confirmation...")
            
            # Wait for transaction receipt
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            if receipt.status == 1:
                logger.info(f"✅ Transaction successful! Gas used: {receipt.gasUsed}")
                
                # Get vault balance after withdrawal
                vault_balance_after = asset_contract.functions.balanceOf(self.yield_allocator_vault_address).call()
                logger.info(f"Vault balance after withdrawal: {self.format_with_decimals(vault_balance_after, asset_decimals)} {asset_symbol}")
                
                # Calculate total withdrawal amount
                total_withdrawal_amount = vault_balance_before - vault_balance_after
                total_withdrawal_formatted = self.format_with_decimals(total_withdrawal_amount, asset_decimals)
                logger.info(f"Total withdrawal amount: {total_withdrawal_formatted} {asset_symbol}")
                
                # Check updated withdrawal queue length
                updated_withdrawal_queue_length = 0
                try:
                    i = 0
                    while True:
                        withdrawer = vault_contract.functions.pendingWithdrawers(i).call()
                        if withdrawer == '0x0000000000000000000000000000000000000000':
                            break
                        i += 1
                    updated_withdrawal_queue_length = i
                except Exception:
                    updated_withdrawal_queue_length = i
                
                processed_count = withdrawal_queue_length - updated_withdrawal_queue_length
                
                logger.info(f"Updated withdrawal queue length: {updated_withdrawal_queue_length}")
                logger.info(f"Processed {processed_count} withdrawal requests")
                
                return {
                    'success': True,
                    'tx_hash': tx_hash.hex(),
                    'gas_used': receipt.gasUsed,
                    'processed_count': processed_count,
                    'remaining_count': updated_withdrawal_queue_length,
                    'total_withdrawal_amount': total_withdrawal_amount,
                    'total_withdrawal_formatted': total_withdrawal_formatted,
                    'asset_symbol': asset_symbol,
                    'asset_decimals': asset_decimals,
                    'withdrawal_txs': withdrawal_txs if 'withdrawal_txs' in locals() else []
                }
            else:
                logger.error(f"❌ Transaction failed!")
                return {'success': False, 'error': 'Transaction failed', 'tx_hash': tx_hash.hex()}
            
        except Exception as e:
            import traceback
            error_message = str(e)
            
            # Handle contract logic errors more gracefully
            if 'execution reverted' in error_message:
                # Extract the revert reason if possible
                if 'revert:' in error_message:
                    revert_reason = error_message.split('revert:')[1].strip()
                    logger.error(f"Contract execution reverted: {revert_reason}")
                    error_message = f"Contract execution reverted: {revert_reason}"
                else:
                    logger.error(f"Contract execution reverted with unknown reason")
            
            logger.error(f"Error fulfilling batch withdrawals: {error_message}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            return {
                'success': False, 
                'error': error_message,
                'asset_symbol': asset_symbol if 'asset_symbol' in locals() else 'USDe',
                'asset_decimals': asset_decimals if 'asset_decimals' in locals() else 18,
                'withdrawal_txs': withdrawal_txs if 'withdrawal_txs' in locals() else []
            }
    
    def save_deposit_run_results(self, queue_info: Dict, result: Dict, start_time: float) -> None:
        """Save deposit run results to database"""
        try:
            end_time = time.time()
            execution_duration = end_time - start_time
            
            # Determine run status
            if result.get('success', False):
                status = 'success'
            else:
                status = 'failed'
            
            # Create the main run record
            # Convert large numeric values to strings to avoid overflow
            total_assets_to_deposit = queue_info.get('total_assets_to_deposit', 0)
            idle_assets_before = queue_info.get('idle_asset_balance', 0)
            
            run = VaultDepositRun.objects.create(
                status=status,
                vault_address=self.yield_allocator_vault_address,
                asset_address=queue_info.get('asset_address', ''),
                asset_symbol=queue_info.get('asset_symbol', ''),
                asset_decimals=queue_info.get('asset_decimals', 18),
                queue_length_before=queue_info.get('queue_length', 0),
                queue_length_after=result.get('remaining_count', queue_info.get('queue_length', 0)),
                processed_count=result.get('processed_count', 0),
                batch_size=self.max_batch_size,
                total_assets_to_deposit=str(total_assets_to_deposit),  # Convert to string
                idle_assets_before=str(idle_assets_before),  # Convert to string
                best_pool_address=result.get('best_pool_address', ''),
                best_pool_name=result.get('best_pool_name', 'Unknown'),
                error_message=result.get('error') if not result.get('success', False) else None,
                execution_duration_seconds=execution_duration
            )
            
            # Create transaction record if successful
            if result.get('success', False) and result.get('tx_hash'):
                VaultDepositTransaction.objects.create(
                    run=run,
                    transaction_hash=result.get('tx_hash', ''),
                    gas_used=result.get('gas_used', 0),
                    status='success'
                )
            
            logger.info(f"✅ Saved deposit run results to database (Run ID: {run.id})")
            logger.info(f"   - Status: {status}")
            logger.info(f"   - Processed count: {result.get('processed_count', 0)}")
            logger.info(f"   - Best pool: {result.get('best_pool_name', 'Unknown')} ({result.get('best_pool_address', '')})")
            logger.info(f"   - Execution time: {execution_duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Error saving deposit run results: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
    def save_withdrawal_run_results(self, withdrawal_info: Dict, result: Dict, start_time: float) -> None:
        """Save withdrawal run results to database"""
        try:
            end_time = time.time()
            execution_duration = end_time - start_time
            
            # Determine run status
            if result.get('success', False):
                status = 'success'
            else:
                status = 'failed'
            
            # Create the main run record
            run = VaultWithdrawalRun.objects.create(
                status=status,
                vault_address=self.yield_allocator_vault_address,
                queue_length_before=withdrawal_info.get('queue_length', 0),
                queue_length_after=result.get('remaining_count', withdrawal_info.get('queue_length', 0)),
                processed_count=result.get('processed_count', 0),
                batch_size=self.max_batch_size,
                total_withdrawal_amount=result.get('total_withdrawal_amount', 0),
                total_withdrawal_amount_formatted=result.get('total_withdrawal_formatted', 0),
                asset_symbol=result.get('asset_symbol', 'USDe'),
                asset_decimals=result.get('asset_decimals', 18),
                error_message=result.get('error') if not result.get('success', False) else None,
                execution_duration_seconds=execution_duration
            )
            
            # Create transaction record for the main batch withdrawal if successful
            if result.get('success', False) and result.get('tx_hash'):
                VaultWithdrawalTransaction.objects.create(
                    run=run,
                    transaction_hash=result.get('tx_hash', ''),
                    gas_used=result.get('gas_used', 0),
                    status='success'
                )
                
            # Create transaction records for any pool withdrawals that were executed
            if result.get('withdrawal_txs'):
                for tx_hash in result.get('withdrawal_txs', []):
                    VaultWithdrawalTransaction.objects.create(
                        run=run,
                        transaction_hash=tx_hash,
                        # gas_used=0,  # We don't have gas info for these transactions
                        status='success'
                    )
                logger.info(f"   - Added {len(result.get('withdrawal_txs', []))} pool withdrawal transactions")
            
            logger.info(f"✅ Saved withdrawal run results to database (Run ID: {run.id})")
            logger.info(f"   - Status: {status}")
            logger.info(f"   - Processed count: {result.get('processed_count', 0)}")
            logger.info(f"   - Total withdrawal: {result.get('total_withdrawal_formatted', 0)} {result.get('asset_symbol', 'USDe')}")
            logger.info(f"   - Execution time: {execution_duration:.2f}s")
            
        except Exception as e:
            logger.error(f"Error saving withdrawal run results: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
    
    def get_pool_name_from_address(self, pool_address: str) -> str:
        """
        Get the protocol/pool name from a pool address.
        
        Args:
            pool_address: The address of the pool
            
        Returns:
            The name of the protocol/pool, or 'Unknown' if not found
        """
        try:
            # Common protocol addresses mapping
            protocol_mapping = {
                '0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b'.lower(): 'Hyperrfi',
                '0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b'.lower(): 'Hyperlend',
                '0x835FEBF893c6DdDee5CF762B0f8e31C5B06938ab'.lower(): 'Felix USDe',
                '0xfc5126377f0efc0041c0969ef9ba903ce67d151e'.lower(): 'Felix USDT0'
            }
            
            # Try to get from mapping first
            if pool_address.lower() in protocol_mapping:
                return protocol_mapping[pool_address.lower()]
            
            # Default
            return 'Unknown'
        except Exception as e:
            logger.error(f"Error getting pool name from address: {str(e)}")
            return 'Unknown'
            
    def is_felix_pool(self, pool_address: str) -> bool:
        """
        Check if a pool is a Felix pool based on its address or name.
        
        Args:
            pool_address: The address of the pool to check
            
        Returns:
            True if the pool is a Felix pool, False otherwise
        """
        try:
            # Check if the pool name contains 'Felix'
            pool_name = self.get_pool_name_from_address(pool_address)
            if 'Felix' in pool_name:
                return True
                
            # Known Felix pool addresses
            felix_pool_addresses = [
                '0x835FEBF893c6DdDee5CF762B0f8e31C5B06938ab'.lower(),  # Felix USDe
                '0xfc5126377f0efc0041c0969ef9ba903ce67d151e'.lower()   # Felix USDT0
            ]
            
            return pool_address.lower() in felix_pool_addresses
        except Exception as e:
            logger.error(f"Error checking if pool is Felix pool: {str(e)}")
            return False
            
    def get_felix_max_withdrawable(self, pool_address: str) -> dict:
        """
        Get the maximum withdrawable amount from a Felix pool.
        
        This function checks the maxWithdraw value for the vault in the Felix pool,
        as well as the share balance and asset value of those shares.
        
        Args:
            pool_address: Address of the Felix pool
            
        Returns:
            Dictionary with max_withdraw_amount, asset_value, and share_balance
        """
        result = {
            'success': False,
            'max_withdraw_amount': 0,
            'asset_value': 0,
            'share_balance': 0,
            'error': None
        }
        
        try:
            # Get the vault contract
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=self.get_contract_abis()["YieldAllocatorVault"]
            )
            
            # Get asset token info
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=self.get_contract_abis()["ERC20"]
            )
            asset_decimals = asset_contract.functions.decimals().call()
            asset_symbol = asset_contract.functions.symbol().call()
            
            # Get Felix pool contract instance with ERC4626 functions
            felix_pool_abi = [
                {"inputs":[{"name":"owner","type":"address"}],"name":"maxWithdraw","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
                {"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"},
                {"inputs":[{"name":"shares","type":"uint256"}],"name":"convertToAssets","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}
            ]
            
            felix_pool = self.web3.eth.contract(
                address=self.web3.to_checksum_address(pool_address),
                abi=felix_pool_abi
            )
            
            # Get vault's share balance in Felix pool
            share_balance = felix_pool.functions.balanceOf(self.yield_allocator_vault_address).call()
            logger.info(f"Vault's share balance in Felix: {self.format_with_decimals(share_balance, asset_decimals)}")
            
            # Get asset value of shares
            asset_value = felix_pool.functions.convertToAssets(share_balance).call()
            logger.info(f"Asset value of shares: {self.format_with_decimals(asset_value, asset_decimals)} {asset_symbol}")
            
            # Get max withdraw amount
            max_withdraw_amount = felix_pool.functions.maxWithdraw(self.yield_allocator_vault_address).call()
            logger.info(f"Max withdraw amount: {self.format_with_decimals(max_withdraw_amount, asset_decimals)} {asset_symbol}")
            
            result['success'] = True
            result['max_withdraw_amount'] = max_withdraw_amount
            result['asset_value'] = asset_value
            result['share_balance'] = share_balance
            result['asset_decimals'] = asset_decimals
            result['asset_symbol'] = asset_symbol
            
            return result
            
        except Exception as e:
            logger.error(f"Error getting Felix pool max withdrawable amount: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            result['error'] = str(e)
            return result
    
    def get_protocol_info(self) -> Dict:
        """Get protocol information including pending deposits, withdrawals, and pool allocations"""
        try:
            abis = self.get_contract_abis()
            
            # Get YieldAllocatorVault contract
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=abis['YieldAllocatorVault']
            )
            
            # Get WhitelistRegistry contract
            whitelist_registry_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.whitelist_registry_address),
                abi=abis['WhitelistRegistry']
            )
            
            # Get deposit queue information
            deposit_queue_length = vault_contract.functions.depositQueueLength().call()
            logger.info(f"Deposit queue length: {deposit_queue_length}")
            
            # Get withdrawal queue information and total withdrawal assets needed
            withdrawal_queue_length = 0
            total_withdrawal_assets_needed = 0
            
            try:
                # Keep checking indices until we get an error (no more withdrawers)
                i = 0
                while True:
                    try:
                        withdrawer = vault_contract.functions.pendingWithdrawers(i).call()
                        if withdrawer == '0x0000000000000000000000000000000000000000':
                            break
                            
                        # Get withdrawal request details - just add to total assets needed
                        withdrawal_request = vault_contract.functions.withdrawalRequests(withdrawer).call()
                        if withdrawal_request[2]:  # exists
                            assets_at_request = withdrawal_request[0]
                            total_withdrawal_assets_needed += int(assets_at_request)
                            
                        i += 1
                    except Exception as e:
                        logger.debug(f"Error reading withdrawal request at index {i}: {str(e)}")
                        break
                        
                withdrawal_queue_length = i
            except Exception as e:
                # We've reached the end of the array
                logger.debug(f"Error reading pendingWithdrawers: {str(e)}")
                withdrawal_queue_length = i
            
            # logger.info(f"Withdrawal queue length: {withdrawal_queue_length}")
            # logger.info(f"Total withdrawal assets needed: {self.format_with_decimals(total_withdrawal_assets_needed, asset_decimals)} {asset_symbol}")
            
            # Get asset token details
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=abis['ERC20']
            )
            
            # Get asset details
            try:
                asset_symbol = asset_contract.functions.symbol().call()
                asset_decimals = asset_contract.functions.decimals().call()
            except Exception:
                # Fallback values if contract calls fail
                asset_symbol = "USDe"
                asset_decimals = 18
                logger.warning(f"Using default symbol and decimals for asset token")
            
            # Check current idle asset balance in vault
            idle_asset_balance = asset_contract.functions.balanceOf(
                self.web3.to_checksum_address(self.yield_allocator_vault_address)
            ).call()
            
            # Get total assets and supply
            total_assets = vault_contract.functions.totalAssets().call()
            total_supply = 0
            try:
                total_supply = vault_contract.functions.totalSupply().call()
            except Exception:
                logger.warning("Could not get total supply")
            
            # Calculate share price
            share_price = 0
            if total_supply > 0:
                # Calculate price per share using (totalAssets * 10^18) / totalSupply
                share_price = (int(total_assets) * (10**18)) // int(total_supply)
            else:
                # Default to 1:1 if no shares
                share_price = 10**18
                
            logger.info(f"Share price: {self.format_with_decimals(share_price, asset_decimals)} {asset_symbol} per share")
            
            # Try alternative method using convertToAssets
            share_price_via_convert = 0
            try:
                one_share = asset_decimals  #10**18  # 1 share with 18 decimals
                assets_per_share = vault_contract.functions.convertToAssets(one_share).call()
                share_price_via_convert = assets_per_share
                logger.info(f"Share price (via convertToAssets): {self.format_with_decimals(assets_per_share, asset_decimals)} {asset_symbol} per share")
            except Exception as e:
                logger.warning(f"Could not calculate share price via convertToAssets: {str(e)}")
            
            # Calculate allocated assets (total - idle)
            allocated_assets = int(total_assets) - int(idle_asset_balance)
            
            # Format for readability
            formatted_idle_balance = self.format_with_decimals(idle_asset_balance, asset_decimals)
            formatted_total_assets = self.format_with_decimals(total_assets, asset_decimals)
            formatted_allocated_assets = self.format_with_decimals(allocated_assets, asset_decimals)
            
            logger.info(f"Asset token: {asset_symbol} ({asset_decimals} decimals)")
            logger.info(f"Idle asset balance: {formatted_idle_balance} {asset_symbol}")
            logger.info(f"Total assets: {formatted_total_assets} {asset_symbol}")
            logger.info(f"Allocated assets in pools: {formatted_allocated_assets} {asset_symbol}")
            
            # Get all whitelisted pools
            whitelisted_pools = []
            try:
                whitelisted_pools = whitelist_registry_contract.functions.getWhitelistedPools().call()
                logger.info(f"Number of whitelisted pools: {len(whitelisted_pools)}")
            except Exception as e:
                logger.error(f"Error getting whitelisted pools: {str(e)}")
            
            # Check balances in each pool
            pool_balances = []
            logger.info("Pool balances:")
            
            # fetch pool allocations 
            for i, pool_address in enumerate(whitelisted_pools):
                try:
                    # Get pool balance
                    pool_balance = vault_contract.functions.poolPrincipal(pool_address).call()
                    
                    # Get pool kind from WhitelistRegistry
                    pool_kind_value = whitelist_registry_contract.functions.getPoolKind(pool_address).call()
                    pool_kind_name = "AAVE" if pool_kind_value == 0 else "ERC4626"
                    
                    # Try to get pool name/info if possible
                    pool_name = f"Pool {i+1}"
                    try:
                        pool_contract = self.web3.eth.contract(
                            address=self.web3.to_checksum_address(pool_address),
                            abi=abis['ERC20']
                        )
                        try:
                            name = pool_contract.functions.name().call()
                            if name:
                                pool_name = name
                        except Exception:
                            # If name() fails, try symbol()
                            try:
                                symbol = pool_contract.functions.symbol().call()
                                if symbol:
                                    pool_name = symbol
                            except Exception:
                                # Keep default name
                                pass
                    except Exception:
                        # Keep default name if contract interaction fails
                        pass
                    
                    # Calculate percentage of total assets
                    percentage = 0
                    if int(total_assets) > 0:
                        percentage = (int(pool_balance) * 10000) // int(total_assets) / 100
                    
                    logger.info(f"  {pool_name} ({pool_address}) [{pool_kind_name}]: {self.format_with_decimals(pool_balance, asset_decimals)} {asset_symbol} ({percentage:.2f}%)")
                    
                    pool_balances.append({
                        'address': pool_address,
                        'balance': pool_balance,
                        'formatted_balance': self.format_with_decimals(pool_balance, asset_decimals),
                        'decimals': asset_decimals,
                        'percentage': percentage
                    })
                except Exception as e:
                    logger.error(f"Error getting balance for pool {pool_address}: {str(e)}")
            
            
            
            return {
                'deposit_queue_length': deposit_queue_length,
                'withdrawal_queue_length': withdrawal_queue_length,
                'total_withdrawal_assets_needed': total_withdrawal_assets_needed,
                'asset_address': asset_address,
                'asset_symbol': asset_symbol,
                'asset_decimals': asset_decimals,
                'idle_asset_balance': idle_asset_balance,
                'total_assets': total_assets,
                'total_supply': total_supply,
                'allocated_assets': allocated_assets,
                'share_price': share_price,
                'share_price_via_convert': share_price_via_convert,
                'whitelisted_pools': whitelisted_pools,
                'pool_balances': pool_balances,
            }
            
        except Exception as e:
            logger.error(f"Error getting protocol info: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return {}
    
    def execute_vault_rebalance(self, from_pool_address, to_pool_address, amount, from_protocol, to_protocol, from_apy, to_apy):
        """
        Execute a rebalance operation between two pools.
        
        This function handles the complete rebalancing process:
        1. Withdraws funds from the source pool
        2. Deposits funds to the destination pool
        3. Records both transactions in the VaultRebalance table
        
        Args:
            from_pool_address: Address of the source pool
            to_pool_address: Address of the destination pool
            amount: Amount to move (in token units)
            from_protocol: Name of the source protocol
            to_protocol: Name of the destination protocol
            
        Returns:
            Dictionary with results of the rebalance operation
        """
        # Generate a unique ID for this rebalance operation
        rebalance_id = str(uuid.uuid4())
        logger.info(f"Starting rebalance operation {rebalance_id}")
        logger.info(f"Moving {amount} from {from_protocol} ({from_pool_address}) to {to_protocol} ({to_pool_address})")
        
        # Get APY values for source and destination pools
        current_apy_from = float(from_apy) * 100
        new_apy_to = float(to_apy) * 100
        
        # Calculate APY improvement in basis points
        try:
            apy_improvement_bps = int((float(new_apy_to) - float(current_apy_from)) * 100)  # Convert to basis points
        except (ValueError, TypeError):
            apy_improvement_bps = 0
            
        # Check if APY improvement is greater than 50 basis points
        if apy_improvement_bps <= 50:
            logger.info(f"Skipping rebalance operation: APY improvement of {apy_improvement_bps} bps is not greater than the minimum threshold of 50 bps")
            return {
                "rebalance_id": rebalance_id,
                "from_pool_address": from_pool_address,
                "to_pool_address": to_pool_address,
                "amount": amount,
                "from_protocol": from_protocol,
                "to_protocol": to_protocol,
                "withdrawal_tx": None,
                "deposit_tx": None,
                "success": False,
                "error": f"APY improvement of {apy_improvement_bps} bps is below the minimum threshold of 50 bps",
                "strategy_summary": None
            }
            
        # Determine amount description based on pool balances
        total_balance = 0
        from_pool_balance = 0
        
        # Get protocol info to check if this is the entire position
        protocol_info = self.get_protocol_info()
        if protocol_info and 'pool_balances' in protocol_info:
            for pool in protocol_info.get('pool_balances', []):
                if pool.get('address') == from_pool_address:
                    from_pool_balance = int(pool.get('balance', 0))
                total_balance += int(pool.get('balance', 0))
        
        # Determine if this is the entire position or partial
        amount_description = "the entire position"
        if from_pool_balance > 0 and amount < from_pool_balance:
            percentage = (amount / from_pool_balance) * 100
            amount_description = f"approximately {percentage:.0f}% of the position"
        
        # Generate strategy summary using GPT
        recommendation = {
            "action": "rebalance",
            "reason": f"Optimizing yield allocation for {apy_improvement_bps} bps improvement",
            "from_protocol": from_protocol,
            "to_protocol": to_protocol,
            "amount": self.format_with_decimals(amount, 18),  # Assuming 18 decimals for display
            "amount_description": amount_description,
            "current_apy_from": current_apy_from,
            "new_apy_to": new_apy_to,
            "current_best_pool": to_protocol
        }
        
        strategy_summary = None
        try:
            strategy_summary = summarize_strategy_with_gpt(recommendation)
            logger.info(f"Generated strategy summary: {strategy_summary}")
        except Exception as e:
            logger.error(f"Error generating strategy summary: {str(e)}")
        
        result = {
            "rebalance_id": rebalance_id,
            "from_pool_address": from_pool_address,
            "to_pool_address": to_pool_address,
            "amount": amount,
            "from_protocol": from_protocol,
            "to_protocol": to_protocol,
            "withdrawal_tx": None,
            "deposit_tx": None,
            "success": False,
            "error": None,
            "strategy_summary": strategy_summary
        }
        
        try:
            # Step 1: Execute withdrawal from source pool
            withdrawal_result = self.execute_withdrawal_from_pool(
                rebalance_id=rebalance_id,
                pool_address=from_pool_address,
                amount=amount,
                protocol=from_protocol,
                strategy_summary=strategy_summary
            )
            
            if not withdrawal_result.get("success"):
                result["error"] = f"Withdrawal failed: {withdrawal_result.get('error')}"
                return result
            
            result["withdrawal_tx"] = withdrawal_result.get("transaction_hash")
            
            # Step 2: Execute deposit to destination pool
            deposit_result = self.execute_deposit_to_pool(
                rebalance_id=rebalance_id,
                pool_address=to_pool_address,
                amount=amount,
                protocol=to_protocol,
                strategy_summary=strategy_summary
            )
            
            if not deposit_result.get("success"):
                result["error"] = f"Deposit failed: {deposit_result.get('error')}"
                return result
            
            result["deposit_tx"] = deposit_result.get("transaction_hash")
            result["success"] = True
            
            logger.info(f"Rebalance operation {rebalance_id} completed successfully")
            logger.info(f"Withdrawal TX: {result['withdrawal_tx']}")
            logger.info(f"Deposit TX: {result['deposit_tx']}")
            
            return result
        
        except Exception as e:
            logger.error(f"Error during rebalance operation: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            result["error"] = str(e)
            return result

    def execute_withdrawal_from_pool(self, rebalance_id, pool_address, amount, protocol, strategy_summary=None):
        """
        Execute a withdrawal from a pool and record the transaction.
        
        Args:
            rebalance_id: Unique ID for the rebalance operation
            pool_address: Address of the pool to withdraw from
            amount: Amount to withdraw
            protocol: Name of the protocol
            strategy_summary: Optional strategy summary to include in the record
            
        Returns:
            Dictionary with results of the withdrawal operation
        """
        logger.info(f"Executing withdrawal from {protocol} ({pool_address})")
        
        result = {
            "success": False,
            "transaction_hash": None,
            "error": None,
            "block_number": None,
            "gas_used": None
        }
        
        # Create a record in the database for this withdrawal
        withdrawal_record = VaultRebalance(
            rebalance_id=rebalance_id,
            transaction_type=VaultRebalance.WITHDRAWAL,
            status=VaultRebalance.PENDING,
            from_protocol=protocol,
            from_pool_address=pool_address,
            amount_token_raw=str(amount),
            token_symbol=self.underlying_token_symbol,
            strategy_summary=strategy_summary
        )
        withdrawal_record.save()
        
        try:
            # Get the AI Agent contract
            ai_agent_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.ai_agent_address),
                abi=self.get_contract_abis()["AIAgent"]
            )
            
            # Get the vault contract
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=self.get_contract_abis()["YieldAllocatorVault"]
            )
            
            # Get asset token info
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=self.get_contract_abis()["ERC20"]
            )
            asset_decimals = asset_contract.functions.decimals().call()
            asset_symbol = asset_contract.functions.symbol().call()
            
            # Format amount for display
            formatted_amount = self.format_with_decimals(amount, asset_decimals)
            withdrawal_record.amount_token = formatted_amount
            withdrawal_record.token_decimals = asset_decimals
            withdrawal_record.save()
            
            # Check if this is a Felix pool and handle withdrawal limit
            withdraw_amount = amount
            if self.is_felix_pool(pool_address):
                logger.info(f"⚠️ Source is Felix pool (ERC4626). Checking maxWithdraw limit...")
                
                # Get max withdrawable amount from Felix pool
                felix_data = self.get_felix_max_withdrawable(pool_address)
                
                if felix_data['success']:
                    # Get the max withdraw amount
                    max_withdraw_amount = felix_data['max_withdraw_amount']
                    asset_value = felix_data['asset_value']
                    share_balance = felix_data['share_balance']
                    
                    # Compare with requested withdrawal amount
                    if withdraw_amount > max_withdraw_amount:
                        logger.warning(f"⚠️ Requested withdrawal ({self.format_with_decimals(withdraw_amount, asset_decimals)} {asset_symbol}) exceeds max withdraw limit")
                        logger.warning(f"⚠️ Limiting withdrawal to max withdraw amount: {self.format_with_decimals(max_withdraw_amount, asset_decimals)} {asset_symbol}")
                        
                        # Update the withdrawal amount to the max withdrawable
                        withdraw_amount = max_withdraw_amount
                        
                        # Update the record with the new amount
                        withdrawal_record.amount_token_raw = str(withdraw_amount)
                        withdrawal_record.amount_token = self.format_with_decimals(withdraw_amount, asset_decimals)
                        withdrawal_record.save()
                    
                    # Log Felix pool analysis
                    logger.info(f"\nFelix Pool Analysis:")
                    logger.info(f"- Recorded Principal: {self.format_with_decimals(vault_contract.functions.poolPrincipal(pool_address).call(), asset_decimals)} {asset_symbol}")
                    logger.info(f"- Actual Asset Value: {self.format_with_decimals(asset_value, asset_decimals)} {asset_symbol}")
                    logger.info(f"- Max Withdraw Amount: {self.format_with_decimals(max_withdraw_amount, asset_decimals)} {asset_symbol}")
                    logger.info(f"- Amount to Withdraw: {self.format_with_decimals(withdraw_amount, asset_decimals)} {asset_symbol}")
                else:
                    logger.warning(f"Could not query Felix pool directly: {felix_data.get('error')}")
                    logger.warning("Proceeding with standard withdrawal method...")
                    
                    # Fallback to using recorded principal
                    pool_principal = vault_contract.functions.poolPrincipal(pool_address).call()
                    if withdraw_amount > pool_principal:
                        logger.warning(f"⚠️ Limiting withdrawal to principal amount: {self.format_with_decimals(pool_principal, asset_decimals)} {asset_symbol}")
                        withdraw_amount = pool_principal
                        
                        # Update the record with the new amount
                        withdrawal_record.amount_token_raw = str(withdraw_amount)
                        withdrawal_record.amount_token = self.format_with_decimals(withdraw_amount, asset_decimals)
                        withdrawal_record.save()
            
            # Check if withdraw amount is valid
            if withdraw_amount <= 0:
                error_msg = "Error: Withdraw amount must be greater than 0"
                logger.error(error_msg)
                withdrawal_record.status = VaultRebalance.FAILED
                withdrawal_record.error_message = error_msg
                withdrawal_record.save()
                result["error"] = error_msg
                return result
            
            # Build transaction
            nonce = self.web3.eth.get_transaction_count(self.executor_address)
            gas_price = self.web3.to_wei(self.gas_price_gwei, 'gwei')
            
            # Prepare the withdrawFromPool transaction
            logger.info(f"withdrawing asset {asset_address} amount {withdraw_amount} decimals {asset_decimals}")
            tx = ai_agent_contract.functions.withdrawFromPool(
                self.web3.to_checksum_address(pool_address),
                withdraw_amount
            ).build_transaction({
                'from': self.executor_address,
                # 'gas': 500000,  # Set a specific gas limit to avoid insufficient funds
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            
            # Sign and send the transaction
            signed_tx = self.web3.eth.account.sign_transaction(tx, private_key=self.executor_private_key)
            # Check if we're using web3.py v5 or v6
            if hasattr(signed_tx, 'rawTransaction'):
                # web3.py v5
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            else:
                # web3.py v6
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # Wait for transaction receipt
            logger.info(f"Withdrawal transaction sent: {tx_hash.hex()}")
            logger.info("Waiting for transaction confirmation...")
            tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            # Update the record with transaction details
            withdrawal_record.transaction_hash = tx_hash.hex()
            withdrawal_record.block_number = tx_receipt.blockNumber
            withdrawal_record.gas_used = tx_receipt.gasUsed
            withdrawal_record.gas_price = gas_price
            
            if tx_receipt.status == 1:
                withdrawal_record.status = VaultRebalance.COMPLETED
                result["success"] = True
                result["transaction_hash"] = tx_hash.hex()
                result["block_number"] = tx_receipt.blockNumber
                result["gas_used"] = tx_receipt.gasUsed
                logger.info(f"Withdrawal successful: {tx_hash.hex()}")
            else:
                withdrawal_record.status = VaultRebalance.FAILED
                withdrawal_record.error_message = "Transaction failed"
                result["error"] = "Transaction failed"
                logger.error(f"Withdrawal failed: {tx_hash.hex()}")
            
            withdrawal_record.save()
            return result
            
        except Exception as e:
            logger.error(f"Error during withdrawal: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            withdrawal_record.status = VaultRebalance.FAILED
            withdrawal_record.error_message = str(e)
            withdrawal_record.save()
            
            result["error"] = str(e)
            return result

    def settle_failed_rebalances(self, protocol_info):
        """
        Check for failed rebalance operations with successful withdrawals but failed deposits.
        Attempt to settle these operations using idle assets in the vault.
        
        This function should be called before rebalance_based_on_optimizer to ensure
        that any idle assets resulting from failed rebalances are properly handled.
        
        Args:
            protocol_info: Dictionary with protocol information including idle_asset_balance
            
        Returns:
            Boolean indicating if any failed rebalances were settled
        """
        logger.info("============================================================")
        logger.info("Checking for failed rebalances to settle")
        logger.info("============================================================")
        
        # Check if we have idle assets to work with
        idle_asset_balance = protocol_info.get('idle_asset_balance', 0)
        asset_decimals = protocol_info.get('asset_decimals', 6)
        asset_symbol = protocol_info.get('asset_symbol', '')
        
        if not idle_asset_balance or int(idle_asset_balance) <= 0:
            logger.info("No idle assets available to settle failed rebalances")
            return False
            
        formatted_idle_balance = self.format_with_decimals(idle_asset_balance, asset_decimals)
        logger.info(f"Available idle assets: {formatted_idle_balance} {asset_symbol}")
        
        # Find failed rebalances with successful withdrawals but failed deposits
        from django.db.models import Q
        
        # Get distinct rebalance IDs with failed deposit status
        failed_rebalances = VaultRebalance.objects.filter(
            Q(transaction_type=VaultRebalance.DEPOSIT) & 
            Q(status=VaultRebalance.FAILED)
        ).values_list('rebalance_id', flat=True).distinct()
        
        if not failed_rebalances:
            logger.info("No failed rebalances found")
            return False
            
        settled_count = 0
        
        for rebalance_id in failed_rebalances:
            try:
                # Get the first successful withdrawal for this rebalance
                withdrawals = VaultRebalance.objects.filter(
                    rebalance_id=rebalance_id,
                    transaction_type=VaultRebalance.WITHDRAWAL,
                    status=VaultRebalance.COMPLETED
                ).order_by('-created_at')
                
                if not withdrawals.exists():
                    logger.info(f"No successful withdrawal found for rebalance {rebalance_id}")
                    continue
                    
                withdrawal = withdrawals.first()
                
                # Get the first failed deposit for this rebalance
                failed_deposits = VaultRebalance.objects.filter(
                    rebalance_id=rebalance_id,
                    transaction_type=VaultRebalance.DEPOSIT,
                    status=VaultRebalance.FAILED
                ).order_by('-created_at')
                
                if not failed_deposits.exists():
                    logger.info(f"No failed deposit found for rebalance {rebalance_id}")
                    continue
                    
                failed_deposit = failed_deposits.first()
                
                # Check if we have enough idle assets to settle this rebalance
                amount = int(withdrawal.amount_token_raw)
                if amount > int(idle_asset_balance):
                    logger.info(f"Insufficient idle assets to settle rebalance {rebalance_id}")
                    logger.info(f"Required: {self.format_with_decimals(amount, asset_decimals)} {asset_symbol}")
                    logger.info(f"Available: {formatted_idle_balance} {asset_symbol}")
                    
                    # Mark the rebalance as rejected
                    failed_deposit.error_message = f"{failed_deposit.error_message} | Rejected: Insufficient idle assets to settle"
                    failed_deposit.save()
                    continue
                
                logger.info(f"Settling failed rebalance {rebalance_id}")
                logger.info(f"Original withdrawal from {withdrawal.from_protocol} ({withdrawal.from_pool_address}) was successful")
                logger.info(f"Original deposit to {failed_deposit.to_protocol} ({failed_deposit.to_pool_address}) failed")
                logger.info(f"Amount: {self.format_with_decimals(amount, asset_decimals)} {asset_symbol}")
                
                # Execute the deposit using the idle assets
                deposit_result = self.execute_deposit_to_pool(
                    rebalance_id=rebalance_id,
                    pool_address=failed_deposit.to_pool_address,
                    amount=amount,
                    protocol=failed_deposit.to_protocol
                )
                
                if deposit_result.get("success"):
                    logger.info(f"Successfully settled rebalance {rebalance_id}")
                    settled_count += 1
                    
                    # Update idle asset balance for next iteration
                    idle_asset_balance = int(idle_asset_balance) - amount
                    formatted_idle_balance = self.format_with_decimals(idle_asset_balance, asset_decimals)
                else:
                    logger.error(f"Failed to settle rebalance {rebalance_id}: {deposit_result.get('error')}")
                
            except Exception as e:
                logger.error(f"Error processing rebalance {rebalance_id}: {str(e)}")
                continue
        
        if settled_count > 0:
            logger.info(f"Successfully settled {settled_count} failed rebalances")
            return True
        else:
            logger.info("No failed rebalances were settled")
            return False

    def rebalance_based_on_optimizer(self):
        """
        Run the optimizer and execute rebalancing if recommended.
        This function analyzes current pool APYs and positions to determine if rebalancing
        would be profitable, and executes the rebalancing if it would improve yield.
        
        Applies the following thresholds:
        - Pool allocations less than $0.01 are considered as zero
        - Rebalance transactions less than $1 are skipped
        """
        logger.info("=" * 60)
        logger.info("Running optimizer to determine if rebalancing is needed")
        logger.info("=" * 60)
        
        # Define minimum thresholds
        MIN_POOL_ALLOCATION_USD = 0.01  # $0.01 minimum pool allocation
        MIN_REBALANCE_AMOUNT_USD = 1.0  # $1 minimum rebalance amount
        
        try:
            # Get protocol info including pool balances
            protocol_info = self.get_protocol_info()
            if not protocol_info:
                logger.error("Failed to get protocol info for rebalancing. Aborting.")
                return
            
            # Get asset decimals for conversion
            asset_decimals = protocol_info.get('asset_decimals', 18)
            asset_symbol = protocol_info.get('asset_symbol', 'USDe')
            
            # Get pool data from API
            latest_hyperlend, latest_hypurrfi, latest_felix = self.get_latest_pool_apys(self.underlying_token_symbol)
            
            # Check if we have any yield reports
            if not latest_hyperlend and not latest_hypurrfi and not latest_felix:
                logger.error("No yield reports found for any protocol. Cannot proceed with optimization.")
                return None
                
            # Build cron_struct for optimizer
            cron_struct = {}
            
            # Add HyperLend pool
            if latest_hyperlend and latest_hyperlend.pool_address:
                hyperlend_params = json.loads(latest_hyperlend.params) if isinstance(latest_hyperlend.params, str) else latest_hyperlend.params
                cron_struct[latest_hyperlend.pool_address] = {
                    'protocol': 'HyperLend',
                    'current_apy': float(latest_hyperlend.apy),
                    'tvl': float(latest_hyperlend.tvl),
                    'utilization': float(hyperlend_params.get('utilization', 0)),
                    'kink': float(hyperlend_params.get('kink', 0.8)),
                    'slope1': float(hyperlend_params.get('slope1')),
                    'slope2': float(hyperlend_params.get('slope2')),
                    'reserve_factor': float(hyperlend_params.get('reserve_factor'))
                }
            
            # Add HypurrFi pool
            if latest_hypurrfi and latest_hypurrfi.pool_address:
                hypurrfi_params = json.loads(latest_hypurrfi.params) if isinstance(latest_hypurrfi.params, str) else latest_hypurrfi.params
                cron_struct[latest_hypurrfi.pool_address] = {
                    'protocol': 'HyperFi',
                    'current_apy': float(latest_hypurrfi.apy),
                    'tvl': float(latest_hypurrfi.tvl),
                    'utilization': float(hypurrfi_params.get('utilization', 0)),
                    'kink': float(hypurrfi_params.get('kink', 0.8)),
                    'slope1': float(hypurrfi_params.get('slope1')),
                    'slope2': float(hypurrfi_params.get('slope2')),
                    'reserve_factor': float(hypurrfi_params.get('reserve_factor'))
                }
            
            # Add Felix pool
            if latest_felix and latest_felix.pool_address:
                felix_params = json.loads(latest_felix.params) if isinstance(latest_felix.params, str) else latest_felix.params
                cron_struct[latest_felix.pool_address] = {
                    'protocol': 'Felix',
                    'current_apy': float(latest_felix.apy),
                    'tvl': float(latest_felix.tvl),
                    'utilization': float(felix_params.get('utilization', 0)),
                    'params': felix_params
                }
            
            # Build current position dictionary with minimum threshold applied
            current_position = {}
            logger.info(f"Applying minimum pool allocation threshold of ${MIN_POOL_ALLOCATION_USD}")
            
            for pool in protocol_info.get('pool_balances', []):
                pool_address = pool.get('address')
                balance = int(pool.get('balance', 0))
                formatted_balance = float(self.format_with_decimals(balance, asset_decimals))
                
                # Apply minimum pool allocation threshold
                if formatted_balance < MIN_POOL_ALLOCATION_USD:
                    logger.info(f"Pool {pool_address} balance ({formatted_balance} {asset_symbol}) is below minimum threshold of ${MIN_POOL_ALLOCATION_USD}, treating as zero")
                    current_position[pool_address] = 0
                else:
                    current_position[pool_address] = balance
            
            # Run optimizer
            current_best_pool_address = None
            try:
                # Parse the cron_struct to get pool data
                pools = parse_cron_struct(cron_struct)
                pool_data = {addr: pool for addr, pool in pools.items() if isinstance(pool, CronPoolData)}

                # Test direct recommendation function
                logger.info("\n=== Testing Most Profitable Reallocation Function ===")
                recommendation = find_most_profitable_reallocation(pool_data, current_position)
                current_best_pool_address = recommendation.get('current_best_pool_address')
                logger.info(f"Optimizer result: {recommendation}")
                logger.info(f"Current best pool address: {current_best_pool_address}")
                
                if recommendation.get('action') == 'reallocate':
                    from_address = recommendation.get('from_address')
                    to_address = recommendation.get('to_address')
                    from_protocol = recommendation.get('from_protocol')
                    to_protocol = recommendation.get('to_protocol')
                    amount = int(recommendation.get('amount', 0))
                    
                    # Check if rebalance amount meets minimum threshold
                    formatted_amount = float(self.format_with_decimals(amount, asset_decimals))
                    if formatted_amount < MIN_REBALANCE_AMOUNT_USD:
                        logger.info(f"⚠️ Skipping rebalance: Amount to move ({formatted_amount} {asset_symbol}) is below minimum threshold of ${MIN_REBALANCE_AMOUNT_USD}")
                        return current_best_pool_address
                    
                    logger.info(f"Optimizer recommends moving {amount} from {from_protocol.protocol} to {to_protocol.protocol}")
                    logger.info(f"Formatted amount: {formatted_amount} {asset_symbol}")
                    logger.info(f"Expected improvement: {recommendation.get('gain_bps')} bps")
                    
                    # Execute rebalance
                    rebalance_result = self.execute_vault_rebalance(
                        from_pool_address=from_address,
                        to_pool_address=to_address,
                        amount=amount,
                        from_protocol=from_protocol.protocol,
                        to_protocol=to_protocol.protocol,
                        from_apy=from_protocol.current_apy,
                        to_apy=to_protocol.current_apy
                    )
                    
                    if rebalance_result.get('success'):
                        logger.info("Rebalancing completed successfully")
                    else:
                        logger.error(f"Rebalancing failed: {rebalance_result.get('error')}")
                else:
                    logger.info("No profitable rebalancing opportunity found")

                return current_best_pool_address
            except Exception as e:
                logger.error(f"Error running optimizer: {str(e)}")
                logger.error("Falling back to simple comparison method")
                return None
                
        except Exception as e:
            logger.error(f"Error during rebalancing: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
    
    def execute_deposit_to_pool(self, rebalance_id, pool_address, amount, protocol, strategy_summary=None):
        """
        Execute a deposit to a pool and record the transaction.
        
        Args:
            rebalance_id: Unique ID for the rebalance operation
            pool_address: Address of the pool to deposit to
            amount: Amount to deposit
            protocol: Name of the protocol
            
        Returns:
            Dictionary with results of the deposit operation
        """
        logger.info(f"Executing deposit to {protocol} ({pool_address})")
        
        result = {
            "success": False,
            "transaction_hash": None,
            "error": None,
            "block_number": None,
            "gas_used": None
        }
        
        # Create a record in the database for this deposit
        deposit_record = VaultRebalance(
            rebalance_id=rebalance_id,
            transaction_type=VaultRebalance.DEPOSIT,
            status=VaultRebalance.PENDING,
            to_protocol=protocol,
            to_pool_address=pool_address,
            amount_token_raw=str(amount),
            token_symbol=self.underlying_token_symbol,
            strategy_summary=strategy_summary
        )
        deposit_record.save()
        
        try:
            # Get the AI Agent contract
            ai_agent_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.ai_agent_address),
                abi=self.get_contract_abis()["AIAgent"]
            )
            
            # Get the vault contract
            vault_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(self.yield_allocator_vault_address),
                abi=self.get_contract_abis()["YieldAllocatorVault"]
            )
            
            # Get asset token info
            asset_address = vault_contract.functions.asset().call()
            asset_contract = self.web3.eth.contract(
                address=self.web3.to_checksum_address(asset_address),
                abi=self.get_contract_abis()["ERC20"]
            )
            asset_decimals = asset_contract.functions.decimals().call()
            
            # Format amount for display
            formatted_amount = self.format_with_decimals(amount, asset_decimals)
            deposit_record.amount_token = formatted_amount
            deposit_record.token_decimals = asset_decimals
            deposit_record.save()
            
            # Build transaction
            nonce = self.web3.eth.get_transaction_count(self.executor_address)
            gas_price = self.web3.to_wei(self.gas_price_gwei, 'gwei')
            
            # Check if this is a Felix pool and use higher gas limit
            is_felix_pool = self.is_felix_pool(pool_address)
            gas_limit = 500000 if is_felix_pool else 300000
            
            if is_felix_pool:
                logger.info(f"⚠️ Target is Felix pool (ERC4626). Using higher gas limit: {gas_limit}")
            
            # Prepare the depositToPool transaction
            tx = ai_agent_contract.functions.depositToPool(
                self.web3.to_checksum_address(pool_address),
                amount
            ).build_transaction({
                'from': self.executor_address,
                'gas': gas_limit,  # Higher gas limit for Felix pools
                'gasPrice': gas_price,
                'nonce': nonce,
            })
            
            # Sign and send the transaction
            signed_tx = self.web3.eth.account.sign_transaction(tx, private_key=self.executor_private_key)
            # Check if we're using web3.py v5 or v6
            if hasattr(signed_tx, 'rawTransaction'):
                # web3.py v5
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
            else:
                # web3.py v6
                tx_hash = self.web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            
            # Wait for transaction receipt
            logger.info(f"Deposit transaction sent: {tx_hash.hex()}")
            logger.info("Waiting for transaction confirmation...")
            tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)
            
            # Update the record with transaction details
            deposit_record.transaction_hash = tx_hash.hex()
            deposit_record.block_number = tx_receipt.blockNumber
            deposit_record.gas_used = tx_receipt.gasUsed
            deposit_record.gas_price = gas_price
            
            if tx_receipt.status == 1:
                deposit_record.status = VaultRebalance.COMPLETED
                result["success"] = True
                result["transaction_hash"] = tx_hash.hex()
                result["block_number"] = tx_receipt.blockNumber
                result["gas_used"] = tx_receipt.gasUsed
                logger.info(f"Deposit successful: {tx_hash.hex()}")
            else:
                deposit_record.status = VaultRebalance.FAILED
                deposit_record.error_message = "Transaction failed"
                result["error"] = "Transaction failed"
                logger.error(f"Deposit failed: {tx_hash.hex()}")
            
            deposit_record.save()
            return result
            
        except Exception as e:
            logger.error(f"Error during deposit: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            
            deposit_record.status = VaultRebalance.FAILED
            deposit_record.error_message = str(e)
            deposit_record.save()
            
            result["error"] = str(e)
            return result

    def run_fulfillment_cycle(self):
        """
        Main operational loop for the vault worker.
        """
        best_pool_address = None  # Initialize to None
        start_time = time.time()
        
        logger.info("=" * 80)
        logger.info("Starting vault worker fulfillment cycle")
        logger.info("=" * 80)
    



        #============================================================
        # STEP 1: Process pending withdrawals
        #============================================================

        logger.info("=" * 60)
        logger.info("Processing pending withdrawals")
        logger.info("=" * 60)
        
        try:

            if not self.verify_executor_permissions():
                logger.error("Permission verification failed. Aborting.")
                return
            
            protocol_info = self.get_protocol_info()
            if not protocol_info:
                logger.error("Failed to get protocol info. Aborting.")
                return
            
            logger.info(f"Protocol Status Summary:")
            logger.info(f"  - Pending deposits: {protocol_info.get('deposit_queue_length', 0)}")
            logger.info(f"  - Pending withdrawals: {protocol_info.get('withdrawal_queue_length', 0)}")
            
            if protocol_info.get('withdrawal_queue_length', 0) > 0:
                logger.info("=" * 60)
                logger.info(f"Processing {protocol_info.get('withdrawal_queue_length')} pending withdrawals")
                logger.info("=" * 60)
                
                # Fulfill batch withdrawals
                withdrawal_start_time = time.time()
                withdrawal_result = self.fulfill_batch_withdrawals(self.max_batch_size)
                
            else:
                logger.info("No pending withdrawals to process.")



        #============================================================
        # STEP 2: Settle any failed rebalances
        #============================================================

            logger.info("=" * 60)
            logger.info("Checking for failed rebalances to settle")
            logger.info("=" * 60)
            # Try to settle any failed rebalances using idle assets
            self.settle_failed_rebalances(protocol_info)
            
            # Refresh protocol info after settling failed rebalances
            protocol_info = self.get_protocol_info()
            if not protocol_info:
                logger.error("Failed to refresh protocol info after settling failed rebalances. Continuing with caution.")

        #============================================================
        # STEP 3: Rebalance based on optimizer
        #============================================================

            logger.info("=" * 60)
            logger.info("Rebalancing based on optimizer")
            logger.info("=" * 60)
            current_best_pool_address = self.rebalance_based_on_optimizer()

        #============================================================
        # STEP 3: Process pending deposits
        #============================================================
        

            logger.info("=" * 60)
            logger.info("Processing pending deposits")
            logger.info("=" * 60)
            # Process deposits if there are any pending
            if protocol_info.get('deposit_queue_length', 0) > 0:
                logger.info("=" * 60)
                logger.info(f"Processing {protocol_info.get('deposit_queue_length')} pending deposits")
                logger.info("=" * 60)
                
                # Verify pool is whitelisted
                if not self.verify_pool_is_whitelisted(current_best_pool_address):
                    logger.error("Best pool is not whitelisted. Skipping deposits.")
                else:
                    # Get detailed deposit queue information
                    queue_info = self.get_deposit_queue_info()
                    
                    # Fulfill batch deposits
                    deposit_start_time = time.time()
                    deposit_result = self.fulfill_batch_deposits(current_best_pool_address, self.max_batch_size)
                    
                    # Save deposit results
                    self.save_deposit_run_results(queue_info, deposit_result, deposit_start_time)
                    
                    # Check if more batches need processing
                    if deposit_result.get('success', False) and deposit_result.get('remaining_count', 0) > 0:
                        logger.info(f"There are still {deposit_result.get('remaining_count')} deposits in the queue.")
                        logger.info("Consider running another fulfillment cycle.")
            else:
                logger.info("No pending deposits to process.")
            
            
            # Overall execution time
            total_execution_time = time.time() - start_time
            logger.info(f"Total execution time: {total_execution_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Error in fulfillment cycle: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")

def main():
    """Main entry point for the vault worker"""

    # Load environment variables for USDe asset
    underlying_token_symbol = 'USDe'
    vault_address = os.getenv('YIELD_ALLOCATOR_VAULT_ADDRESS')
    ai_agent_address = os.getenv('AI_AGENT_ADDRESS')
    whitelist_registry_address = os.getenv('WHITELIST_REGISTRY_ADDRESS')
    executor_private_key = os.getenv('EXECUTOR_PRIVATE_KEY')
    max_batch_size = int(os.getenv('MAX_BATCH_SIZE_USDe', '5'))
    
    try:
        # Initialize the vault worker for USDe asset
        worker = VaultWorker(underlying_token_symbol, vault_address, ai_agent_address, whitelist_registry_address, executor_private_key, max_batch_size)
        worker.run_fulfillment_cycle()
        
    except Exception as e:
        logger.error(f"Fatal error in vault worker: {str(e)}")
        sys.exit(1)


    # # Load environment variables for USDT0 asset
    # underlying_token_symbol = 'USDT0'
    # vault_address = os.getenv('YIELD_ALLOCATOR_VAULT_ADDRESS_USDT0')
    # ai_agent_address = os.getenv('AI_AGENT_ADDRESS_USDT0')
    # whitelist_registry_address = os.getenv('WHITELIST_REGISTRY_ADDRESS')
    # executor_private_key = os.getenv('EXECUTOR_PRIVATE_KEY')
    # max_batch_size = int(os.getenv('MAX_BATCH_SIZE_USDT0', '1'))
    
    # try:
    #     # Initialize the vault worker for USDT0 asset
    #     worker = VaultWorker(underlying_token_symbol, vault_address, ai_agent_address, whitelist_registry_address, executor_private_key, max_batch_size)
    #     worker.run_fulfillment_cycle()
        
    # except Exception as e:
    #     logger.error(f"Fatal error in vault worker: {str(e)}")
    #     sys.exit(1)     

if __name__ == "__main__":
    main()
