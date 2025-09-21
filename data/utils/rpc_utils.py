import logging
from decimal import Decimal
from django.conf import settings
from web3 import Web3

logger = logging.getLogger(__name__)

# ABI for ERC20 token balanceOf function
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    }
]

# ERC20 Transfer event ABI
ERC20_TRANSFER_EVENT_ABI = {
    "anonymous": False,
    "inputs": [
        {"indexed": True, "name": "from", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"},
        {"indexed": False, "name": "value", "type": "uint256"}
    ],
    "name": "Transfer",
    "type": "event"
}

def get_rpc_url():
    """Get the RPC URL from settings or use a default."""
    return settings.BLOCKCHAIN_RPC_URL

def get_web3_provider():
    """Get a Web3 provider instance."""
    rpc_url = get_rpc_url()
    return Web3(Web3.HTTPProvider(rpc_url))

def get_native_token_balance(address, wei=False):
    """
    Get the native token (ETH) balance for an address.
    
    Args:
        address (str): The wallet address to check
        
    Returns:
        Decimal: The balance in ETH (not wei)
    """
    try:
        w3 = get_web3_provider()
        
        # Ensure the address is checksum
        checksum_address = w3.to_checksum_address(address)
        
        # Get balance in wei
        balance_wei = w3.eth.get_balance(checksum_address)

        
        if wei:
            return balance_wei    
        # Convert to ETH
        balance_eth = w3.from_wei(balance_wei, 'ether')
        
        return Decimal(balance_eth)

    except Exception as e:
        logger.error(f"Error getting native token balance for {address}: {str(e)}")
        return Decimal('0')

def get_erc20_token_balance(wallet_address, token_address, wei=False):
    """
    Get the ERC20 token balance for a wallet address.
    
    Args:
        wallet_address (str): The wallet address to check
        token_address (str): The token contract address
        wei (bool, optional): Whether to return the balance in wei (raw units without decimal conversion)
        
    Returns:
        Decimal: The token balance (adjusted for decimals)
    """
    try:
        w3 = get_web3_provider()
        
        # Ensure addresses are checksum
        checksum_token_address = w3.to_checksum_address(token_address)
        checksum_wallet_address = w3.to_checksum_address(wallet_address)
        
        # Create contract instance
        contract = w3.eth.contract(address=checksum_token_address, abi=ERC20_ABI)
        

        # Get raw balance
        raw_balance = contract.functions.balanceOf(checksum_wallet_address).call()

        if wei:
            return raw_balance
        
        # Get token decimals
        decimals = get_token_decimals(token_address)

        
        # Convert to token units
        balance = Decimal(raw_balance) / Decimal(10 ** decimals)
        
        return Decimal(balance)
    except Exception as e:
        logger.error(f"Error getting ERC20 balance for token {token_address}, wallet {wallet_address}: {str(e)}")
        return Decimal('0')

def get_token_balance(wallet_address,token_address=None, wei=False):
    """
    Get token balance based on symbol. If HYPE, get native token balance,
    otherwise get ERC20 token balance.
    
    Args:
        wallet_address (str): The wallet address to check
        token_address (str, optional): The token contract address (required for ERC20 tokens)
        wei (bool, optional): Whether to return the balance in wei (raw units without decimal conversion)
        
    Returns:
        Decimal: The token balance in token units
    """
    try:
        if token_address.lower() == '0x5555555555555555555555555555555555555555':
            return get_native_token_balance(wallet_address, wei)
        elif token_address:
            return get_erc20_token_balance(wallet_address, token_address, wei)
        else:
            logger.error(f"Token address required for non-native token {token_address}")
            return Decimal('0')
    except Exception as e:
        logger.error(f"Error getting token balance: {str(e)}")
        return Decimal('0')



def get_token_decimals(token_address):
    try:
        w3 = Web3(Web3.HTTPProvider(settings.BLOCKCHAIN_RPC_URL))
        abi = [{
            "constant": True,
            "inputs": [],
            "name": "decimals",
            "outputs": [{"name": "", "type": "uint8"}],
            "type": "function"
        }]
        contract = w3.eth.contract(address=w3.to_checksum_address(token_address), abi=abi)
        decimals = contract.functions.decimals().call()
        return decimals
    except Exception as e:
        logger.warning(f"Could not get decimals for token {token_address}, using default 18: {str(e)}")
        return 18
    

async def fetch_all_token_balances(wallet_address, token_addresses):
    """
    Fetch balances for multiple tokens for a wallet address.
    
    Args:
        wallet_address: The wallet address to check balances for
        token_addresses: List of token addresses to check
        
    Returns:
        dict: Dictionary mapping token addresses to their balances
    """
    balances = {}
    
    # Process each token address
    for address in token_addresses:
        try:
            # Get balance using synchronous function (Web3.py doesn't support async)
            balance = get_token_balance(wallet_address, address, False)
            balances[address] = balance
        except Exception as e:
            logger.error(f"Error fetching balance for {address}: {str(e)}")
            balances[address] = 0
    
    return balances


def get_transaction_receipt(tx_hash):
    """
    Get the transaction receipt for a given transaction hash.
    
    Args:
        tx_hash (str): The transaction hash
        
    Returns:
        dict: The transaction receipt or None if not found
    """
    try:
        w3 = get_web3_provider()
        
        # Ensure hash has 0x prefix
        if not tx_hash.startswith('0x'):
            tx_hash = '0x' + tx_hash
            
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        return receipt
    except Exception as e:
        logger.error(f"Error getting transaction receipt for {tx_hash}: {str(e)}")
        return None

def get_token_transfer_events(tx_hash, token_address):
    """
    Get token transfer events from a transaction.
    
    Args:
        tx_hash (str): The transaction hash
        token_address (str): The token contract address
        
    Returns:
        list: List of transfer events
    """
    try:
        w3 = get_web3_provider()
        
        # Ensure addresses are checksum
        token_address = w3.to_checksum_address(token_address)
        
        # Get transaction receipt
        receipt = get_transaction_receipt(tx_hash)
        if not receipt:
            return []
        
        # Create contract instance
        contract = w3.eth.contract(address=token_address, abi=[ERC20_TRANSFER_EVENT_ABI])
        
        # Get Transfer events
        transfer_events = []
        for log in receipt.logs:
            if log.address.lower() == token_address.lower():
                try:
                    # Try to decode the log as a Transfer event
                    decoded_log = contract.events.Transfer().process_log(log)
                    transfer_events.append(decoded_log)
                except Exception as e:
                    logger.debug(f"Log is not a Transfer event: {str(e)}")
        
        return transfer_events
    except Exception as e:
        logger.error(f"Error getting token transfer events for {tx_hash}: {str(e)}")
        return []

def verify_token_transfer(transfer_events, wallet_address):
    """
    Verify that a token transfer to the specified wallet address exists in the events.
    
    Args:
        transfer_events (list): List of transfer events
        wallet_address (str): The wallet address to verify transfer to
        
    Returns:
        dict: Transfer data if verified, None otherwise
    """
    try:
        if not transfer_events:
            return None
            
        w3 = get_web3_provider()
        wallet_address = wallet_address.lower()
        
        # Look for transfers to the wallet address
        for event in transfer_events:
            to_address = event['args']['to'].lower()
            if to_address == wallet_address:
                return {
                    'from': event['args']['from'],
                    'to': event['args']['to'],
                    'value': event['args']['value']
                }
        
        return None
        
    except Exception as e:
        logger.error(f"Error verifying token transfer: {str(e)}")
        return None

