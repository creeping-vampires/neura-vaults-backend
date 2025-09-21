"""
Felix Future APY Calculator

This module provides functions to calculate future APY for Felix protocol pools.
It handles the specific Felix interest rate model and sub-market calculations.
"""
import sys
import os
import json
import math
from typing import Dict, List, Optional
from decimal import Decimal

from data.utils.rpc_utils import get_web3_provider


def call_borrow_rate_view(felix_contract, market_params: Dict, market_data: Dict) -> Optional[int]:
    """
    Call borrowRateView function on Felix contract
    
    Args:
        felix_contract: Web3 contract instance for Felix
        market_params: Dictionary containing market parameters
        market_data: Dictionary containing market data
        
    Returns:
        Borrow rate as integer or None if error occurs
    """
    try:
        # Convert lltv from float to uint256 if needed
        if 'lltv' in market_params and isinstance(market_params['lltv'], float):
            # Convert from decimal (e.g., 0.77) to wei format (e.g., 770000000000000000)
            market_params['lltv'] = int(market_params['lltv'] * 10**18)
        
        # Create structured tuples for contract call
        market_params_tuple = (
            market_params['loanToken'],
            market_params['collateralToken'],
            market_params['oracle'],
            market_params['irm'],
            market_params['lltv']
        )
        
        market_data_tuple = (
            int(market_data['totalSupplyAssets']),
            int(market_data['totalSupplyShares']),
            int(market_data['totalBorrowAssets']),
            int(market_data['totalBorrowShares']),
            int(market_data['lastUpdate']),
            int(market_data['fee'])
        )
        
        # Call the function with tuple parameters
        return felix_contract.functions.borrowRateView(market_params_tuple, market_data_tuple).call()
            
    except Exception as e:
        # Show error without fallback calculation
        print(f"Error calling borrowRateView: {e}")
        
        # If market has a borrow_rate field, use that
        if 'borrow_rate' in market_params:
            return market_params['borrow_rate']
            
        # Otherwise return None to indicate failure
        return None

#calculate_supply_apy
def calculate_supply_apy_with_borrow_rate(borrow_rate: float, market_data: Dict, reserve_factor: float) -> float:
    """
    Calculate supply APY based on borrow rate and market data
    
    Args:
        borrow_rate: Borrow rate from borrowRateView (scaled by 1e9)
        market_data: Dictionary containing market data
        reserve_factor: Reserve factor as a decimal (0.1 = 10%)
        
    Returns:
        Supply APY as a percentage (e.g., 5.2 for 5.2%)
    """
    # Constants
    seconds_per_year = 365 * 24 * 60 * 60  # 31536000
    
    rate_per_second = borrow_rate / 1e18
    
    if market_data['totalSupplyAssets'] == 0:
        return 0.0
        
    util = market_data['totalBorrowAssets'] / market_data['totalSupplyAssets']
    supply_rate = rate_per_second * util * (1 - reserve_factor)
    
    supply_apy = (1 + supply_rate) ** seconds_per_year - 1

    # print(f"calculated supply apy {supply_apy*100}")
    return supply_apy * 100


def calculate_sub_market_weights(underlying_markets: List[Dict]) -> List[Dict]:
    """
    Calculate supply weights for each sub-market
    
    Args:
        underlying_markets: List of dictionaries containing sub-market data
        
    Returns:
        List of dictionaries with original data plus calculated weights
    """
    # Calculate total supply across all markets
    total_supply = sum(market['total_supply_assets'] for market in underlying_markets)
    
    if total_supply == 0:
        # If total supply is zero, assign equal weights
        equal_weight = 1.0 / len(underlying_markets) if underlying_markets else 0
        return [
            {**market, 'weight': equal_weight}
            for market in underlying_markets
        ]
    
    # Calculate weight for each market based on its proportion of total supply
    weighted_markets = []
    for market in underlying_markets:
        weight = market['total_supply_assets'] / total_supply
        weighted_markets.append({**market, 'weight': weight})
    
    return weighted_markets


def calculate_submarket_apys(pool_params: Dict, felix_contract=None) -> Dict:
    """
    Calculate future APY for a Felix pool based on its parameters and underlying markets
    
    Args:
        pool_params: Dictionary containing Felix pool parameters and underlying markets
        felix_contract: Optional Web3 contract instance for Felix to calculate borrow rates
        
    Returns:
        Dictionary with calculated APY and related data
    """
    # Extract parameters
    reserve_factor = pool_params.get('reserve_factor', 0.1)
    underlying_markets = pool_params.get('underlying_markets', [])
    
    # Calculate weights for each sub-market
    weighted_markets = calculate_sub_market_weights(underlying_markets)
    
    # Calculate APY for each sub-market
    market_apys = []
    for market in weighted_markets:
        # Create market_data dict for supply_apy calculation
        market_data = {
            'totalSupplyAssets': market['total_supply_assets'],
            'totalBorrowAssets': market['total_borrow_assets']
        }
        
        # Initialize calculated_borrow_rate with a default value or from market data if available
        calculated_borrow_rate = market.get('borrow_rate', 0)
        
        # Only attempt contract call if felix_contract is provided
        if felix_contract and all(key in market for key in ['loan_token', 'collateral_token', 'oracle', 'lltv']):
            # Prepare parameters for contract call
            market_params = {
                'loanToken': market['loan_token'],
                'collateralToken': market['collateral_token'],
                'oracle': market['oracle'],
                'irm': market.get('irm', '0x0000000000000000000000000000000000000000'),  # Default to zero address if not provided
                'lltv': market['lltv']
            }
            
            # Prepare market data for contract call
            contract_market_data = {
                'totalSupplyAssets': market['total_supply_assets'],
                'totalSupplyShares': market.get('total_supply_shares', 0),
                'totalBorrowAssets': market['total_borrow_assets'],
                'totalBorrowShares': market.get('total_borrow_shares', 0),
                'lastUpdate': market.get('lastUpdate', 0),
                'fee': market.get('fee', 0)
            }
            
            # Call contract to get borrow rate - no fallback calculation
            contract_borrow_rate = call_borrow_rate_view(felix_contract, market_params, contract_market_data)
            
            # print('calculated_borrow_rate', contract_borrow_rate)
            if contract_borrow_rate is not None:
                calculated_borrow_rate = contract_borrow_rate
        
        # Calculate APY for this market using the borrow rate
        apy = calculate_supply_apy_with_borrow_rate(calculated_borrow_rate, market_data, reserve_factor)
        
        # print('calculated apy with borrow rate', apy)
        market_apys.append({
            'market': f"{market['loan_token']}:{market['collateral_token']}",
            'weight': market['weight'],
            'apy': apy,
            'weighted_apy': apy * market['weight'],
            'borrow_rate': calculated_borrow_rate
        })
    
    # Calculate pool APY as weighted average of sub-market APYs
    pool_apy = sum(market['weighted_apy'] for market in market_apys)
    
    return {
        'pool_apy': pool_apy,
        'reserve_factor': reserve_factor,
        'market_apys': market_apys,
        'total_supply': pool_params.get('total_supply', 0),
        'total_borrows': pool_params.get('total_borrows', 0),
        'utilization': pool_params.get('utilization', 0)
    }

def update_pool_params_with_extra_supply(
    pool_params: Dict, 
    extra_supply_amount: float,
    target_market_index: int = None
) -> Dict:
    """
    Update Felix pool parameters with additional supply amount following specific instructions
    
    Args:
        pool_params: Dictionary containing Felix pool parameters and underlying markets
        extra_supply_amount: Additional supply amount to add to the pool
        target_market_index: Optional index of the specific market to add supply to (if None, distribute proportionally)
        
    Returns:
        Dictionary with updated pool parameters
    """
    # Create a deep copy of the pool params to avoid modifying the original
    import copy
    from decimal import Decimal, getcontext
    
    # Set precision high enough for large numbers
    getcontext().prec = 36
    
    modified_params = copy.deepcopy(pool_params)
    
    # Extract current values using Decimal for precision
    original_total_supply = Decimal(modified_params.get('total_supply', '0'))
    total_borrows = Decimal(modified_params.get('total_borrows', '0'))
    extra_supply_decimal = Decimal(str(extra_supply_amount))
    
    # 1. Increase total supply
    new_total_supply = original_total_supply + extra_supply_decimal
    
    # 2. Calculate new utilization with increased total supply
    new_utilization = float(total_borrows / new_total_supply) if new_total_supply > 0 else 0.99
    
    # Update the parameters with new values
    modified_params['total_supply'] = str(new_total_supply)
    modified_params['utilization'] = new_utilization
    
    underlying_markets = modified_params.get('underlying_markets', [])
    if not underlying_markets:
        return modified_params
    
    # If target market is specified, only update that market
    if target_market_index is not None and 0 <= target_market_index < len(underlying_markets):
        markets_to_update = [target_market_index]
        # All extra supply goes to the target market
        market_weights = {target_market_index: Decimal('1.0')}
    else:
        # Distribute proportionally across all markets
        markets_to_update = range(len(underlying_markets))
        # Calculate total supply across all markets for distribution weighting
        total_markets_supply = sum(Decimal(str(market['total_supply_assets'])) for market in underlying_markets)
        market_weights = {}
        for i, market in enumerate(underlying_markets):
            total_supply_assets = Decimal(str(market['total_supply_assets']))
            market_weights[i] = total_supply_assets / total_markets_supply if total_markets_supply > 0 else Decimal('1.0') / Decimal(str(len(underlying_markets)))
    
    # Update each selected market
    for i in markets_to_update:
        market = underlying_markets[i]
        
        # 3. Find current share price using Decimal for precision
        total_supply_assets = Decimal(str(market['total_supply_assets']))
        
        # Handle scientific notation or any other format in total_supply_shares
        if isinstance(market['total_supply_shares'], str):
            total_supply_shares = Decimal(market['total_supply_shares'])
        else:
            # If it's already a number (float/int) or scientific notation
            total_supply_shares = Decimal(str(market['total_supply_shares']))
        
        share_price = total_supply_assets / total_supply_shares if total_supply_shares > 0 else Decimal('1.0')
        
        # 4. Increase total supply assets for this market
        extra_supply_for_market = extra_supply_decimal * market_weights[i]
        new_supply_assets = total_supply_assets + extra_supply_for_market
        
        # 5. Calculate additional shares with increased supply
        additional_shares = extra_supply_for_market / share_price if share_price > 0 else extra_supply_for_market
        new_supply_shares = total_supply_shares + additional_shares
        
        # 6. Update new utilization
        total_borrow_assets = Decimal(str(market['total_borrow_assets']))
        new_market_utilization = float(total_borrow_assets / new_supply_assets) if new_supply_assets > 0 else 0.99
        
        # Update the market data - store as regular numbers, not Decimal objects
        modified_params['underlying_markets'][i]['total_supply_assets'] = float(new_supply_assets)
        modified_params['underlying_markets'][i]['total_supply_shares'] = int(new_supply_shares) if new_supply_shares > 10**15 else float(new_supply_shares)
        modified_params['underlying_markets'][i]['utilization'] = new_market_utilization
    
    return modified_params



def prepare_submarket_apy_results(pool_param: dict, felix_pool_address: str) -> float:
    """Calculate future apy for a given pool param

    Args:
        pool_param (dict): Pool parameters
        felix_pool_address (str): Felix pool address

    Returns:
        float: Future apy
    """

    w3 = get_web3_provider()
    
    # Ensure addresses are checksum
    checksum_token_address = w3.to_checksum_address(felix_pool_address)
        
    # Create contract instance
    # Use absolute path to the Felix ABI file
    abi_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'workers/cron_service/abi/Felix.json')
    try:
        with open(abi_path, 'r') as f:
            FELIX_ABI = json.load(f)
        felix_contract = w3.eth.contract(address=checksum_token_address, abi=FELIX_ABI)
    except FileNotFoundError:
        print(f"Error: Could not find Felix ABI at {abi_path}")
        print("Falling back to simplified calculation without contract")
        # return calculate_felix_future_apy(pool_param, None)
        raise Exception("Felix ABI not found")

    apy = calculate_submarket_apys(pool_param, felix_contract)
    return apy



# Calculate complete supply APY with weights
def calculate_complete_supply_apy_with_weights(borrow_rates: list, market_datas: list) -> float:
    """Calculate vault supply APY based on weighted average of market APYs

    Args:
        borrow_rates (list): List of borrow rates for each market
        market_datas (list): List of market data dictionaries

    Returns:
        float: Weighted average supply APY
    """
    total_supply = sum(market_data['totalSupplyAssets'] for market_data in market_datas)
    if total_supply == 0:
        return 0.0
    weighted = 0.0
    for br, market_data in zip(borrow_rates, market_datas):
        weight = market_data['totalSupplyAssets'] / total_supply
        weighted += weight * calculate_supply_apy_with_borrow_rate(br, market_data, 0.1)  # Assuming 10% reserve factor
    return weighted


# Final Felix apy calculation function to call
# This function will be used to calculate final apy for felix pool
def fetch_felix_final_calculated_apy(pool_address: str, params: dict) -> float:
    # felix_pool_address = '0xD4a426F010986dCad727e8dd6eed44cA4A9b7483'
    apy_result = prepare_submarket_apy_results(params, pool_address)
    
    # Extract market data and borrow rates for calculate_vault_supply_apy
    market_datas = []
    borrow_rates = []
    
    if 'market_apys' in apy_result:
        for market in apy_result['market_apys']:
            # Extract market identifier
            market_id = market.get('market', '')
            if ':' in market_id:
                loan_token, collateral_token = market_id.split(':')
                
                # Find the corresponding market in POOL_PARAMS
                for underlying_market in params['underlying_markets']:
                    if (underlying_market['loan_token'] == loan_token and 
                        underlying_market['collateral_token'] == collateral_token):
                        
                        # Create market data dict
                        market_data = {
                            'totalSupplyAssets': underlying_market['total_supply_assets'],
                            'totalBorrowAssets': underlying_market['total_borrow_assets']
                        }
                        market_datas.append(market_data)
                        
                        # Get borrow rate
                        borrow_rates.append(underlying_market['borrow_rate'])
    
    # Calculate vault supply APY using the new function
    vault_supply_apy = calculate_complete_supply_apy_with_weights(borrow_rates, market_datas) if market_datas else 0
    return vault_supply_apy


