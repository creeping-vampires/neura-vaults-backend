#!/usr/bin/env python3
"""
Test script for calculating HyperFi/HyperLend APY using hardcoded data
"""

import sys
import os
import math
from typing import Dict
from decimal import Decimal

# Add project root to path to allow imports from data module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Initialize Django settings before importing Django-dependent modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

# Import Django and setup
import django
django.setup()

# Import the calculate_hyperfi_hyperlend_future_apy function from optimizer.py
from data.utils.optimizer import calculate_hyperfi_hyperlend_future_apy


# Hardcoded test data for HyperFi
HYPERFI_POOL_DATA = {
  "kink": 0.80,
  "base_rate": 0.0,
  "slope1": 0.104,
  "slope2": 1.0,
  "utilization": 0.76250241,
  "reserve_factor": 0.2,
  "total_supply": 53114143285978,
  "total_borrows": 40499662324941
}
# Hardcoded test data for HyperLend
HYPERLEND_POOL_DATA = {
    "kink": 0.85,
    "slope1": 0.07,  # 7% rate at kink
    "slope2": 0.6,   # 60% rate slope after kink
    "reserve_factor": 0.15,  # 15% reserve factor
    "total_supply": 5000000,
    "total_borrows": 4145500,  # 82.91% utilization
}


def calculate_apy_with_different_utilizations(pool_data: Dict, name: str):
    """
    Calculate and print APY at different utilization levels
    
    Args:
        pool_data: Dictionary containing pool parameters
        name: Name of the protocol for display purposes
    """
    print(f"\n{name} APY at different utilization levels:")
    print("=" * 50)
    print(f"{'Utilization':<15} {'Borrow APR':<15} {'Supply APR':<15} {'Supply APY':<15}")
    print("-" * 50)
    
    for util in [0.5, 0.7, 0.8, 0.85, 0.9, 0.95]:
        # Clamp utilization
        u = max(0.01, min(0.99, util))
        
        # Extract parameters from pool data
        kink = pool_data.get("kink", 0.8)
        slope1 = pool_data.get("slope1", 0.1)
        slope2 = pool_data.get("slope2", 0.5)
        reserve_factor = pool_data.get("reserve_factor", 0.2)
        
        # Calculate borrow APR using kinked interest model
        if u <= kink:
            borrow_apr = (u / kink) * slope1
        else:
            borrow_apr = slope1 + ((u - kink) / (1 - kink)) * slope2

        # Calculate supply APR
        supply_apr = borrow_apr * u * (1 - reserve_factor)
        
        # Convert APR to APY
        supply_apy = math.exp(supply_apr) - 1
        
        print(f"{util*100:<15.2f}% {borrow_apr*100:<15.2f}% {supply_apr*100:<15.2f}% {supply_apy*100:<15.2f}%")


def calculate_apy_with_extra_supply(pool_data: Dict, extra_supply: float, name: str):
    """
    Calculate APY after adding extra supply to the pool
    
    Args:
        pool_data: Dictionary containing pool parameters
        extra_supply: Amount of extra supply to add
        name: Name of the protocol for display purposes
    """
    # Create a copy of the pool data
    updated_pool = pool_data.copy()
    
    # Calculate original values
    original_total_supply = pool_data["total_supply"]
    total_borrows = pool_data["total_borrows"]
    original_utilization = total_borrows / original_total_supply

    print('original_utilization ', original_utilization)
    
    # Calculate new values
    new_total_supply = original_total_supply + extra_supply
    new_utilization = total_borrows / new_total_supply

    print('new_utilization ', new_utilization)

    print('utilization diff ', original_utilization - new_utilization)
    
    # Calculate APYs
    original_apy = calculate_hyperfi_hyperlend_future_apy(original_utilization, pool_data)
    new_apy = calculate_hyperfi_hyperlend_future_apy(new_utilization, pool_data)
    
    print(f"\n{name} APY with extra supply:")
    print("=" * 60)
    print(f"Original Supply: {original_total_supply:,.2f}")
    print(f"Extra Supply: {extra_supply:,.2f}")
    print(f"New Supply: {new_total_supply:,.2f}")
    print(f"Original Utilization: {original_utilization*100:.2f}%")
    print(f"New Utilization: {new_utilization*100:.2f}%")
    print(f"Original APY: {original_apy*100:.4f}%")
    print(f"New APY: {new_apy*100:.4f}%")
    print(f"APY Change: {(new_apy - original_apy)*100:.4f}%")


def main():
    """Main function to run the test calculations"""
    print("HyperFi/HyperLend APY Calculator")
    print("=" * 50)
    
    # # Calculate current APY for HyperFi
    # hyperfi_utilization = HYPERFI_POOL_DATA["total_borrows"] / HYPERFI_POOL_DATA["total_supply"]
    # hyperfi_apy = calculate_hyperfi_hyperlend_future_apy(hyperfi_utilization, HYPERFI_POOL_DATA)
    # print(f"HyperFi APY at {hyperfi_utilization*100:.2f}% utilization: {hyperfi_apy*100:.4f}%")
    
    # # Calculate current APY for HyperLend
    # hyperlend_utilization = HYPERLEND_POOL_DATA["total_borrows"] / HYPERLEND_POOL_DATA["total_supply"]
    # hyperlend_apy = calculate_hyperfi_hyperlend_future_apy(hyperlend_utilization, HYPERLEND_POOL_DATA)
    # print(f"HyperLend APY at {hyperlend_utilization*100:.2f}% utilization: {hyperlend_apy*100:.4f}%")
    
    # # Calculate APY at different utilization levels
    # calculate_apy_with_different_utilizations(HYPERFI_POOL_DATA, "HyperFi")
    # calculate_apy_with_different_utilizations(HYPERLEND_POOL_DATA, "HyperLend")
    
    # Calculate APY with extra supply

    # increase 1% of total supply
    extra_supply = float(HYPERFI_POOL_DATA["total_supply"]) * 0.11
    calculate_apy_with_extra_supply(HYPERFI_POOL_DATA, extra_supply, "HyperFi")
    # calculate_apy_with_extra_supply(HYPERLEND_POOL_DATA, 500000, "HyperLend")


if __name__ == "__main__":
    main()
