"""
Real-time Pool Optimizer for Cron Job Data - FIXED LOGIC
Processes live data and calculates optimal fund movements between HyperLend and HyperFi
"""
import os


import re
import sys
import io
import asyncio
import httpx
from pathlib import Path

# Set up stdout to handle Unicode properly
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add the project root to Python path so we can import data modules
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Configure Django BEFORE importing any Django models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

import django
django.setup()

from typing import Dict, Tuple, Any
from decimal import Decimal
import logging
import json
import os
from web3 import Web3
from web3.contract import Contract
from telebot import broadcast_messages, get_all_user_ids_from_api
import math
import time

from dataclasses import dataclass
from data.data_access_layer import OptimizationResultDAO
from data.data_access_layer import YieldReportDAL
from data.workers.cron_service.yield_monitor_worker import YieldMonitorWorker

yield_monitor = YieldMonitorWorker()
API_BASE_URL=os.getenv("API_BASE_URL")
logger = logging.getLogger(__name__)

# ============================================================================
# PROTOCOL CONFIGURATIONS (from smart contracts)
# ============================================================================

WAD = 10**27


PROTOCOL_PARAMS = {
    "HyperLend": {
        "kink": 0.80,
        "base_rate": 0.0,
        "slope1": 0.052,  # 5.2%
        "slope2": 1.00,   # 100%
        "reserve_factor": 0.10
    },
    "HyperFi": {
        "kink": 0.80,
        "base_rate": 0.0,
        "slope1": 0.040,  # 4.0%
        "slope2": 0.75,   # 75%
        "reserve_factor": 0.10
    }
}


yield_threshold = float(os.getenv("YIELD_THRESHOLD", "0.5"))

# ============================================================================
# DATA PARSING
# ============================================================================

@dataclass
class CronPoolData:
    """Parsed data from cron job"""
    protocol: str
    current_apr: float  # Current supply APR from cron (for validation)
    tvl: float  # Total value locked (supplied)
    utilization: float  # Utilization rate as decimal (0.8291 for 82.91%)
    
    @property
    def total_borrow(self) -> float:
        """Calculate total borrows from TVL and utilization"""
        return self.tvl * self.utilization
    
    @property
    def available_liquidity(self) -> float:
        """Calculate available liquidity"""
        return self.tvl - self.total_borrow

def check_apr_difference_move(cron_data: str, current_hyperfi_deposit: float = 300000) -> Dict:
    """
    If APR difference is 1.5% or more, move entire wallet to better protocol.
    """
    pools = parse_cron_data(cron_data)
    
    if not pools or len(pools) < 2:
        return {"error": "Need both protocols in cron data"}
        
    # Calculate current APRs using the same model as the optimizer
    hyperfi_util = pools["HyperFi"].utilization
    hyperlend_util = pools["HyperLend"].utilization
    
    hyperfi_apr = calculate_supply_apr(hyperfi_util, "HyperFi")
    hyperlend_apr = calculate_supply_apr(hyperlend_util, "HyperLend")
    
    # Calculate absolute APR difference in percentage points
    apr_diff_pp = abs(hyperfi_apr - hyperlend_apr) * 100
    
    # Current position (assuming all money in HyperFi)
    current_balance = current_hyperfi_deposit
    
    # If difference >= 1.5%, move everything to better protocol
    if apr_diff_pp >= 1.5:
        if hyperfi_apr > hyperlend_apr:
            # Stay in HyperFi - it's better
            return {
                "move_recommended": False,
                "reason": f"HyperFi APR ({hyperfi_apr*100:.2f}%) is {apr_diff_pp:.2f}% higher than HyperLend",
                "current_protocol": "HyperFi",
                "stay_put": True,
                "apr_difference": apr_diff_pp
            }
        else:
            # Move everything to HyperLend
            annual_gain = current_balance * (hyperlend_apr - hyperfi_apr)
            return {
                "move_recommended": True,
                "amount": current_balance,
                "from": "HyperFi", 
                "to": "HyperLend",
                "apr_difference": apr_diff_pp,
                "annual_gain": annual_gain
            }
    else:
        # APR difference is too small - use normal optimization
        return {
            "move_recommended": False,
            "reason": f"APR difference ({apr_diff_pp:.2f}%) is less than 1.5% threshold",
            "use_optimization": True
        }
def parse_cron_data(cron_string: str) -> Dict[str, CronPoolData]:
    """
    Parse cron job data strings into structured data
    
    Example input:
    "hyplend usde - 13.79% apr. USDe supplied/tvl- $2,950,186.42, utilisation rate= 82.91%"
    """
    pools = {}
    
    # Parse HyperLend data
    if "hyplend" in cron_string.lower() or "hyperlend" in cron_string.lower():
        # Extract APR (for validation/comparison)
        apr_match = re.search(r'hyp[er]*lend.*?(\d+\.?\d*)%\s*apr', cron_string.lower())
        apr = float(apr_match.group(1)) / 100 if apr_match else 0
        
        # Extract TVL
        tvl_match = re.search(r'hyp[er]*lend.*?\$([0-9,]+\.?\d*)', cron_string.lower())
        tvl = float(tvl_match.group(1).replace(',', '')) if tvl_match else 0
        
        # Extract utilization
        util_match = re.search(r'hyp[er]*lend.*?utilisation rate\s*=\s*(\d+\.?\d*)%', cron_string.lower())
        utilization = float(util_match.group(1)) / 100 if util_match else 0
        
        pools["HyperLend"] = CronPoolData(
            protocol="HyperLend",
            current_apr=apr,
            tvl=tvl,
            utilization=utilization
        )
    
    # Parse HyperFi data
    if "hypurfi" in cron_string.lower() or "hyperfi" in cron_string.lower():
        # Extract APR
        apr_match = re.search(r'hyp[ue]*rfi.*?(\d+\.?\d*)%\s*apr', cron_string.lower())
        apr = float(apr_match.group(1)) / 100 if apr_match else 0
        
        # Extract TVL
        tvl_match = re.search(r'hyp[ue]*rfi.*?\$([0-9,]+\.?\d*)', cron_string.lower())
        tvl = float(tvl_match.group(1).replace(',', '')) if tvl_match else 0
        
        # Extract utilization
        util_match = re.search(r'hyp[ue]*rfi.*?utilisation rate\s*=\s*(\d+\.?\d*)%', cron_string.lower())
        utilization = float(util_match.group(1)) / 100 if util_match else 0
        
        pools["HyperFi"] = CronPoolData(
            protocol="HyperFi",
            current_apr=apr,
            tvl=tvl,
            utilization=utilization
        )
    
    return pools

# ============================================================================
# INTEREST RATE CALCULATIONS
# ============================================================================

def decimal_default_converter(obj):
    """Converts Decimal objects to formatted strings for clean JSON serialization."""
    if isinstance(obj, Decimal):
        # Format to a plain string with 8 decimal places, avoiding scientific notation
        return f"{obj:.8f}"
    raise TypeError("Object of type %s is not JSON serializable" % type(obj).__name__)

def calculate_borrow_apr(utilization: float, protocol: str) -> float:
    """
    Calculate borrow APR using the kinked model
    """
    params = PROTOCOL_PARAMS[protocol]
    
    if utilization <= params["kink"]:
        # Below kink: base + slope1 * (U / kink)
        if params["kink"] > 0:
            borrow_apr = params["base_rate"] + params["slope1"] * (utilization / params["kink"])
        else:
            borrow_apr = params["base_rate"]
    else:
        # Above kink: base + slope1 + slope2 * ((U - kink) / (1 - kink))
        borrow_apr = (params["base_rate"] + params["slope1"] + 
                     params["slope2"] * ((utilization - params["kink"]) / (1 - params["kink"])))
    
    return borrow_apr

def calculate_supply_apr(utilization: float, protocol: str) -> float:
    """
    Calculate supply APR
    Supply APR = Borrow APR * Utilization * (1 - Reserve Factor)
    """
    borrow_apr = calculate_borrow_apr(utilization, protocol)
    params = PROTOCOL_PARAMS[protocol]
    supply_apr = borrow_apr * utilization * (1 - params["reserve_factor"])
    
    return supply_apr

# ============================================================================
# OPTIMIZER
# ============================================================================

class RealtimeOptimizer:
    """Optimizer for real-time cron job data"""
    
    def __init__(self, pools: Dict[str, CronPoolData], current_position: Dict[str, float],
                 min_gain_bps: float = 5, gas_cost_usd: float = 10, verbose: bool = True):
        """
        Initialize optimizer with parsed cron data
        
        Args:
            pools: Dictionary of parsed pool data
            current_position: Dict with protocol names as keys and balances as values
            min_gain_bps: Minimum basis points gain to consider profitable
            gas_cost_usd: Estimated gas cost in USD
            verbose: Whether to print detailed logs
        """
        self.pools = pools
        self.position = current_position
        self.min_gain_bps = min_gain_bps
        self.gas_cost_usd = gas_cost_usd
        self.verbose = verbose
        
        # Validate parsed APRs against calculated ones
        self._validate_aprs()
    
    def _validate_aprs(self):
        """Validate that parsed APRs match our model calculations"""
        if self.verbose:
            print("\n📊 APR Validation:")
            print("-" * 60)
        
        for name, pool in self.pools.items():
            calculated_apr = calculate_supply_apr(pool.utilization, name)
            if self.verbose:
                print(f"{name}: Reported={pool.current_apr*100:.2f}%, Calculated={calculated_apr*100:.2f}%")
            if abs(calculated_apr - pool.current_apr) > 0.01:  # More than 1% difference
                print(f"  ⚠️  Warning: {name} APR mismatch - using calculated value")
    
    def analyze_move(self, amount: float, from_protocol: str, to_protocol: str) -> Dict:
        """
        Analyze the impact of moving funds
        
        FIXED LOGIC:
        - Withdrawing from a pool INCREASES its utilization (less supply, same borrows)
        - Depositing to a pool DECREASES its utilization (more supply, same borrows)
        """
        if amount > self.position.get(from_protocol, 0):
            return {"error": f"Insufficient balance in {from_protocol}"}
        
        if amount <= 0:
            return {"error": "Amount must be positive"}
        
        from_pool = self.pools[from_protocol]
        to_pool = self.pools[to_protocol]
        
        # Calculate new TVLs after the move
        new_tvl_from = from_pool.tvl - amount  # Withdrawing reduces TVL
        new_tvl_to = to_pool.tvl + amount      # Depositing increases TVL
        
        # Calculate new utilizations
        # Utilization = Borrows / Supply (TVL)
        new_util_from = from_pool.total_borrow / new_tvl_from if new_tvl_from > 0 else 1.0
        new_util_to = to_pool.total_borrow / new_tvl_to if new_tvl_to > 0 else 0
        
        # Cap utilization at 100%
        new_util_from = min(new_util_from, 1.0)
        new_util_to = min(new_util_to, 1.0)
        
        # Calculate new APRs based on new utilizations
        new_apr_from = calculate_supply_apr(new_util_from, from_protocol)
        new_apr_to = calculate_supply_apr(new_util_to, to_protocol)
        
        # Calculate current weighted APR
        total_balance = sum(self.position.values())
        current_weighted_apr = 0
        for protocol, balance in self.position.items():
            if balance > 0 and protocol in self.pools:
                current_weighted_apr += calculate_supply_apr(self.pools[protocol].utilization, protocol) * balance
        current_weighted_apr = current_weighted_apr / total_balance if total_balance > 0 else 0
        
        # Calculate new weighted APR after move
        new_balance_from = self.position.get(from_protocol, 0) - amount
        new_balance_to = self.position.get(to_protocol, 0) + amount
        
        new_weighted_apr = (new_balance_from * new_apr_from + new_balance_to * new_apr_to) / total_balance if total_balance > 0 else 0
        
        # Calculate gains
        annual_gain_usd = (new_weighted_apr - current_weighted_apr) * total_balance
        gain_bps = (new_weighted_apr - current_weighted_apr) * 10000
        
        # Check kink crossings
        kink = PROTOCOL_PARAMS[from_protocol]["kink"]
        from_crosses_kink = (
            (from_pool.utilization < kink <= new_util_from) or
            (new_util_from < kink <= from_pool.utilization)
        )
        
        to_crosses_kink = (
            (to_pool.utilization < kink <= new_util_to) or
            (new_util_to < kink <= to_pool.utilization)
        )
        
        return {
            "amount": amount,
            "from": from_protocol,
            "to": to_protocol,
            "current_util": {
                from_protocol: from_pool.utilization,
                to_protocol: to_pool.utilization
            },
            "new_util": {
                from_protocol: new_util_from,
                to_protocol: new_util_to
            },
            "util_change": {
                from_protocol: new_util_from - from_pool.utilization,
                to_protocol: new_util_to - to_pool.utilization
            },
            "current_apr": {
                from_protocol: calculate_supply_apr(from_pool.utilization, from_protocol),
                to_protocol: calculate_supply_apr(to_pool.utilization, to_protocol)
            },
            "new_apr": {
                from_protocol: new_apr_from,
                to_protocol: new_apr_to
            },
            "current_weighted_apr": current_weighted_apr,
            "new_weighted_apr": new_weighted_apr,
            "annual_gain_usd": annual_gain_usd,
            "gain_bps": gain_bps,
            "kink_crossings": {
                from_protocol: from_crosses_kink,
                to_protocol: to_crosses_kink
            },
            "profitable": gain_bps > self.min_gain_bps and annual_gain_usd > self.gas_cost_usd
        }
    
    def find_optimal_move(self) -> Dict:
        """
        Find the optimal amount to move between pools to maximize total yield
        Uses 1000 increments to find the precise optimal distribution
        """
        best_move = None
        best_weighted_apr = -float('inf')
        
        # Calculate current weighted APR as baseline
        total_balance = sum(self.position.values())
        current_weighted_apr = 0
        for protocol, balance in self.position.items():
            if balance > 0 and protocol in self.pools:
                current_weighted_apr += calculate_supply_apr(self.pools[protocol].utilization, protocol) * balance
        current_weighted_apr = current_weighted_apr / total_balance if total_balance > 0 else 0
        
        # Track the best APR we've found (start with current)
        best_weighted_apr = current_weighted_apr
        
        # For detailed tracking
        all_results = []
        
        # Check each possible move direction
        for from_protocol in self.position:
            if self.position[from_protocol] <= 0:
                continue
                
            for to_protocol in self.pools:
                if from_protocol == to_protocol:
                    continue
                
                max_amount = self.position[from_protocol]
                
                # Find kink crossing points
                kink_points = self._find_kink_points(from_protocol, to_protocol, max_amount)
                
                # Create test points with 1000 increments for precise optimization
                test_points = []
                
                # Add kink points (critical points where APR changes dramatically)
                test_points.extend(kink_points)
                
                # Add 1000 evenly spaced points for fine-grained search
                increment = max_amount / 1000
                for i in range(0, 1001):  # 0 to 1000 inclusive
                    test_points.append(i * increment)
                
                # Remove duplicates and sort
                test_points = sorted(set([p for p in test_points if 0 <= p <= max_amount]))
                
                if self.verbose:
                    print(f"\n🔍 Testing {len(test_points)} points from {from_protocol} to {to_protocol}...")
                
                # Test each point
                for i, amount in enumerate(test_points):
                    result = self.analyze_move(amount, from_protocol, to_protocol)
                    
                    if "error" not in result:
                        all_results.append({
                            'amount': amount,
                            'weighted_apr': result["new_weighted_apr"],
                            'from': from_protocol,
                            'to': to_protocol
                        })
                        
                        # Track if this is the best so far
                        if result["new_weighted_apr"] > best_weighted_apr:
                            best_weighted_apr = result["new_weighted_apr"]
                            best_move = result
                            
                            # Print when we find a new best
                            if self.verbose and (i % 100 == 0 or amount in kink_points):
                                print(f"  New best at ${amount:,.0f}: {best_weighted_apr*100:.4f}% APR")
                
                # Fine-tune around the best point found using golden section search
                if best_move and best_move["from"] == from_protocol and best_move["to"] == to_protocol:
                    if self.verbose:
                        print(f"\n🎯 Fine-tuning around ${best_move['amount']:,.0f}...")
                    
                    optimal = self._fine_tune_for_max_apr(
                        best_move["amount"], 
                        from_protocol, 
                        to_protocol,
                        max_amount
                    )
                    result = self.analyze_move(optimal, from_protocol, to_protocol)
                    if "error" not in result and result["new_weighted_apr"] > best_weighted_apr:
                        best_weighted_apr = result["new_weighted_apr"]
                        best_move = result
                        if self.verbose:
                            print(f"  Fine-tuned to ${optimal:,.2f}: {best_weighted_apr*100:.4f}% APR")
        
        # Print summary of search
        if self.verbose and all_results:
            print(f"\n📊 Search Summary:")
            print(f"  Tested {len(all_results)} total combinations")
            print(f"  Current APR: {current_weighted_apr*100:.4f}%")
            print(f"  Best APR found: {best_weighted_apr*100:.4f}%")
            if best_move:
                print(f"  Optimal move: ${best_move['amount']:,.2f} from {best_move['from']} to {best_move['to']}")
        
        # Always return the best move found, even if gain is small
        if best_move is None:
            # No move is better than current position
            return {
                "no_move_needed": True,
                "reason": "Current position is already optimal",
                "current_position": self.position,
                "current_weighted_apr": current_weighted_apr,
                "pool_status": {
                    name: {
                        "utilization": pool.utilization,
                        "apr": calculate_supply_apr(pool.utilization, name),
                        "tvl": pool.tvl,
                        "borrows": pool.total_borrow
                    }
                    for name, pool in self.pools.items()
                }
            }
        
        # Add detailed breakdown to the result
        best_move["detailed_breakdown"] = {
            "tests_performed": len(all_results),
            "kink_points_found": len(kink_points) if 'kink_points' in locals() else 0,
            "improvement_bps": (best_weighted_apr - current_weighted_apr) * 10000,
            "current_yield_annual": current_weighted_apr * total_balance,
            "new_yield_annual": best_weighted_apr * total_balance
        }
        
        # Check if the gain is worth the gas cost
        if best_move["gain_bps"] < 0.1 and best_move["annual_gain_usd"] < self.gas_cost_usd:
            best_move["warning"] = f"Gain of {best_move['gain_bps']:.1f} bps may not cover gas costs"
        
        return best_move
    
    def _fine_tune_for_max_apr(self, initial: float, from_protocol: str, to_protocol: str, max_amount: float) -> float:
        """Fine-tune amount to maximize weighted APR using golden section search"""
        # Golden ratio
        phi = (1 + 5**0.5) / 2
        resphi = 2 - phi
        
        # Define search bounds
        left = max(0, initial - max_amount * 0.1)
        right = min(max_amount, initial + max_amount * 0.1)
        
        # Required precision
        tol = 0.1  # 10 cents precision
        
        # Golden section search
        x1 = left + resphi * (right - left)
        x2 = right - resphi * (right - left)
        
        result1 = self.analyze_move(x1, from_protocol, to_protocol)
        result2 = self.analyze_move(x2, from_protocol, to_protocol)
        
        f1 = result1.get("new_weighted_apr", -float('inf'))
        f2 = result2.get("new_weighted_apr", -float('inf'))
        
        iterations = 0
        while abs(right - left) > tol and iterations < 50:
            iterations += 1
            if f1 > f2:
                right = x2
                x2 = x1
                f2 = f1
                x1 = left + resphi * (right - left)
                result1 = self.analyze_move(x1, from_protocol, to_protocol)
                f1 = result1.get("new_weighted_apr", -float('inf'))
            else:
                left = x1
                x1 = x2
                f1 = f2
                x2 = right - resphi * (right - left)
                result2 = self.analyze_move(x2, from_protocol, to_protocol)
                f2 = result2.get("new_weighted_apr", -float('inf'))
        
        return (left + right) / 2
    
    def _find_kink_points(self, from_protocol: str, to_protocol: str, max_amount: float) -> list:
        """Find amounts that cause utilization to hit kink (80%)"""
        kink = 0.80
        points = []
        
        from_pool = self.pools[from_protocol]
        to_pool = self.pools[to_protocol]
        
        # Withdrawing from 'from_protocol' INCREASES its utilization
        if from_pool.utilization < kink:
            # Find amount that pushes utilization to exactly 80%
            # New util = borrows / (tvl - amount) = kink
            # amount = tvl - (borrows / kink)
            amount_to_kink = from_pool.tvl - (from_pool.total_borrow / kink)
            if 0 < amount_to_kink < max_amount:
                points.append(amount_to_kink)
        
        # Depositing to 'to_protocol' DECREASES its utilization
        if to_pool.utilization > kink:
            # Find amount that reduces utilization to exactly 80%
            # New util = borrows / (tvl + amount) = kink
            # amount = (borrows / kink) - tvl
            amount_to_kink = (to_pool.total_borrow / kink) - to_pool.tvl
            if 0 < amount_to_kink < max_amount:
                points.append(amount_to_kink)
        
        return points
    
    def _fine_tune(self, initial: float, from_protocol: str, to_protocol: str, max_amount: float) -> float:
        """Fine-tune amount using ternary search"""
        left = max(0, initial - max_amount * 0.05)
        right = min(max_amount, initial + max_amount * 0.05)
        
        for _ in range(30):
            if right - left < 1:  # $1 precision
                break
            
            mid1 = left + (right - left) / 3
            mid2 = right - (right - left) / 3
            
            result1 = self.analyze_move(mid1, from_protocol, to_protocol)
            result2 = self.analyze_move(mid2, from_protocol, to_protocol)
            
            gain1 = result1.get("gain_bps", -float('inf'))
            gain2 = result2.get("gain_bps", -float('inf'))
            
            if gain1 > gain2:
                right = mid2
            else:
                left = mid1
        
        return (left + right) / 2

# ============================================================================
# MAIN FUNCTION
# ============================================================================

def optimize_from_cron_data(cron_data: str, current_hyperfi_deposit: float = 200000, verbose: bool = True) -> Dict:
    """
    Main function to process cron data and return optimization
    
    Args:
        cron_data: String containing pool data from cron job
        current_hyperfi_deposit: Current deposit in HyperFi
        verbose: Whether to show detailed optimization progress
    
    Returns:
        Dictionary with optimization details
    """
    # Parse the cron data
    pools = parse_cron_data(cron_data)
    
    if not pools:
        return {"error": "Failed to parse cron data"}
    
    # Set up current position
    current_position = {
        "HyperFi": current_hyperfi_deposit,
        "HyperLend": 0
    }
    
    # Create optimizer with very low threshold to find ANY improvement
    optimizer = RealtimeOptimizer(
        pools=pools,
        current_position=current_position,
        min_gain_bps=0.1,  # Even 0.1 bps improvement is worth finding
        gas_cost_usd=10,
        verbose=verbose
    )
    
    # Find optimal move
    result = optimizer.find_optimal_move()
    return result

def format_recommendation(result: Dict) -> str:
    """Format the optimization result for display"""
    if "no_move_needed" in result:
        output = f"\n✅ {result['reason']}\n"
        if "pool_status" in result:
            output += "\n   Current Pool Status:\n"
            for name, status in result["pool_status"].items():
                output += f"   - {name}: {status['utilization']*100:.2f}% util, {status['apr']*100:.2f}% APR\n"
        if "current_weighted_apr" in result:
            output += f"\n   Your current weighted APR: {result['current_weighted_apr']*100:.2f}%\n"
        return output
    
    if "error" in result:
        output = f"\n❌ {result['error']}\n"
        if "reason" in result:
            output += f"   Reason: {result['reason']}\n"
        if "pool_status" in result:
            output += "\n   Current Pool Status:\n"
            for name, status in result["pool_status"].items():
                output += f"   - {name}: {status['utilization']*100:.2f}% util, {status['apr']*100:.2f}% APR\n"
        if "current_weighted_apr" in result:
            output += f"\n   Your current weighted APR: {result['current_weighted_apr']*100:.2f}%\n"
        return output
    
    # Check for kink warnings
    kink_warnings = []
    if result["kink_crossings"].get(result["from"]):
        kink_warnings.append(f"{result['from']} will cross 80% kink")
    if result["kink_crossings"].get(result["to"]):
        kink_warnings.append(f"{result['to']} will cross 80% kink")
    
    warning_text = ""
    if kink_warnings:
        warning_text = "\n║ ⚠️  WARNING: " + ", ".join(kink_warnings)
    
    # Show utilization direction with arrows
    from_util_change = "↑" if result["util_change"][result["from"]] > 0 else "↓"
    to_util_change = "↑" if result["util_change"][result["to"]] > 0 else "↓"
    
    return f"""
╔═══════════════════════════════════════════════════════════════════╗
║                 🎯 OPTIMIZATION RECOMMENDATION                    ║
╠═══════════════════════════════════════════════════════════════════╣
║ ACTION: Move ${result['amount']:,.2f}
║ FROM: {result['from']} 
║ TO: {result['to']}{warning_text}
╠═══════════════════════════════════════════════════════════════════╣
║ UTILIZATION CHANGES:
║   {result['from']}: {result['current_util'][result['from']]*100:.2f}% → {result['new_util'][result['from']]*100:.2f}% {from_util_change}
║   {result['to']}: {result['current_util'][result['to']]*100:.2f}% → {result['new_util'][result['to']]*100:.2f}% {to_util_change}
╠═══════════════════════════════════════════════════════════════════╣
║ APR CHANGES:
║   {result['from']}: {result['current_apr'][result['from']]*100:.2f}% → {result['new_apr'][result['from']]*100:.2f}%
║   {result['to']}: {result['current_apr'][result['to']]*100:.2f}% → {result['new_apr'][result['to']]*100:.2f}%
╠═══════════════════════════════════════════════════════════════════╣
║ YOUR WEIGHTED APR:
║   Current: {result['current_weighted_apr']*100:.3f}%
║   After Move: {result['new_weighted_apr']*100:.3f}%
║   
║ 💰 GAIN: {result['gain_bps']:.1f} basis points
║ 💵 Annual Extra Yield: ${result.get('annual_gain_usd', 0):.2f}
╚═══════════════════════════════════════════════════════════════════╗
"""


def save_result_to_db(result, pools=None):
    """Save optimization result to database with proper error handling"""
    try:
        logger.debug(f"save_result_to_db called with result: {result}")
        if pools:
            logger.debug(f"Pools data: {{k: vars(v) for k, v in pools.items()}}")

        data = {}
        # Determine the result type and extract relevant data
        if result.get("move_recommended"):
            from_protocol = result.get("from")
            to_protocol = result.get("to")
            
            # Safely access pool data
            from_pool = pools.get(from_protocol) if pools else None
            to_pool = pools.get(to_protocol) if pools else None

            data = {
                "from_protocol": from_protocol,
                "to_protocol": to_protocol,
                "amount_usd": result.get("amount", 0),
                "current_apr_from": from_pool.current_apr if from_pool else 0,
                "current_apr_to": to_pool.current_apr if to_pool else 0,
                "projected_apr": to_pool.current_apr if to_pool else 0,
                "utilization_from": from_pool.utilization if from_pool else 0,
                "utilization_to": to_pool.utilization if to_pool else 0,
                "extra_yield_bps": result.get("apr_difference", 0) * 100,
                "notes": "Full move due to large APR difference"
            }
            logger.debug(f"Full move data prepared: {data}")

        elif "amount" in result:
            from_protocol = result.get("from", "HyperFi")
            to_protocol = result.get("to", "HyperLend")
            current_apr = result.get("current_apr", {})
            current_util = result.get("current_util", {})

            data = {
                "from_protocol": from_protocol,
                "to_protocol": to_protocol,
                "amount_usd": result.get("amount", 0),
                "current_apr_from": current_apr.get(from_protocol, 0),
                "current_apr_to": current_apr.get(to_protocol, 0),
                "projected_apr": result.get("new_weighted_apr", 0),
                "utilization_from": current_util.get(from_protocol, 0),
                "utilization_to": current_util.get(to_protocol, 0),
                "extra_yield_bps": result.get("gain_bps", 0),
                "notes": result.get("warning", "Optimized partial move")
            }
            logger.debug(f"Partial move data prepared: {data}")

        else:
            data = {
                "from_protocol": "None",
                "to_protocol": "None",
                "amount_usd": 0,
                "current_apr_from": 0,
                "current_apr_to": 0,
                "projected_apr": result.get("current_weighted_apr", 0),
                "utilization_from": 0,
                "utilization_to": 0,
                "extra_yield_bps": 0,
                "notes": result.get("reason", "No move recommended")
            }
            logger.debug(f"No move data prepared: {data}")

        # Save to database
        OptimizationResultDAO.create_result(data)
        logger.info("Successfully saved optimization result to database")
        
    except Exception as e:
        logger.error(f"Failed to save optimization result: {str(e)}")
        raise
#query to get the latest optimization result
def fetch_most_recent_result():
    try:
        result = OptimizationResultDAO.get_latest_results(limit=1)
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Failed to fetch the most recent result: {str(e)}")
        raise

# === CONFIG ===
PRICE_DECIMALS = 10 ** 8
RPC_URL = os.getenv("BLOCKCHAIN_RPC_URL")
CHAIN = "hyperEvm"

# === HypurrFi Setup ===
web3 = Web3(Web3.HTTPProvider(RPC_URL))
if not web3.is_connected():
    print("❌ Failed to connect to  RPC")
    exit()

ORACLE_ADDRESS = web3.to_checksum_address("0x9BE2ac1ff80950DCeb816842834930887249d9A8")
PROTOCOL_DATA_PROVIDER_ADDRESS = web3.to_checksum_address("0x895C799a5bbdCb63B80bEE5BD94E7b9138D977d6")

with open("data/workers/cron_service/abi/HyFiOracle.json") as f:
    oracle_abi = json.load(f)
with open("data/workers/cron_service/abi/HyFiFiDataProvider.json") as f:
    data_provider_abi = json.load(f)


oracle_contract = web3.eth.contract(address=ORACLE_ADDRESS, abi=oracle_abi)
data_provider_contract = web3.eth.contract(address=PROTOCOL_DATA_PROVIDER_ADDRESS, abi=data_provider_abi)

HYPERLEND_ORACLE_ADDRESS = web3.to_checksum_address("0xC9Fb4fbE842d57EAc1dF3e641a281827493A630e")
HYPERLEND_DATA_PROVIDER_ADDRESS = web3.to_checksum_address("0x5481bf8d3946E6A3168640c1D7523eB59F055a29")


with open("data/workers/cron_service/abi/HyperlendOracle.json") as f:
    hyperlend_oracle_abi = json.load(f)
with open("data/workers/cron_service/abi/HyperlendDataProvider.json") as f:
    hyperlend_data_provider_abi = json.load(f)

hyperlend_oracle_contract = web3.eth.contract(address=HYPERLEND_ORACLE_ADDRESS, abi=hyperlend_oracle_abi)
hyperlend_data_provider_contract = web3.eth.contract(address=HYPERLEND_DATA_PROVIDER_ADDRESS, abi=hyperlend_data_provider_abi)

MORPHO_CONTRACT = "0x68e37de8d93d3496ae143f2e900490f6280c57cd"
FELIX_CONTRACT = "0xD4a426F010986dCad727e8dd6eed44cA4A9b7483"

VAULT_ADDRESSES = {
    "USDe": web3.to_checksum_address("0x835febf893c6dddee5cf762b0f8e31c5b06938ab"),
    "USDT0": web3.to_checksum_address("0xfc5126377f0efc0041c0969ef9ba903ce67d151e"),
    #"HYPE": web3.to_checksum_address("0x2900ABd73631b2f60747e687095537B673c06A76"),
}

markets_by_token = {
    "USDe": [
        "0x292f0a3ddfb642fbaadf258ebcccf9e4b0048a9dc5af93036288502bde1a71b1",  # WHYPE / USDe
        "0x5fe3ac84f3a2c4e3102c3e6e9accb1ec90c30f6ee87ab1fcafc197b8addeb94c",  # UBTC / USDe
    ],
    "USDT0": [
        "0xf9f0473b23ebeb82c83078f0f0f77f27ac534c9fb227cb4366e6057b6163ffbf",  # UETH / USDT0
        "0xace279b5c6eff0a1ce7287249369fa6f4d3d32225e1629b04ef308e0eb568fb0",  # WHYPE / USDT0
        "0x707dddc200e95dc984feb185abf1321cabec8486dca5a9a96fb5202184106e54",  # UBTC / USDT0
        "0xb39e45107152f02502c001a46e2d3513f429d2363323cdaffbc55a951a69b998",  # wstHYPE / USDT0
        "0x86d7bc359391486de8cd1204da45c53d6ada60ab9764450dc691e1775b2e8d69",  # hwHLP / USDT0
        "0xd4fd53f612eaf411a1acea053cfa28cbfeea683273c4133bf115b47a20130305",  # wHLP / USDT0
        "0x78f6b57d825ef01a5dc496ad1f426a6375c685047d07a30cd07ac5107ffc7976",  # kHYPE / USDT0
        "0x888679b2af61343a4c7c0da0639fc5ca5fc5727e246371c4425e4d634c09e1f6",  # kHYPE-PT / USDT0
    ],
    #"HYPE": [
    #    "0x64e7db7f042812d4335947a7cdf6af1093d29478aff5f1ccd93cc67f8aadfddc",  # kHYPE / HYPE
    #    "0xe9a9bb9ed3cc53f4ee9da4eea0370c2c566873d5de807e16559a99907c9ae227",  # wstHYPE / HYPE
    #    "0x1df0d0ebcdc52069692452cb9a3e5cf6c017b237378141eaf08a05ce17205ed6",  # kHYPE-PT / HYPE
    #],
}

token_map = {
    "USDe": web3.to_checksum_address("0x5d3a1Ff2b6BAb83b63cd9AD0787074081a52ef34"),
    "USD₮0": web3.to_checksum_address("0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb"),
    #"HYPE": web3.to_checksum_address("0x5555555555555555555555555555555555555555")
}

HYPERLEND_IRM_ADDRESS = web3.to_checksum_address("0xD01E9AA0ba6a4a06E756BC8C79579E6cef070822")
HYURRFI_IRM_ADDRESS = web3.to_checksum_address("0x701B26833A2dFa145B29Ef1264DE3a5240E17bBD")

with open("data/workers/cron_service/abi/Hyperlend_irm.json") as f:
    hyperlend_irm = json.load(f)

with open("data/workers/cron_service/abi/Hypurrfi_irm.json") as f:
    hypurrfi_irm = json.load(f)

hyperlend_irm_contract = web3.eth.contract(
        address=HYPERLEND_IRM_ADDRESS,
        abi=hyperlend_irm
    )

hypurrfi_irm_contract = web3.eth.contract(
    address=HYURRFI_IRM_ADDRESS,
    abi=hypurrfi_irm
)
# todo: update this with actual pool address
#pool_address_map = {
#    "HyperLend": "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b",
#    "HypurrFi": "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b",
    #"Felix": "0x0000000000000000000000000000000000000000"
#}
pool_address_map = {
    # Protocols with one pool address use a "default" key
    "HyperLend": {
        "default": "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b"
    },
    "HypurrFi": {
        "default": "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b"
    },
    # Felix now maps specific tokens to their unique pool addresses
    "Felix": {
        "USDe": "0x835FEBF893c6DdDee5CF762B0f8e31C5B06938ab",
        "USDT0": "0xfc5126377f0efc0041c0969ef9ba903ce67d151e"  
    }
}
# === Functions ===

def load_abi(filename: str) -> list:
    """Load ABI from JSON file"""
    with open(filename, 'r') as f:
        return json.load(f)

def setup_contracts(web3: Web3, vault_address: str) -> Tuple[Any, Any]:
    morpho_abi = load_abi('data/workers/cron_service/abi/Morpho.json')
    felix_abi = load_abi('data/workers/cron_service/abi/Felix.json')
    vault_abi = load_abi('data/workers/cron_service/abi/vault.json')
    oracle_abi = load_abi('data/workers/cron_service/abi/HyFiOracle.json')

    morpho_contract = web3.eth.contract(
        address=web3.to_checksum_address(MORPHO_CONTRACT),
        abi=morpho_abi
    )

    felix_contract = web3.eth.contract(
        address=web3.to_checksum_address(FELIX_CONTRACT),
        abi=felix_abi
    )
    
    vault_contract = web3.eth.contract(
        address=web3.to_checksum_address(vault_address),
        abi=vault_abi
    )

    oracle_contract = web3.eth.contract(
        address=ORACLE_ADDRESS,
        abi=oracle_abi
    )

    return morpho_contract, felix_contract, vault_contract , oracle_contract

def get_hyperlend_yields_and_tvl():
    try:
        SECONDS_PER_YEAR = 31536000
        RAY = 10**27
        PRICE_DECIMALS = 10**8

        # Your known tokens whitelist and their addresses
        WHITELIST = ["USDe", "USD₮0"]

        # Get prices for these tokens
        price_addresses = [token_map[symbol] for symbol in WHITELIST]
        prices = hyperlend_oracle_contract.functions.getAssetsPrices(price_addresses).call()
        price_dict = {symbol: price for symbol, price in zip(WHITELIST, prices)}

        results = {}

        # Loop only over your known tokens
        for token_symbol in WHITELIST:
            token_address = token_map[token_symbol]
            try:
                reserve_data = hyperlend_data_provider_contract.functions.getReserveData(token_address).call()
                config_data = hyperlend_data_provider_contract.functions.getReserveConfigurationData(token_address).call()
                total_supply = hyperlend_data_provider_contract.functions.getATokenTotalSupply(token_address).call()

                liquidity_rate = reserve_data[5]
                decimals = config_data[0]
                token_price = price_dict.get(token_symbol, 0)

                apy = 0.0
                if liquidity_rate > 0:
                    liquidity_rate_decimal = liquidity_rate / RAY
                    apy = ((1 + liquidity_rate_decimal / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1) * 100

                tvl = 0.0
                if total_supply > 0 and token_price > 0:
                    tvl = (total_supply * token_price) / (10 ** decimals * PRICE_DECIMALS)

                results[token_symbol.replace("₮", "T")] = {
                    "apy": round(apy, 2),
                    "tvl": round(tvl, 2)
                }

            except Exception as e:
                print(f"⚠️ Error processing {token_symbol}: {str(e)}")
                continue

        return results

    except Exception as e:
        print(f"❌ Error fetching HyperLend data on-chain: {e}")
        return {}

def get_hypurrfi_yields_and_tvl():
    SECONDS_PER_YEAR = 365 * 24 * 60 * 60
    RAY = 10**27
    PRICE_DECIMALS = 10**8

    # Your known whitelist tokens and their addresses
    WHITELIST = ["USD₮0", "USDe"]
    token_map = {
        "USD₮0": web3.to_checksum_address("0xB8CE59FC3717ada4C02eaDF9682A9e934F625ebb"),
        #"HYPE": web3.to_checksum_address("0x5555555555555555555555555555555555555555"),
        "USDe": web3.to_checksum_address("0x5d3a1Ff2b6BAb83b63cd9AD0787074081a52ef34"),
    }

    results = {}

    for symbol in WHITELIST:
        address = token_map.get(symbol)
        if not address:
            print(f"⚠️ Address for token {symbol} not found in token_map")
            continue

        try:
            # Get reserve data
            data1 = data_provider_contract.functions.getReserveData(address).call()
            data2 = data_provider_contract.functions.getReserveConfigurationData(address).call()
            liquidity_rate = data1[5]  # liquidityRate in ray
            decimals = data2[0]  # token decimals per reserve
            DECIMALS = 10 ** decimals

            # Calculate APY with edge case handling
            apy = 0.0
            if liquidity_rate > 0:
                liquidity_rate_decimal = liquidity_rate / RAY
                apy = ((1 + liquidity_rate_decimal / SECONDS_PER_YEAR) ** SECONDS_PER_YEAR - 1) * 100

            # TVL Calculation
            tvl_usd = 0.0
            try:
                total_supply = data_provider_contract.functions.getATokenTotalSupply(address).call()
                token_price = hyperlend_oracle_contract.functions.getAssetPrice(address).call()
                if total_supply > 0 and token_price > 0:
                    tvl_usd = (total_supply * token_price) / (DECIMALS * PRICE_DECIMALS)
            except Exception as e:
                tvl_usd = 0.0

            results[symbol.replace("₮", "T")] = {
                "apy": round(apy, 2),
                "tvl": round(tvl_usd, 2)
            }

        except Exception as e:
            print(f"⚠️ Error processing {symbol}: {str(e)}")
            continue

    return results

#here starts for felix
def fetch_market_params(morpho_contract, market_id: str) -> Dict[str, Any]:
    """Fetch MarketParams from Morpho contract"""
    try:
        market_params = morpho_contract.functions.idToMarketParams(market_id).call()
        
        # Convert tuple to dict for easier handling
        return {
            'loanToken': market_params[0],
            'collateralToken': market_params[1],
            'oracle': market_params[2],
            'irm': market_params[3],
            'lltv': market_params[4]
        }
    except Exception as e:
        print(f"Error fetching market params: {e}")
        return None

def fetch_market_data(morpho_contract, market_id: str) -> Dict[str, Any]:
    """Fetch Market struct from Morpho contract"""
    try:
        market_data = morpho_contract.functions.market(market_id).call()
        
        # Convert tuple to dict for easier handling
        
        return {
            'totalSupplyAssets': market_data[0],
            'totalSupplyShares': market_data[1],
            'totalBorrowAssets': market_data[2],
            'totalBorrowShares': market_data[3],
            'lastUpdate': market_data[4],
            'fee': market_data[5]
        }
    except Exception as e:
        print(f"Error fetching market data: {e}")
        return None

def call_borrow_rate_view(felix_contract, market_params: Dict, market_data: Dict) -> int:
    """Call borrowRateView function on Felix contract"""
    try:
        # Convert dicts back to tuples for contract call
        market_params_tuple = (
            market_params['loanToken'],
            market_params['collateralToken'],
            market_params['oracle'],
            market_params['irm'],
            market_params['lltv']
        )
        
        market_data_tuple = (
            market_data['totalSupplyAssets'],
            market_data['totalSupplyShares'],
            market_data['totalBorrowAssets'],
            market_data['totalBorrowShares'],
            market_data['lastUpdate'],
            market_data['fee']
        )
        
        borrow_rate = felix_contract.functions.borrowRateView(
            market_params_tuple, 
            market_data_tuple
        ).call()
        
        return borrow_rate
    except Exception as e:
        print(f"Error calling borrowRateView: {e}")
        return None

def calculate_borrow_apy(borrow_rate: int) -> float:
    """
    Compute borrow APY from borrow rate (per second), compounded annually.
    Assumes borrow_rate is in 1e18 units (wei).
    """
    rate_per_second = borrow_rate / 1e18 
    seconds_per_year = 365 * 24 * 3600
    borrow_apy = (1 + rate_per_second) ** seconds_per_year - 1
    return borrow_apy * 100 

def calculate_supply_apy(borrow_rate: int, market_data: Dict[str, Any]) -> float:
    rate_per_second = borrow_rate / 1e18
    #print(f"Borrow rate per second (decimal): {rate_per_second}")

    util = 0
    if market_data['totalSupplyAssets'] > 0:
        util = market_data['totalBorrowAssets'] / market_data['totalSupplyAssets']
    #print(f"Utilization: {util}")

    fee = market_data['fee'] / 1e18
    #print(f"Fee (decimal): {fee}")

    supply_rate = rate_per_second * util * (1 - 0.1)
    #print(f"Supply rate per second: {supply_rate}")

    seconds_per_year = 365 * 24 * 3600
    #supply_apy = math.exp(supply_rate * seconds_per_year) - 1
    supply_apy = (1 + supply_rate) ** seconds_per_year - 1
    
    return supply_apy * 100  # percentage

def calculate_vault_supply_apy(borrow_rates: list, market_datas: list) -> float:
    total_supply = sum(market_data['totalSupplyAssets'] for market_data in market_datas)
    if total_supply == 0:
        return 0.0
    weighted = 0.0
    for br, market_data in zip(borrow_rates, market_datas):
        weight = market_data['totalSupplyAssets'] / total_supply
        weighted += weight * calculate_supply_apy(br, market_data)
    return weighted

def calculate_vault_tvl(vault_contract, oracle_contract, vault_name: str) -> float:
    try:
        # Step 1: Get underlying asset
        asset_address = vault_contract.functions.asset().call()

        # Step 2: Get total assets and decimals
        raw_total_assets = vault_contract.functions.totalAssets().call()

        # Hardcode decimals for USDT0
        if vault_name == "USDT0":
            decimals = 6
        else:
            decimals = vault_contract.functions.decimals().call()

        # Step 3: Get token price from oracle
        token_price = oracle_contract.functions.getAssetPrice(asset_address).call()

        if raw_total_assets == 0:
            print(f"⚠️ [{vault_name}] totalAssets is 0")
        if token_price == 0:
            print(f"⚠️ [{vault_name}] Oracle returned 0 price for asset")
        if decimals == 0:
            print(f"⚠️ [{vault_name}] Decimals is 0 (unusual)")

        # Step 4: Calculate TVL
        tvl = (raw_total_assets * token_price) / (10 ** decimals * PRICE_DECIMALS)
        print(f"✅ [{vault_name}] TVL: ${tvl:,.2f}")
        return tvl

    except Exception as e:
        print(f"❌ [{vault_name}] Error calculating TVL: {e}")
        return 0.0


FELIX_DYNAMIC_PARAMS = {}
def get_felix_yields_and_tvl():
    global FELIX_DYNAMIC_PARAMS
    results = {}
    for token, market_ids in markets_by_token.items():
        vault_address = VAULT_ADDRESSES[token]
        morpho_contract, felix_contract, vault_contract, oracle_contract = setup_contracts(web3, vault_address)
        borrow_rates, datas = [], []
        total_vault_supply = 0
        total_vault_borrow = 0
        try:
            vault_fee = vault_contract.functions.fee().call() / 1e18  # Convert from uint96 to decimal
        except Exception as e:
            print(f"❌ Failed to fetch vault fee: {e}")
            vault_fee = 0
        underlying_markets_data = []
        for market_id in market_ids:
            
            time.sleep(2)  
            market_params = fetch_market_params(morpho_contract, market_id)
            market_data = fetch_market_data(morpho_contract, market_id)
            
            if not market_params or not market_data:
                print("❌ Skipping: Failed to fetch market params/data")
                continue

            # Calculate utilization
            util = 0
            if market_data['totalSupplyAssets'] > 0:
                util = market_data['totalBorrowAssets'] / market_data['totalSupplyAssets']

            # Fetch borrow rate
            borrow_rate = call_borrow_rate_view(felix_contract, market_params, market_data)
            if borrow_rate is None:
                print("❌ Skipping: Failed to fetch borrow rate")
                continue

            rate_per_second = borrow_rate / 1e18
            borrow_apy = calculate_borrow_apy(borrow_rate)
            supply_apy = calculate_supply_apy(borrow_rate, market_data)
            underlying_markets_data.append({
                "utilization": round(util, 4), 
                "supply_apy_gross": round(supply_apy, 4),
                "total_supply_assets": market_data['totalSupplyAssets'],
                "total_borrow_assets": market_data['totalBorrowAssets'],
                #"protocol_fee": market_data['fee'] / 1e18,
                "lltv": market_params['lltv'] / 1e18,
                #"last_update": market_data['lastUpdate'],
                "loan_token": market_params['loanToken'],
                "collateral_token": market_params['collateralToken'], 
                "oracle": market_params['oracle'],
                "total_supply_shares": market_data['totalSupplyShares'],
                "total_borrow_shares": market_data['totalBorrowShares'],
                "borrow_rate": borrow_rate,
            })

            # Apply vault fee to supply APY
            borrow_rates.append(borrow_rate)
            datas.append(market_data)
            total_vault_supply += market_data['totalSupplyAssets']
            total_vault_borrow += market_data['totalBorrowAssets']

        vault_apy = calculate_vault_supply_apy(borrow_rates, datas) 
        #vault_apy = vault_apy * (1 - vault_fee)
        #vault_apy = vault_apy - (vault_fee * 100)
        
        vault_tvl = calculate_vault_tvl(vault_contract, oracle_contract, token)
        utilization = (total_vault_borrow / total_vault_supply) if total_vault_supply > 0 else Decimal(0)

        sanitized_token = token.replace("₮0", "T0")
        FELIX_DYNAMIC_PARAMS[sanitized_token] = {
            "utilization": utilization,
            "reserve_factor": vault_fee,
            "total_supply": Decimal(total_vault_supply),
            "total_borrows": Decimal(total_vault_borrow),
            "underlying_markets": underlying_markets_data
        }
        results[token] = {
            "apy": round(vault_apy, 2),  # Report the net APY after fees
            "tvl": round(vault_tvl, 2),
        }

    return results


def generate_yield_alerts(hyperlend_data: dict, hypurrfi_data: dict, felix_data: dict) -> list[str]:
    """
    Compares asset yields and generates a LIST of actionable alert strings.

    Returns:
        A list of formatted strings, where each string is a separate alert.
        Returns an empty list if no opportunities are found.
    """
    alerts = []
    
    all_assets = sorted(set(hyperlend_data.keys()) | set(hypurrfi_data.keys()) | set(felix_data.keys()))

    for asset in all_assets:
        protocols = {}
        if asset in hyperlend_data: protocols["HyperLend"] = hyperlend_data[asset]
        if asset in hypurrfi_data: protocols["HypurrFi"] = hypurrfi_data[asset]
        if asset in felix_data: protocols["Felix"] = felix_data[asset]

        if len(protocols) < 2:
            continue

        sorted_protocols = sorted(protocols.items(), key=lambda item: item[1]["apy"], reverse=True)
        
        top_protocol_name, top_protocol_data = sorted_protocols[0]
        second_protocol_name, second_protocol_data = sorted_protocols[1]

        diff = top_protocol_data['apy'] - second_protocol_data['apy']

        if diff > 0.5:
            alert_string = (
                f"✨ Higher Yield available for {asset}\n\n"
                f"➡️ Recommended Action\n"
                f"└ From: {second_protocol_name}\n"
                f"└ To:   {top_protocol_name}\n\n"
                f"📈 Expected Growth\n"
                f"└ From: {second_protocol_data['apy']:.2f}%\n"
                f"└ To:   {top_protocol_data['apy']:.2f}%\n\n"
                f"To capture this opportunity, Neura Vault recommends re-deploying funds for a +{diff:.2f}% higher yield."
            )
            alerts.append(alert_string)

    # Instead of joining, we return the list directly.
    # If no alerts were added, this will be an empty list.
    return alerts

#here ends for felix

def compare_yields(hyperlend_data: dict, hypurrfi_data: dict, felix_data: dict) -> str:
    lines = [
        "📊 *Yield Comparison Report*",
    ]
    
    all_assets = sorted(set(hyperlend_data.keys()) | set(hypurrfi_data.keys()) | set(felix_data.keys()))

    for asset in all_assets:
        protocols = {}

        if asset in hyperlend_data:
            protocols["HyperLend"] = hyperlend_data[asset]
        if asset in hypurrfi_data:
            protocols["HypurrFi"] = hypurrfi_data[asset]
        if asset in felix_data:
            protocols["Felix"] = felix_data[asset]

        if len(protocols) < 2:
            continue  # not enough data to compare

        # Sort protocols by APY descending
        sorted_protocols = sorted(protocols.items(), key=lambda x: x[1]["apy"], reverse=True)
        top1_name, top1_data = sorted_protocols[0]
        top2_name, top2_data = sorted_protocols[1]

        line = f"\n🪙 *{asset}*"
        recommendations = []

        # List all protocol APYs and TVLs
        for name, data in protocols.items():
            line += f"\n  - {name}: {data['apy']:.2f}% (TVL: ${data['tvl']:,.2f})"

        # Yield comparison
        diff = top1_data['apy'] - top2_data['apy']
        if abs(diff) < 0.5:
            recommendations.append("🔹 Top two protocols offer similar yields currently")
        else:
            recommendations.append(f"🔸 {top1_name} offers {abs(diff):.2f}% higher yield than {top2_name}")

   
        lines.append(line)
        if recommendations:
            lines.extend(recommendations)

    return "\n".join(lines)

POOL_ADDRESS_TO_TOKEN = {
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    "0x4ed4e862860bed51a9570b96d89af5e1b0efefed": "USDe",
    "0x50c5725949a6f092e06c4207c340744954b09078": "weETH",
    "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b": "WETH" 
}

def save_yield_reports(yields_data, token_addresses, pool_addresses, protocol_params): # <-- Add token_addresses here
    """
    Saves the yield data from different protocols to the database.
    """
    all_tokens = {}
    # Collect all data and find the best APY per token
    for protocol, yields in yields_data.items():
        for token, data in yields.items():
            if token not in all_tokens:
                all_tokens[token] = []
            
            # Ensure data is in Decimal format for the model
            apy = Decimal(str(data.get('apy', 0)))
            tvl = Decimal(str(data.get('tvl', 0)))
            
            all_tokens[token].append({
                'protocol': protocol,
                'apy': apy,
                'tvl': tvl
            })

    # Save each entry, marking the best one
    for token, reports in all_tokens.items():
        if not reports:
            continue

        # Find the report with the highest APY for the current token
        best_report = max(reports, key=lambda x: x['apy'])

        for report in reports:
            is_best = (report['protocol'] == best_report['protocol'] and report['apy'] == best_report['apy'])
            protocol_pools = pool_addresses.get(report['protocol'], {})
            # Get the pool address for the specific protocol and token
            pool_addr = protocol_pools.get(token, protocol_pools.get('default'))
            params_for_entry = protocol_params.get(report['protocol'], {}).get(token, {})
            params_json_string = json.dumps(params_for_entry, default=decimal_default_converter) if params_for_entry else "{}"
            YieldReportDAL.create_yield_report(
                token=token,
                protocol=report['protocol'],
                apy=report['apy'],
                tvl=report['tvl'],
                is_current_best=is_best,
                token_address=token_addresses.get(token),
                pool_address=pool_addr,
                params=params_json_string
            )

def format_rebalancing_message(deposit_trade: dict, withdrawal_trade: dict) -> str | None:
    """Formats the rebalancing data into a user-friendly message."""
    try:
        # Extract data from the trades
        amount = abs(float(deposit_trade['amount_formatted']))
        pool_address = deposit_trade['pool_address']
        token_symbol = POOL_ADDRESS_TO_TOKEN.get(pool_address, "tokens") # Fallback to "tokens"

        from_protocol = withdrawal_trade['protocol']
        to_protocol = deposit_trade['protocol']
        tx_hash = deposit_trade['transaction_hash']

        # Construct the Basescan link
        tx_link = f"https://basescan.org/tx/{tx_hash}"

        # Build the message string
        message = (
            f"📈 **Rebalancing Complete** 📉\n\n"
            f"A position of **{amount:.6f} {token_symbol}** on Base has been moved to a new protocol to optimize yield.\n\n"
            f"**Protocol Change:**\n"
            f"➡️ From: `{from_protocol}`\n"
            f"⬅️ To: `{to_protocol}`\n\n"
            f"Sentient handles the optimization, so you don't have to.\n\n"
            f"[View Transaction]({tx_link})"
        )
        return message

    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"Failed to format message due to missing/invalid data: {e}")
        return None

async def notify_latest_rebalance():
    """
    Fetches the latest rebalancing trades and broadcasts a notification for the newest pair.
    This version robustly finds the matching pair using their allocation_index.
    """
    logger.info("--- Fetching latest rebalancing event for broadcast ---")

    if not API_BASE_URL:
        logger.critical("API_BASE_URL is not set in the environment file.")
        return

    # 1. Fetch the latest rebalancing trades from the API
    api_url = f"{API_BASE_URL}/api/rebalancing-trades/"
    params = {
        "scenario_type": "REBALANCING",
        "status": "SUCCESS",
        "page_size": 100
    }
    recent_trades = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, params=params, timeout=20)
            if response.status_code == 200:
                api_response = response.json()
                if isinstance(api_response, dict):
                    recent_trades = api_response.get("results", [])
                else:
                    recent_trades = api_response
            else:
                logger.error(f"API returned non-200 status: {response.status_code} - {response.text}")
                return
    except httpx.RequestError as e:
        logger.error(f"Error calling rebalancing API: {e}")
        return

    if not recent_trades or len(recent_trades) < 2:
        logger.warning("API returned fewer than 2 rebalancing trades. Cannot form a pair.")
        return

    # --- START OF THE FIX ---
    # 2. Find the latest deposit and its withdrawal partner by searching the list
    deposit_trade = None
    withdrawal_trade = None

    # First, find the most recent successful rebalancing DEPOSIT in the list
    for trade in recent_trades:
        if trade['transaction_type'] == 'DEPOSIT':
            deposit_trade = trade
            break # Stop once we've found the newest one (list is ordered by date)

    if not deposit_trade:
        logger.warning("No successful rebalancing DEPOSIT found in the recent trades.")
        return

    # Now, find the matching WITHDRAWAL using the allocation_index
    target_index = deposit_trade.get('allocation_index')
    for trade in recent_trades:
        if trade['transaction_type'] == 'WITHDRAWAL' and trade.get('allocation_index') == target_index:
            withdrawal_trade = trade
            break # Stop once we've found the partner

    if not withdrawal_trade:
        logger.warning(f"Found deposit (ID: {deposit_trade['id']}) but could not find its withdrawal partner with allocation_index: {target_index}.")
        return
    
    logger.info(f"Successfully paired Deposit ID {deposit_trade['id']} with Withdrawal ID {withdrawal_trade['id']}.")
    # --- END OF THE FIX ---

    message = format_rebalancing_message(deposit_trade, withdrawal_trade)

    if not message:
        logger.error("Failed to format the rebalancing message. Aborting broadcast.")
        return

    # 3. Broadcast the message to all users
    user_ids = await get_all_user_ids_from_api()
    if user_ids:
        logger.info(f"Broadcasting notification for tx {deposit_trade['transaction_hash']} to {len(user_ids)} users.")
        await broadcast_messages(user_ids, message)
    else:
        logger.warning("No users found to send the rebalancing notification to.")

    logger.info("--- Rebalancing notification process complete ---")

def _get_reserve_details(provider_contract: Contract, asset_address: str) -> dict:
    """
    Helper to fetch and normalize reserve factor and utilization for a specific asset.
    """
    try:
        # Fetch utilization data
        reserve_data = provider_contract.functions.getReserveData(asset_address).call()
        available_liquidity = Decimal(reserve_data[2])
        total_stable_debt = Decimal(reserve_data[3])
        total_variable_debt = Decimal(reserve_data[4])
        
        total_borrows = total_stable_debt + total_variable_debt
        total_supply = Decimal(reserve_data[2])
        utilization = (total_borrows / total_supply) if total_supply > 0 else Decimal(0)

        # Fetch reserve factor from its correct location
        config_data = provider_contract.functions.getReserveConfigurationData(asset_address).call()
        # In Aave V2 style providers, reserveFactor is at index 4 and scaled by 10000
        raw_reserve_factor = config_data[4] 
        reserve_factor = Decimal(raw_reserve_factor) / Decimal(10000)
        
        return {
            "utilization": utilization,
            "reserve_factor": reserve_factor,
            "total_supply": total_supply,
            "total_borrows": total_borrows
        }

    except Exception as e:
        print(f"⚠️  Warning: Could not fetch reserve details for asset {asset_address}. Error: {e}")
        return { "utilization": Decimal(0), "reserve_factor": Decimal("0.10"), "total_supply": Decimal(0),
            "total_borrows": Decimal(0),}

def fetch_on_chain_protocol_params(
    hyperlend_irm_contract: Contract,
    hypurrfi_irm_contract: Contract,
    hyperlend_data_provider_contract: Contract,
    hypurrfi_data_provider_contract: Contract,
    token_map: dict
) -> dict:
    """
    Fetches and FULLY NORMALIZES interest rate model parameters for all protocols.
    """
    RAY = Decimal(10**27)
    PROTOCOL_PARAMS = { "HyperLend": {}, "HypurrFi": {}, "Felix": {} }
    HYPURRFI_API_URL = "https://app.hypurr.fi/api/markets/pooled"#os.getenv("HYPURRFI_API_URL")
    HYPERLEND_API_URL= "https://api.hyperlend.finance/data/markets?chain=hyperEvm" #os.getenv("HYPERLEND_API_URL")
    global FELIX_DYNAMIC_PARAMS

    # --- 1. Fetch HyperLend Parameters ---
    try:
        print("⚙️  Fetching and normalizing data for Hyperlend from API...")
        with httpx.Client() as client:
            response = client.get(HYPERLEND_API_URL)
            response.raise_for_status()
            markets_data = response.json().get("reserves", [])
        for market in markets_data:
            token_symbol = market.get("symbol")
            if not token_symbol:
                continue
            irm_params = {
                "kink": Decimal(market.get("optimalUsageRatio", 0)) / RAY,
                "base_rate": Decimal(market.get("baseVariableBorrowRate", 0)) / RAY,
                "slope1": Decimal(market.get("variableRateSlope1", 0)) / RAY,
                "slope2": Decimal(market.get("variableRateSlope2", 0)) / RAY,
            }
            token_address = token_map.get(token_symbol)
            if not token_address:
                continue 
            reserve_details = _get_reserve_details(hyperlend_data_provider_contract, token_address)
            PROTOCOL_PARAMS["HyperLend"][token_symbol.replace("₮0", "T0")] = {**irm_params, **reserve_details}

    except Exception as e:
        print(f"❌ Error fetching HyperLend parameters: {e}")

    # --- 2. Fetch HypurrFi Parameters ---
    try:
        print("⚙️  Fetching and normalizing data for HypurrFi from API...")
        with httpx.Client() as client:
            response = client.get(HYPURRFI_API_URL)
            response.raise_for_status()
            markets_data = response.json().get("reserves", [])
        for market in markets_data:
            token_symbol = market.get("symbol")
            if  not token_symbol:
                continue
            irm_params = {
                "kink": Decimal(market.get("optimalUsageRatio", 0)) / RAY,
                "base_rate": Decimal(market.get("baseVariableBorrowRate", 0)) / RAY,
                "slope1": Decimal(market.get("variableRateSlope1", 0)) / RAY,
                "slope2": Decimal(market.get("variableRateSlope2", 0)) / RAY,
            }
            token_address = token_map.get(token_symbol)
            if not token_address:
                continue 
            reserve_details = _get_reserve_details(hypurrfi_data_provider_contract, token_address)
            PROTOCOL_PARAMS["HypurrFi"][token_symbol.replace("₮0", "T0")] = {**irm_params, **reserve_details}
    except Exception as e:
        print(f"❌ Error fetching HypurrFi parameters: {e}")
    
    print("📝 Processing parameters for Felix...")
    # These IRM values are hardcoded from the ConstantsLib.sol file
    felix_irm_params = {
        "curve_steepness": Decimal("4.0"),          # from CURVE_STEEPNESS
        "adjustment_speed": Decimal("50.0"),        # from ADJUSTMENT_SPEED (annualized)
        "target_utilization": Decimal("0.90"),      # from TARGET_UTILIZATION
        "initial_rate_at_target": Decimal("0.04"),  # from INITIAL_RATE_AT_TARGET
        "min_rate_at_target": Decimal("0.001"),     # from MIN_RATE_AT_TARGET
        "max_rate_at_target": Decimal("2.00"),  
    }

    for token, dynamic_data in FELIX_DYNAMIC_PARAMS.items():
        sanitized_token = token.replace("₮0", "T0")
        PROTOCOL_PARAMS["Felix"][sanitized_token] = {**felix_irm_params, **dynamic_data}
    
    print("✅ Successfully finished fetching and normalizing all protocol parameters.")
    return PROTOCOL_PARAMS

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Example 1: Your exact cron data
    print("=" * 70)
    print("REAL-TIME OPTIMIZATION FROM CRON DATA")
    print("=" * 70)
    
    cron_data = """
hyplend usde - 15.00% apr. USDe supplied/tvl- $2,950,186.42, utilisation rate= 82.91%
Hypurfi USDe- 12.50% apr. USDe supplied/tvl- $2,310,000, utilisation rate= 82.19%
"""
    
    print("📊 Current Market Data:")
    print("-" * 70)
    pools = parse_cron_data(cron_data)
    for name, pool in pools.items():
        print(f"{name:10} | APR: {pool.current_apr*100:6.2f}% | TVL: ${pool.tvl:13,.2f} | Util: {pool.utilization*100:6.2f}%")
        print(f"           | Borrows: ${pool.total_borrow:13,.2f} | Available: ${pool.available_liquidity:13,.2f}")
    
    print("\n💼 Your Position:")
    print("-" * 70)
    print("HyperFi: $200,000")
    print("HyperLend: $0")
    print(f"Current Yield: $200,000 × {pools['HyperFi'].current_apr*100:.2f}% = ${200000 * pools['HyperFi'].current_apr:,.2f}/year")

    # First check APR difference
    apr_check = check_apr_difference_move(cron_data, current_hyperfi_deposit=200000)
    #print("DEBUG apr_check:", apr_check)
    if apr_check.get('move_recommended'):
        print("\n" + "=" * 70)
        print("⚠️ LARGE APR DIFFERENCE DETECTED - FULL POSITION MOVE RECOMMENDED")
        print("=" * 70)
        print(f"Move ALL ${apr_check.get('amount', 0):,.2f} from {apr_check.get('from')} to {apr_check.get('to')}")
        print(f"APR Difference: {apr_check.get('apr_difference', 0):.2f}%")
        print(f"Estimated Annual Gain: ${apr_check.get('annual_gain', 0):,.2f}")
        print("=" * 70)
        save_result_to_db(apr_check, pools)

    else:
        # Only run optimization if no full move needed
        result = optimize_from_cron_data(cron_data, current_hyperfi_deposit=200000)
        print(format_recommendation(result))
        save_result_to_db(result, pools)


        if "amount" in result and result["amount"] > 0:
            print("\n🎯 Why This Is Optimal:")
            print("-" * 70)
            print(f"• Moving ${result['amount']:,.2f} optimally balances the yield differential")
            
            print("\nUtilization Changes:")
            print(f"  HyperFi: {result['current_util']['HyperFi']*100:.2f}% → {result['new_util']['HyperFi']*100:.2f}% {'↑' if result['util_change']['HyperFi'] > 0 else '↓'}")
            print(f"  HyperLend: {result['current_util']['HyperLend']*100:.2f}% → {result['new_util']['HyperLend']*100:.2f}% {'↑' if result['util_change']['HyperLend'] > 0 else '↓'}")
            
            print("\nAPR Changes:")
            print(f"  HyperFi: {result['current_apr']['HyperFi']*100:.2f}% → {result['new_apr']['HyperFi']*100:.2f}%")
            print(f"  HyperLend: {result['current_apr']['HyperLend']*100:.2f}% → {result['new_apr']['HyperLend']*100:.2f}%")
            
            new_balance_hf = 200000 - result["amount"]
            new_balance_hl = result["amount"]
            
            print("\n💰 Yield Calculation:")
            print(f"  Before: $200,000 × {result['current_weighted_apr']*100:.2f}% = ${200000 * result['current_weighted_apr']:,.2f}/year")
            print(f"  After:")
            print(f"    HyperFi: ${new_balance_hf:,.2f} × {result['new_apr']['HyperFi']*100:.2f}% = ${new_balance_hf * result['new_apr']['HyperFi']:,.2f}/year")
            print(f"    HyperLend: ${new_balance_hl:,.2f} × {result['new_apr']['HyperLend']*100:.2f}% = ${new_balance_hl * result['new_apr']['HyperLend']:,.2f}/year")
            print(f"    Total: ${(new_balance_hf * result['new_apr']['HyperFi'] + new_balance_hl * result['new_apr']['HyperLend']):,.2f}/year")
            print(f"\n📈 Additional yield: ${result['annual_gain_usd']:,.2f}/year ({result['gain_bps']:.1f} bps)")
            
            if result.get('kink_crossings', {}).get('HyperLend'):
                print("\n⚠️ Note: This move crosses HyperLend's 80% kink threshold")
            if result.get('kink_crossings', {}).get('HyperFi'):
                print("⚠️ Note: This move crosses HyperFi's 80% kink threshold")
            
            if "detailed_breakdown" in result:
                print("\n📊 Optimization Stats:")
                print(f"  • Tested {result['detailed_breakdown']['tests_performed']} different amounts")
                print(f"  • Found {result['detailed_breakdown']['kink_points_found']} critical kink points")
                print(f"  • Improvement: {result['detailed_breakdown']['improvement_bps']:.2f} basis points")

    # Show detailed impact analysis if optimization was performed
    if not apr_check.get('move_recommended'):
        print("\n" + "=" * 70)
        print("DETAILED IMPACT ANALYSIS - Finding the Optimal Distribution")
        print("=" * 70)
        
        optimizer = RealtimeOptimizer(
            pools=parse_cron_data(cron_data),
            current_position={"HyperFi": 200000, "HyperLend": 0},
            min_gain_bps=0.1,
            verbose=False
        )
        
        print("\nOptimization Table - Finding Maximum Yield Distribution:")
        print("-" * 120)
        print(f"{'Amount':<15} {'HF Balance':<15} {'HL Balance':<15} {'HF Util→APR':<20} {'HL Util→APR':<20} {'Weighted APR':<15} {'Annual Yield':<15} {'Note':<10}")
        print("-" * 120)
        
        best_apr = 0
        best_amount = 0
        best_yield = 0
        
        test_amounts = [0, 10000, 20000, 30000, 40000, 45000, 50000, 55000, 60000, 70000, 80000, 
                        90000, 100000, 110000, 120000, 140000, 160000, 180000, 200000]
        
        for amount in test_amounts:
            result = optimizer.analyze_move(amount, "HyperFi", "HyperLend")
            if "error" not in result:
                hf_balance = 200000 - amount
                hl_balance = amount
                
                hf_util_apr = f"{result['new_util']['HyperFi']*100:.1f}%→{result['new_apr']['HyperFi']*100:.2f}%"
                hl_util_apr = f"{result['new_util']['HyperLend']*100:.1f}%→{result['new_apr']['HyperLend']*100:.2f}%"
                
                annual_yield = hf_balance * result['new_apr']['HyperFi'] + hl_balance * result['new_apr']['HyperLend']
                
                note = ""
                if result['new_weighted_apr'] > best_apr:
                    best_apr = result['new_weighted_apr']
                    best_amount = amount
                    best_yield = annual_yield
                    note = "← BEST"
                
                if result['kink_crossings']['HyperFi']:
                    note += " ⚠️HF"
                if result['kink_crossings']['HyperLend']:
                    note += " ⚠️HL"
                
                print(f"${amount:<14,} ${hf_balance:<14,} ${hl_balance:<14,} {hf_util_apr:<20} {hl_util_apr:<20} "
                      f"{result['new_weighted_apr']*100:>13.3f}% ${annual_yield:>14,.2f} {note}")
        
        print("-" * 120)
        print(f"\n💡 Optimal Distribution: Move ${best_amount:,} to HyperLend")
        print(f"   • Keep ${200000-best_amount:,} in HyperFi")  
        print(f"   • Weighted APR: {best_apr*100:.3f}%")
        print(f"   • Annual Yield: ${best_yield:,.2f}")
        print(f"   • Gain vs current: ${best_yield - (200000 * pools['HyperFi'].current_apr):,.2f}/year")
        
        print("\n📝 Key Insights:")
        print("-" * 70)
        print("• The optimizer tests 1000+ points to find the exact optimum")
        print("• HyperLend at 82.91% util offers higher APR but will drop if too much is deposited")
        print("• HyperFi at 82.19% util offers lower APR but will increase if funds are withdrawn")
        print("• The sweet spot maximizes (balance_in_HF × APR_HF) + (balance_in_HL × APR_HL)")
        print("• ⚠️ marks where utilization crosses the 80% kink threshold")
        print("• Even small optimizations compound significantly over time!")
    
    # Example 2: More favorable scenario
    print("\n\n" + "=" * 70)
    print("SCENARIO 2: HyperLend Below Kink (More Favorable)")
    print("=" * 70)
    
    cron_data_2 = """
    hyplend usde - 3.50% apr. USDe supplied/tvl- $5,000,000, utilisation rate= 75.00%
    Hypurfi USDe- 4.25% apr. USDe supplied/tvl- $3,000,000, utilisation rate= 85.00%
    """
    
    pools2 = parse_cron_data(cron_data_2)
    print("📊 Market Data:")
    for name, pool in pools2.items():
        print(f"{name:10} | APR: {pool.current_apr*100:6.2f}% | TVL: ${pool.tvl:13,.2f} | Util: {pool.utilization*100:6.2f}%")
    
    result2 = optimize_from_cron_data(cron_data_2, current_hyperfi_deposit=200000, verbose=False)
    print(format_recommendation(result2))
    save_result_to_db(result2, pools2)

    print("\n" + "=" * 70)
    print("FETCHING MOST RECENTLY SAVED RESULT FROM DB")
    print("=" * 70)
    most_recent_result = fetch_most_recent_result()
    if most_recent_result:
        print(f"ID: {most_recent_result.id}")
        print(f"Timestamp: {most_recent_result.timestamp}")
        print(f"From: {most_recent_result.from_protocol}")
        print(f"To: {most_recent_result.to_protocol}")
        print(f"Amount: ${most_recent_result.amount_usd:,.2f}")
        print(f"Note: {most_recent_result.notes}")
    else:
        print("No results found in the database.")
    
    yields_hyperlend = get_hyperlend_yields_and_tvl()
    yields_hypurrfi = get_hypurrfi_yields_and_tvl()
    yields_felix = get_felix_yields_and_tvl()

    all_yields_data = {
        'HyperLend': yields_hyperlend,
        'HypurrFi': yields_hypurrfi,
        'Felix': yields_felix
    }
    
    # Define pool addresses for each protocol and token
    # For HyperLend and HypurrFi, the 'pool' is the token reserve itself.
    # For Felix, the 'pool' is the specific vault address for that token.
    pool_addresses = {
        'HyperLend': {
            'USDe': "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b",
            'USDT0': "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b",
            'HYPE': "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b",
        },
        'HypurrFi': {
            'USDe': "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b",
            'USDT0': "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b",
            'HYPE': "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b",
        },
        'Felix': {
            'USDe':"0x835FEBF893c6DdDee5CF762B0f8e31C5B06938ab", #VAULT_ADDRESSES.get('USDe'),
            'USDT0':"0xfc5126377f0efc0041c0969ef9ba903ce67d151e", #VAULT_ADDRESSES.get('USDT0'),
            'HYPE': VAULT_ADDRESSES.get('HYPE'),
        }
    }


    significant_change_detected = False
    alerts_to_generate = {}

    #we have to call the funciton get the data if the data is different as compared to recent then asyncio broadcast messages

    #asyncio.run(notify_latest_rebalance())
    # The token map needs to use the sanitized token symbols to match the keys in yields_data
    on_chain_params = fetch_on_chain_protocol_params(
        hyperlend_irm_contract,
        hypurrfi_irm_contract,
        hyperlend_data_provider_contract,
        data_provider_contract,
        token_map
    )
    sanitized_token_map = {k.replace('₮', 'T'): v for k, v in token_map.items()}
    # Always save yield reports regardless of APY differences
    should_save = True
    for token in sanitized_token_map.keys():
        best_apy, protocol = yield_monitor.get_best_apy(token)
        current_apy = 0
        current_protocol = None
        for protocol_name, protocol_data in all_yields_data.items():
            if token in protocol_data and 'apy' in protocol_data[token]:
                if protocol_data[token]['apy'] > current_apy:
                    current_apy = protocol_data[token]['apy']
                    current_protocol = protocol_name
        if best_apy > 0:
            if current_apy > 0:  # If we found current APY data
                apy_difference = abs(float(current_apy) - float(best_apy))
                
                if apy_difference >= 0.2:  
                    print(f"⚠️  Significant APY difference found for {token}: {apy_difference:.2f}% (current: {current_apy:.2f}% in {current_protocol} vs best: {best_apy:.2f}% in {protocol})")
                    should_save = True  # We want to save when there's a significant difference
                else:
                    should_save = True
                    print(f"✅ APY difference for {token} is within normal range: {apy_difference:.2f}% (current: {current_apy:.2f}% in {current_protocol} vs best: {best_apy:.2f}% in {protocol})")
        elif current_apy > 0:
            print(f"ℹ️ No previous data found for {token}. Saving latest APY: {current_apy:.2f}% from {current_protocol}.")
            should_save = True
    if should_save:
        print("\n💾 Saving yield reports to database due to significant APY differences...")
        save_yield_reports(all_yields_data, sanitized_token_map, pool_address_map, on_chain_params)
        
        # Get the list of individual alert messages
        #alert_messages = generate_yield_alerts(yields_hyperlend, yields_hypurrfi, yields_felix)
        #user_ids = asyncio.run(get_all_user_ids_from_api())
        #if alert_messages:
        #    print(f"📢 Found {len(alert_messages)} yield opportunities. Broadcasting alerts individually...")
            # Loop through each message and broadcast it separately
        #    for alert in alert_messages:
        #        asyncio.run(broadcast_messages(user_ids,alert))
        #    print("✅ Successfully sent all alert messages.")
        #else:
        #    print("ℹ️ No specific alerts were generated based on comparison logic.")
    
    else:
        # This should never happen now, but keeping as a fallback
        print("\n⚠️  should_save flag is False, saving reports anyway...")
        save_yield_reports(all_yields_data, sanitized_token_map, pool_address_map, on_chain_params)
    