#!/usr/bin/env python3
"""
Test script for calculating HyperFi/HyperLend APY using hardcoded data
"""

import sys
import os
import math
from typing import Dict
from decimal import Decimal
import json
from dotenv import load_dotenv


# Add project root to path to allow imports from data module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

# Initialize Django settings before importing Django-dependent modules
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

# Import Django and setup
import django
django.setup()

# Import the calculate_hyperfi_hyperlend_future_apy function from optimizer.py
from data.utils.optimizer import (
    find_most_profitable_reallocation,
    parse_cron_struct, # Import the parser
    CronPoolData # Import the data class
)
from data.utils.strategy_summarizer import summarize_strategy_with_gpt



# -----------------------------
# Example usage & quick sanity test
# -----------------------------
if __name__ == "__main__":
    load_dotenv()
    # Use pool addresses as keys in cron_struct
    cron_struct = {
        "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b": {
            "protocol": "HyperLend",
            "current_apy": 18.13,
            "tvl": 48747628.25,
            "utilization": 0.82868132,
            "kink": 0.80,
            "slope1": 0.10400000,
            "slope2": 1.00000000,
            "reserve_factor": 0.20
        },
        "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b": {
            "protocol": "HyperFi",
            "current_apy": 9.18,
            "tvl": 19851473.49,
            "utilization": 0.80506552,
            "kink": 0.80,
            "slope1": 0.12,
            "slope2": 0.60,
            "reserve_factor": 0.20
        },
        "0xfc5126377f0efc0041c0969ef9ba903ce67d151e": {
            "protocol": "Felix",
            "current_apy": 26.31,
            "tvl": 69491695.92,
            "utilization": 75.0,
             "params":  {
                        "curve_steepness": "4.00000000",
                        "adjustment_speed": "50.00000000",
                        "target_utilization": "0.90000000",
                        "initial_rate_at_target": "0.04000000",
                        "min_rate_at_target": "0.00100000",
                        "max_rate_at_target": "2.00000000",
                        "utilization": 0.9447894740922841,
                        "reserve_factor": 0.1,
                        "total_supply": "69822044513676.00000000",
                        "total_borrows": "65967132716124.00000000",
                        "underlying_markets": [
                            {
                            "utilization": 0.8312,
                            "supply_apy_gross": 8.4631,
                            "total_supply_assets": 298176044415,
                            "total_borrow_assets": 247851669423,
                            "lltv": 0.77,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0xBe6727B535545C67d5cAa73dEa54865B92CF7907",
                            "oracle": "0x6Bfa2792efA52c2ffe61eD6d5d56fFA35cc4dD67",
                            "total_supply_shares": 293039637938077273,
                            "total_borrow_shares": 243147530975453404,
                            "borrow_rate": 3443525161
                            },
                            {
                            "utilization": 0.955,
                            "supply_apy_gross": 38.6953,
                            "total_supply_assets": 13353399583853,
                            "total_borrow_assets": 12752432185998,
                            "lltv": 0.625,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0x5555555555555555555555555555555555555555",
                            "oracle": "0x8f36DF5a5a9Fc1238d03401b96Aa411D6eBcA973",
                            "total_supply_shares": 12860709341549342610,
                            "total_borrow_shares": 12226481370527164465,
                            "borrow_rate": 12068193304
                            },
                            {
                            "utilization": 0.9586,
                            "supply_apy_gross": 39.8389,
                            "total_supply_assets": 11513159566517,
                            "total_borrow_assets": 11036198264076,
                            "lltv": 0.77,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0x9FDBdA0A5e284c32744D2f17Ee5c74B284993463",
                            "oracle": "0xcE5B111739B8b6A10fd7E9dD6a1C7DF9b653317f",
                            "total_supply_shares": 11184205099516735575,
                            "total_borrow_shares": 10687599217358062142,
                            "borrow_rate": 12324987756
                            },
                            {
                            "utilization": 0.955,
                            "supply_apy_gross": 5.3711,
                            "total_supply_assets": 5155218737149,
                            "total_borrow_assets": 4923198184657,
                            "lltv": 0.625,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0x94e8396e0869c9F2200760aF0621aFd240E1CF38",
                            "oracle": "0x10E8707F41fd04622EB42b6bcE857690313f5D78",
                            "total_supply_shares": 5137029084147366590,
                            "total_borrow_shares": 4903956862502929899,
                            "borrow_rate": 1930221579
                            },
                            {
                            "utilization": 0.7653,
                            "supply_apy_gross": 9.3071,
                            "total_supply_assets": 70642959973,
                            "total_borrow_assets": 54065260154,
                            "lltv": 0.77,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0x9FD7466f987Fd4C45a5BBDe22ED8aba5BC8D72d1",
                            "oracle": "0x58ff4dEEc83573510a7b8F26e7318173a473768b",
                            "total_supply_shares": 68978940772208629,
                            "total_borrow_shares": 52666144168858334,
                            "borrow_rate": 4096816978
                            },
                            {
                            "utilization": 0.7341,
                            "supply_apy_gross": 3.8293,
                            "total_supply_assets": 18128013745,
                            "total_borrow_assets": 13308524768,
                            "lltv": 0.77,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0x1359b05241cA5076c9F59605214f4F84114c0dE8",
                            "oracle": "0x485Ad642Ab73710aF785200b1eE90b3758B3d069",
                            "total_supply_shares": 17898221906757150,
                            "total_borrow_shares": 13118949713655950,
                            "borrow_rate": 1803453418
                            },
                            {
                            "utilization": 0.9347,
                            "supply_apy_gross": 22.5712,
                            "total_supply_assets": 34526850895653,
                            "total_borrow_assets": 32273525262610,
                            "lltv": 0.625,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0xfD739d4e423301CE9385c1fb8850539D657C296D",
                            "oracle": "0x5f5272eCaf3C9ef83697c7A0f560a8B8286108C7",
                            "total_supply_shares": 33883966174479239067,
                            "total_borrow_shares": 31617065834838303467,
                            "borrow_rate": 7671352632
                            },
                            {
                            "utilization": 0.955,
                            "supply_apy_gross": 10.5506,
                            "total_supply_assets": 4886468712371,
                            "total_borrow_assets": 4666553364438,
                            "lltv": 0.625,
                            "loan_token": "0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb",
                            "collateral_token": "0x311dB0FDe558689550c68355783c95eFDfe25329",
                            "oracle": "0x7111994019abaf6955FBcCd0AF0340Fd27c6B847",
                            "total_supply_shares": 4863278412076708850,
                            "total_borrow_shares": 4641911632641805621,
                            "borrow_rate": 3700533162
                            }
                        ]
                        }
            }
        }

    # Use pool addresses as keys in current_position
    current_pos = {
        "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b": 1002000, 
        "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b": 0,
        "0xfc5126377f0efc0041c0969ef9ba903ce67d151e": 5500
    }
    
    try:
        # Test the new protocol-specific APY calculation functions
        print("\n=== Testing Protocol-Specific APY Calculation Functions ===")
        
        # Parse the cron_struct to get pool data
        pools = parse_cron_struct(cron_struct)
        pool_data = {addr: pool for addr, pool in pools.items() if isinstance(pool, CronPoolData)}
        # Test direct recommendation function
        print("\n=== Testing Most Profitable Reallocation Function ===")
        recommendation = find_most_profitable_reallocation(pool_data, current_pos)


        print(recommendation)    
        print(f"Recommendation: {recommendation['action']}")
        if recommendation['action'] == 'reallocate':
            print(f"Move {recommendation['amount']:.2f} from {recommendation['from_protocol']} to {recommendation['to_protocol']}")
            print(f"Reason: {recommendation['reason']}")
            print(f"Source Pool APY: {recommendation['current_apy_from']:.3f}%")
            print(f"Destination Pool's New APY: {recommendation['new_apy_to']:.3f}%")
            print(f"Current Best Pool: {recommendation['current_best_pool']}")
            print(f"Current Best Pool Address: {recommendation['current_best_pool_address']}")
        else:
            print(f"Reason: {recommendation['reason']}")
            print(f"Current Best Pool: {recommendation['current_best_pool']}")
            print(f"Current Best Pool Address: {recommendation['current_best_pool_address']}")
            
                

        # print("\n--- AI Agent's Summary ---")
        # if not os.environ.get("OPENAI_API_KEY"):
        #     print("Skipping summary: OPENAI_API_KEY not set in .env file.")
        # else:
        #     summary = summarize_strategy_with_gpt(recommendation)
        #     print(summary)
        #     print("-------------------------")
    except Exception as e:
        print("Error:", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
