#!/usr/bin/env python3
"""
Patched Structured-only Pool Optimizer — model-consistent baseline

Key changes:
- Decision (gain_bps / profitable) uses the **modelled current APY** computed
  from the same kinked model at each pool's current utilization.
- The script still shows the observed current APR (converted to APY) for
  transparency, but it is NOT used for the profit/stability decision.
- Keeps strict requirement: each pool must supply kink, slope1, slope2, reserve_factor.
- Transaction instructions remain USD-based (no automatic Web3/wei conversion).
"""

from dataclasses import dataclass
from typing import Dict, Union, Optional, Any
import math
import sys
import copy

from data.utils.felix_apy_calculator import fetch_felix_final_calculated_apy, update_pool_params_with_extra_supply

# -----------------------------
# Data class (requires model params)
# ----------------------------- 
@dataclass
class CronPoolData:
    protocol: str
    current_apy: float   # fraction (0.12 == 12%) as provided (normalized by parser)
    tvl: float
    utilization: float   # fraction (0..1)
    kink: float
    slope1: float
    slope2: float
    reserve_factor: float
    pool_address: str  # Changed from Optional to required
    token_price_usd: Optional[float] = None
    token_decimals: Optional[int] = None
    # Felix-specific parameters
    base_rate: Optional[float] = None
    multiplier: Optional[float] = None
    jump_multiplier: Optional[float] = None
    curve_steepness: Optional[float] = None
    adjustment_speed: Optional[float] = None
    target_utilization: Optional[float] = None
    initial_rate_at_target: Optional[float] = None
    min_rate_at_target: Optional[float] = None
    max_rate_at_target: Optional[float] = None
    pool_params: Optional[Dict[str, Any]] = None

    @property
    def total_borrow(self) -> float:
        return self.tvl * self.utilization

    @property
    def available_liquidity(self) -> float:
        return max(0.0, self.tvl - self.total_borrow)


# -----------------------------
# Helpers: normalization & validation
# -----------------------------
def _to_fraction(v: Union[str, float, int, None]) -> float:
    """Convert percent or fraction to fraction. None -> 0.0"""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        vv = float(v)
        return vv / 100.0 if vv > 1.0 else vv
    s = str(v).strip()
    if s.endswith('%'):
        s = s[:-1].strip()
    try:
        vv = float(s)
        return vv / 100.0 if vv > 1.0 else vv
    except Exception:
        raise ValueError(f"Expected numeric rate but got: {v!r}")


def _normalize_pool_key(k: str) -> str:
    k_l = k.strip().lower()
    if "hyperlend" in k_l or k_l.startswith("hypl"):
        return "HyperLend"
    if "hyperfi" in k_l or "hypurfi" in k_l:
        return "HyperFi"
    return k.strip()


def parse_cron_struct(cron_dict: Dict[str, Any]) -> Dict[str, CronPoolData]:
    """
    Accept only structured dict input. Pool addresses are used as keys.
    Requires per-pool fields: protocol, tvl, utilization, current_apy, kink, slope1, slope2, reserve_factor.
    Optional: token_price_usd, token_decimals
    Raises ValueError on missing / invalid inputs.
    """
    if not isinstance(cron_dict, dict):
        raise ValueError("cron_data must be a dict with pool entries")

    pools: Dict[str, CronPoolData] = {}
    protocol_to_address: Dict[str, str] = {}
    address_to_protocol: Dict[str, str] = {}
    
    # Process each pool entry (address is the key)
    for pool_address, payload in cron_dict.items():
        if not isinstance(payload, dict):
            raise ValueError(f"pool '{pool_address}' must be a dict with required fields")
            
        # Get protocol name
        protocol = payload.get("protocol")
        if not protocol:
            raise ValueError(f"{pool_address}: missing required 'protocol' field")
            
        protocol = _normalize_pool_key(protocol)
        protocol_to_address[protocol] = pool_address
        address_to_protocol[pool_address] = protocol

        # Required numeric fields
        try:
            tvl = float(payload["tvl"])
        except Exception:
            raise ValueError(f"{pool_address}: missing or invalid 'tvl'")

        util = _to_fraction(payload.get("utilization", payload.get("util", payload.get("utilisation", None))))
        apy = _to_fraction(payload.get("current_apy", payload.get("supply_apy", payload.get("current_apr", None))))

        # Handle Felix protocol differently
        if protocol == "Felix":
            # Map Felix parameters to the standard model parameters
            try:
                # For Felix, we'll use target_utilization as kink
                kink = float(payload.get("target_utilization", 0.9))
                
                # Map curve_steepness and adjustment_speed to slope parameters
                curve_steepness = float(payload.get("curve_steepness", 4.0))
                adjustment_speed = float(payload.get("adjustment_speed", 50.0))
                
                # Create equivalent slope parameters for Felix
                slope1 = float(payload.get("initial_rate_at_target", 0.04))
                slope2 = float(payload.get("max_rate_at_target", 2.0))
                
                # Get reserve factor
                reserve = float(payload.get("reserve_factor", 0.1))
                
                # Store Felix-specific parameters
                base_rate = float(payload.get("min_rate_at_target", 0.001))
                multiplier = adjustment_speed / 100.0  # Normalize to 0-1 range
                jump_multiplier = curve_steepness
                
            except Exception as e:
                raise ValueError(f"{pool_address}: error parsing Felix parameters: {str(e)}")
                
        else:
            # Standard HyperFi/HyperLend parameters
            missing_model = []
            try:
                kink = float(payload["kink"])
            except Exception:
                missing_model.append("kink")
                kink = None  # type: ignore
            try:
                slope1 = float(payload["slope1"])
            except Exception:
                missing_model.append("slope1")
                slope1 = None  # type: ignore
            try:
                slope2 = float(payload["slope2"])
            except Exception:
                missing_model.append("slope2")
                slope2 = None  # type: ignore
            try:
                reserve = float(payload["reserve_factor"])
            except Exception:
                missing_model.append("reserve_factor")
                reserve = None  # type: ignore
                
            # Default values for Felix-specific parameters
            base_rate = 0.01
            multiplier = 0.5
            jump_multiplier = 3.0

            if missing_model:
                raise ValueError(f"{pool_address}: missing required model params: {missing_model}")

        # We already have pool_address as the key
        token_price_usd = payload.get("token_price_usd")
        token_decimals = payload.get("token_decimals")
        if token_price_usd is not None:
            try:
                token_price_usd = float(token_price_usd)
            except Exception:
                token_price_usd = None
        if token_decimals is not None:
            try:
                token_decimals = int(token_decimals)
            except Exception:
                token_decimals = None

        # Create pool data with appropriate parameters based on protocol
        if protocol == "Felix":
            # For Felix, we store the entire `params` dictionary from the payload.
            felix_params = payload.get("params", {})
            # Include Felix-specific parameters
            pool = CronPoolData(
                protocol=protocol,
                current_apy=apy,
                tvl=tvl,
                utilization=util,
                kink=kink,
                slope1=slope1,
                slope2=slope2,
                reserve_factor=reserve,
                pool_address=pool_address,
                token_price_usd=token_price_usd,
                token_decimals=token_decimals,
                # Felix-specific parameters
                base_rate=base_rate,
                multiplier=multiplier,
                jump_multiplier=jump_multiplier,
                curve_steepness=float(payload.get("curve_steepness", 4.0)),
                adjustment_speed=float(payload.get("adjustment_speed", 50.0)),
                target_utilization=float(payload.get("target_utilization", 0.9)),
                initial_rate_at_target=float(payload.get("initial_rate_at_target", 0.04)),
                min_rate_at_target=float(payload.get("min_rate_at_target", 0.001)),
                max_rate_at_target=float(payload.get("max_rate_at_target", 2.0)),
                pool_params=felix_params
            )
        else:
            # Standard pool parameters
            pool = CronPoolData(
                protocol=protocol,
                current_apy=apy,
                tvl=tvl,
                utilization=util,
                kink=kink,
                slope1=slope1,
                slope2=slope2,
                reserve_factor=reserve,
                pool_address=pool_address,
                token_price_usd=token_price_usd,
                token_decimals=token_decimals
            )
        # Use pool_address as the key
        pools[pool_address] = pool

    # Require both canonical pools
    hyperlend_protocol = "HyperLend"
    hyperfi_protocol = "HyperFi"
    
    hyperlend_found = False
    hyperfi_found = False
    
    for addr, pool in pools.items():
        if pool.protocol == hyperlend_protocol:
            hyperlend_found = True
        elif pool.protocol == hyperfi_protocol:
            hyperfi_found = True
    
    if not hyperlend_found or not hyperfi_found:
        raise ValueError(f"cron_data must include both '{hyperlend_protocol}' and '{hyperfi_protocol}' protocols")

    # Basic validation of values
    for addr, p in pools.items():
        if p.tvl < 0:
            raise ValueError(f"{p.protocol} ({addr}).tvl must be >= 0")
        if not (0.0 <= p.utilization < 1.0):
            raise ValueError(f"{p.protocol} ({addr}).utilization must be in [0, 1). Got {p.utilization}")
        if p.current_apy < 0:
            raise ValueError(f"{p.protocol} ({addr}).current_apy must be >= 0")
        if not (0.0 < p.kink < 1.0):
            raise ValueError(f"{p.protocol} ({addr}).kink must be in (0,1). Got {p.kink}")
        if p.slope1 < 0 or p.slope2 < 0 or not (0.0 <= p.reserve_factor < 1.0):
            raise ValueError(f"{p.protocol} ({addr}): invalid slope/reserve params (slope1>=0, slope2>=0, reserve_factor in [0,1))")
            
    # Create a custom dictionary with protocol mappings
    result_pools = dict(pools)
    result_pools["protocol_to_address"] = protocol_to_address
    result_pools["address_to_protocol"] = address_to_protocol
    
    return result_pools

    # This line is now handled above


# -----------------------------
# APY calculation model
# -----------------------------


def calculate_hyperfi_hyperlend_future_apy_with_formula(utilization: float, pool_data: Dict) -> float:
    """
    Calculate supply APY for HyperFi or HyperLend using kinked interest rate model
    
    Args:
        utilization: Pool utilization as a fraction (0.0-1.0)
        pool_data: Dictionary containing pool parameters (kink, slope1, slope2, reserve_factor)
        
    Returns:
        Supply APY as a fraction (0.05 = 5%)
    """
    # Clamp utilization
    u = max(0.01, min(0.99, utilization))
    
    # Extract parameters from pool data
    kink = pool_data.get("kink", 0.8)
    slope1 = pool_data.get("slope1", 0.1)
    slope2 = pool_data.get("slope2", 0.5)
    reserve_factor = pool_data.get("reserve_factor", 0.2)

    print('kink ', kink)
    print('slope1 ', slope1)
    print('slope2 ', slope2)
    print('reserve_factor ', reserve_factor)
    
    # Calculate borrow APR using kinked interest model
    if u <= kink:
        borrow_apr = (u / kink) * slope1
    else:
        borrow_apr = slope1 + ((u - kink) / (1 - kink)) * slope2

    # Calculate supply APR and convert to APY
    supply_apr = borrow_apr * u * (1 - reserve_factor)
    supply_apy = math.exp(supply_apr) - 1

    return supply_apy*100


def calculate_new_utilization(current_tvl: float, current_borrow: float, tvl_change: float) -> float:
    """
    Calculate new utilization after TVL change
    
    Args:
        current_tvl: Current total value locked in the pool
        current_borrow: Current borrowed amount from the pool
        tvl_change: Amount to add (positive) or remove (negative) from TVL
        
    Returns:
        New utilization rate as a fraction (0.0-1.0)
    """
    new_tvl = current_tvl + tvl_change
    if new_tvl <= 0:
        return 0.99  # Max utilization if TVL goes to zero

    new_utilization = current_borrow / new_tvl
    return max(0.01, min(0.99, new_utilization))

def find_most_profitable_reallocation(pool_data: Dict, position: Dict) -> Dict:
    """
    Checks every possible reallocation from a pool with a balance to a pool with a higher
    current APY, and recommends the single move that results in the highest destination APY.
    """
    # if not any(balance > 0 for balance in position.values()):
    #     return {"action": "hold", "reason": "No funds to optimize."}

    # Find the current best pool by APY
    current_best_pool = max([p for p in pool_data.values() if isinstance(p, CronPoolData)], key=lambda p: p.current_apy, default=None)
    if not current_best_pool:
        return {"action": "hold", "reason": "Could not determine the best pool from the provided data."}
    current_best_pool_name = current_best_pool.protocol if current_best_pool else "None"
    current_best_pool_address = current_best_pool.pool_address if current_best_pool else "None"

    # Check if all funds are already in the best pool.
    is_consolidated = True
    for addr, balance in position.items():
        if balance > 0 and addr != current_best_pool.pool_address:
            is_consolidated = False
            break
    if is_consolidated:
        return {"action": "hold", "reason": "All funds are already in the best pool.", "current_best_pool": current_best_pool_name, "current_best_pool_address": current_best_pool_address}

    best_move = {"action": "hold", "reason": "No profitable move found.", "new_apy_to": -1, "current_best_pool": current_best_pool_name, "current_best_pool_address": current_best_pool_address}

    # Iterate through each pool that has funds as a potential source
    for from_addr, from_pool in pool_data.items():
        if not isinstance(from_pool, CronPoolData) or position.get(from_addr, 0) <= 0:
            continue

        # Iterate through all other pools as a potential destination
        for to_addr, to_pool in pool_data.items():
            if from_addr == to_addr or not isinstance(to_pool, CronPoolData):
                continue

            # Only consider moves to pools with a higher current APY
            if to_pool.current_apy > from_pool.current_apy:
                amount_to_move = position[from_addr]

                # Calculate the new APY of the destination pool
                new_apy_to = estimate_supply_apy_for_util(to_pool, tvl_change=amount_to_move)

                # If this move results in a higher destination APY than any move found so far, it's the new best move
                if new_apy_to > best_move["new_apy_to"]:
                    best_move = {
                        "action": "reallocate",
                        "from_protocol": from_pool,
                        "from_address": from_addr,
                        "to_protocol": to_pool,
                        "to_address": to_addr,
                        "amount": amount_to_move,
                        "reason": f"Moving funds from {from_pool.protocol} to {to_pool.protocol} offers the highest resulting APY.",
                        "current_apy_from": from_pool.current_apy * 100,
                        "new_apy_to": new_apy_to * 100,
                        "current_best_pool": current_best_pool_name,
                        "current_best_pool_address": current_best_pool_address
                    }

    return best_move

def find_simple_reallocation(pool_data: Dict, position: Dict) -> Dict:
    """
    Finds the highest and lowest APY pools and checks if moving funds from lowest to highest is profitable.
    """
    if not any(balance > 0 for balance in position.values()):
        return {"action": "hold", "reason": "No funds to optimize."}

    # Find the highest APY pool
    highest_apy_pool = max([p for p in pool_data.values() if isinstance(p, CronPoolData)], key=lambda p: p.current_apy, default=None)

    # Find the lowest APY pool that has a balance
    lowest_apy_pool = min([p for addr, p in pool_data.items() if isinstance(p, CronPoolData) and position.get(addr, 0) > 0], key=lambda p: p.current_apy, default=None)

    if not highest_apy_pool or not lowest_apy_pool or highest_apy_pool.pool_address == lowest_apy_pool.pool_address:
        return {"action": "hold", "reason": "No profitable move available."}

    amount_to_move = position[lowest_apy_pool.pool_address]

    # Calculate the new APY of the highest pool if it receives the funds
    new_apy_for_highest_pool = estimate_supply_apy_for_util(highest_apy_pool, tvl_change=amount_to_move)

    # Check if the new APY of the destination is better than the current APY of the source
    if new_apy_for_highest_pool > lowest_apy_pool.current_apy:
        return {
            "action": "reallocate",
            "from_protocol": lowest_apy_pool.protocol,
            "from_address": lowest_apy_pool.pool_address,
            "to_protocol": highest_apy_pool.protocol,
            "to_address": highest_apy_pool.pool_address,
            "amount": amount_to_move,
            "reason": f"Moving funds from {lowest_apy_pool.protocol} to {highest_apy_pool.protocol} is profitable.",
            "current_apy_from": lowest_apy_pool.current_apy * 100,
            "new_apy_to": new_apy_for_highest_pool * 100
        }
    else:
        return {"action": "hold", "reason": "Move is not profitable."}


def evaluate_move_recommendation(pool_data: Dict, position: Dict) -> Dict:
    """
    Evaluate if moving funds between pools would improve yield
    
    Args:
        pool_data: Dictionary with pool information including TVL, borrowed amounts, etc.
        position: Current position in each pool
        
    Returns:
        Dictionary with recommendation details
    """
    # Extract pool data for each protocol
    protocols = {}
    for addr, pool in pool_data.items():
        if isinstance(pool, CronPoolData):
            protocols[pool.protocol] = {
                "address": addr,
                "tvl": pool.tvl,
                "borrowed": pool.total_borrow,
                "utilization": pool.utilization,
                "current_apy": estimate_supply_apy_for_util(pool, pool.utilization),
                "pool_params": {
                    "kink": pool.kink,
                    "slope1": pool.slope1,
                    "slope2": pool.slope2,
                    "reserve_factor": pool.reserve_factor,
                    "base_rate": getattr(pool, "base_rate", 0.01),
                    "multiplier": getattr(pool, "multiplier", 0.5),
                    "jump_multiplier": getattr(pool, "jump_multiplier", 3.0)
                }
            }
    
    # Find highest and lowest yielding pools
    sorted_protocols = sorted(
        [(name, data["current_apy"]) for name, data in protocols.items()],
        key=lambda x: x[1],
        reverse=True
    )
    
    if len(sorted_protocols) < 2:
        return {"action": "hold", "reason": "Not enough pools to compare"}
    
    higher_pool = sorted_protocols[0][0]
    lower_pool = sorted_protocols[-1][0]
    
    # Check if we have funds in the lower yielding pool
    lower_addr = protocols[lower_pool]["address"]
    amount_to_move = position.get(lower_addr, 0)
    
    if amount_to_move <= 0:
        return {
            "action": "hold",
            "amount": 0,
            "from": lower_pool,
            "to": higher_pool,
            "reason": f"No funds in {lower_pool} to move"
        }
    
    # Calculate new utilization after moving all funds
    higher_addr = protocols[higher_pool]["address"]
    
    new_higher_util = calculate_new_utilization(
        protocols[higher_pool]["tvl"],
        protocols[higher_pool]["borrowed"],
        amount_to_move
    )
    
    new_lower_util = calculate_new_utilization(
        protocols[lower_pool]["tvl"],
        protocols[lower_pool]["borrowed"],
        -amount_to_move
    )
    
    # Calculate new APYs using protocol-specific parameters
    higher_pool_obj = pool_data[protocols[higher_pool]["address"]]
    lower_pool_obj = pool_data[protocols[lower_pool]["address"]]
    
    # Use the estimate_supply_apy_for_util function which handles protocol differences
    new_higher_apy = estimate_supply_apy_for_util(higher_pool_obj, tvl_change=amount_to_move)
    new_lower_apy = estimate_supply_apy_for_util(lower_pool_obj, tvl_change=-amount_to_move)
    
    # Calculate weighted APYs
    total_balance = sum(position.values())
    if total_balance <= 0:
        return {"action": "hold", "reason": "No funds to move"}
    
    current_weighted_apy = 0
    for addr, balance in position.items():
        if addr in pool_data and isinstance(pool_data[addr], CronPoolData):
            protocol = pool_data[addr].protocol
            current_apy = protocols[protocol]["current_apy"]
            current_weighted_apy += (current_apy * balance)
    
    current_weighted_apy /= total_balance
    
    # After move, all funds from lower pool go to higher pool
    new_position = dict(position)
    new_position[lower_addr] = 0
    new_position[higher_addr] = position.get(higher_addr, 0) + amount_to_move
    
    new_weighted_apy = 0
    for addr, balance in new_position.items():
        if balance <= 0 or addr not in pool_data or not isinstance(pool_data[addr], CronPoolData):
            continue
            
        protocol = pool_data[addr].protocol
        if addr == higher_addr:
            apy = new_higher_apy
        elif addr == lower_addr:
            apy = new_lower_apy
        else:
            apy = protocols[protocol]["current_apy"]
            
        new_weighted_apy += (apy * balance)
    
    new_weighted_apy /= total_balance
    
    # Calculate improvement in basis points
    improvement_bps = (new_weighted_apy - current_weighted_apy) * 10000
    
    # Check if the move would be profitable
    if new_higher_apy >= new_lower_apy and improvement_bps > 0:
        return {
            "action": "move_all",
            "amount": amount_to_move,
            "from": lower_pool,
            "from_address": lower_addr,
            "to": higher_pool,
            "to_address": higher_addr,
            "reason": f"{higher_pool} remains higher after 100% move",
            "current_weighted_apy": current_weighted_apy * 100,
            "new_weighted_apy": new_weighted_apy * 100,
            "improvement_bps": improvement_bps,
            "new_higher_apy": new_higher_apy * 100,
            "new_lower_apy": new_lower_apy * 100
        }
    else:
        return {
            "action": "hold",
            "amount": 0,
            "from": lower_pool,
            "to": higher_pool,
            "reason": f"Moving funds would not improve yield (crossover detected)",
            "current_weighted_apy": current_weighted_apy * 100,
            "new_weighted_apy": new_weighted_apy * 100,
            "improvement_bps": improvement_bps,
            "new_higher_apy": new_higher_apy * 100,
            "new_lower_apy": new_lower_apy * 100
        }

def estimate_supply_apy_for_util(pool: CronPoolData, tvl_change: float = 0.0) -> float:
    """
    Compute supply APY using pool's kinked borrow model (reads model params from CronPoolData).
    Returns supply APY (fraction).
    """
    # Check if this is a Felix pool
    if hasattr(pool, "protocol") and pool.protocol == "Felix":
        # For Felix, we need to simulate the change in supply by creating a new set of pool parameters.
        # The `update_pool_params_with_extra_supply` function handles this.
        felix_pool_address = "0xD4a426F010986dCad727e8dd6eed44cA4A9b7483"#pool.pool_address
        # The `pool_params` are nested inside the CronPoolData object for Felix
        felix_params = pool.pool_params 

        if tvl_change != 0.0:
            # If there is a hypothetical change in TVL, calculate the new APY based on that.
            updated_params = update_pool_params_with_extra_supply(felix_params, tvl_change)
            # The Felix calculator returns a percentage, so we divide by 100.
            apy = fetch_felix_final_calculated_apy(felix_pool_address, updated_params) 
        else:
            # If there is no change, calculate the APY with the current parameters.
            # The Felix calculator returns a percentage, so we divide by 100.
            apy = fetch_felix_final_calculated_apy(felix_pool_address, felix_params) 
        
        print(f"calculated final felix apy:  {apy}   tvl change: {tvl_change}")
        # The Felix calculator returns a percentage, so we divide by 100.
        return apy / 100.0

    else:
        # For HyperFi/HyperLend, we calculate the new utilization based on the TVL change.
        util = calculate_new_utilization(pool.tvl, pool.total_borrow, tvl_change)
        params = {
            "kink": pool.kink,
            "slope1": pool.slope1,
            "slope2": pool.slope2,
            "reserve_factor": pool.reserve_factor
        }
        apy = calculate_hyperfi_hyperlend_future_apy_with_formula(util, params)
        print(f"calculated final {pool.protocol} apy:  {apy}   tvl change: {tvl_change}")
        # The calculator returns a percentage, so we divide by 100.
        return apy / 100.0


# -----------------------------
# Core optimizer (model-consistent baseline)
# -----------------------------
class CombinedOptimizer:
    def __init__(self, pools: Dict[str, CronPoolData], current_position: Dict[str, float], min_gain_bps: float = 10):
        # pools assumed normalized with pool_address as keys
        self.pools = pools
        self.position = {k: float(v or 0.0) for k, v in current_position.items()}
        self.min_gain_bps = float(min_gain_bps)
        # topology / safety params
        self.min_safe_util = 0.805
        self.max_safe_util = 0.87
        self.max_spread_bps = 100
        
        # Find protocol addresses
        self.protocol_addresses = {}
        self.address_to_protocol = {}
        
        for addr, pool in self.pools.items():
            if isinstance(pool, CronPoolData):
                protocol = pool.protocol
                self.protocol_addresses[protocol] = addr
                self.address_to_protocol[addr] = protocol
        
        # Ensure we have at least HyperLend and HyperFi
        self.hyperlend_address = self.protocol_addresses.get("HyperLend")
        self.hyperfi_address = self.protocol_addresses.get("HyperFi")
        
        if not self.hyperlend_address or not self.hyperfi_address:
            raise ValueError("Could not find HyperLend and HyperFi pools in the provided data")

    def _observed_current_weighted_apy(self) -> float:
        """Weighted APY based on user-supplied current_apy values. For transparency only."""
        total = sum(self.position.values())
        if total <= 0:
            return 0.0
        weighted = 0.0
        for addr, bal in self.position.items():
            if bal <= 0 or addr not in self.pools:
                continue
            pool = self.pools[addr]
            weighted += pool.current_apy * bal
        return weighted / total

    def _modeled_current_weighted_apy(self) -> float:
        """Weighted APY computed by the same model at each pool's CURRENT utilization.
           THIS is used for decision-making (apples-to-apples)."""
        total = sum(self.position.values())
        if total <= 0:
            return 0.0
        weighted = 0.0
        for addr, bal in self.position.items():
            if bal <= 0 or addr not in self.pools:
                continue
            pool = self.pools[addr]
            modeled_apy = estimate_supply_apy_for_util(pool, pool.utilization)
            weighted += modeled_apy * bal
        return weighted / total

    def find_optimal_amount_adaptive(self, safe_max, score_function):
        # Stage 1: coarse
        coarse = []
        for i in range(11):
            a = safe_max * i / 10.0
            coarse.append((a, score_function(a)))
        coarse.sort(key=lambda x: x[1], reverse=True)
        top = coarse[:3]

        # Stage 2: fine
        fine = []
        for base, _ in top:
            span = safe_max * 0.1
            start = max(0.0, base - span)
            end = min(safe_max, base + span)
            for j in range(21):
                a = start + (end - start) * j / 20.0
                fine.append((a, score_function(a)))

        seen = {}
        for a, s in fine:
            k = round(a, 2)
            if k not in seen or s > seen[k]:
                seen[k] = s
        fine_list = sorted(((a, s) for a, s in seen.items()), key=lambda x: x[1], reverse=True)
        best_fine = fine_list[0] if fine_list else (0.0, -1e9)

        # Stage 3: ultra-fine
        base_amount = best_fine[0]
        span = safe_max * 0.02
        start = max(0.0, base_amount - span)
        end = min(safe_max, base_amount + span)
        ultra = []
        for k in range(41):
            a = start + (end - start) * k / 40.0
            ultra.append((a, score_function(a)))
        ultra.sort(key=lambda x: x[1], reverse=True)
        winner = ultra[0] if ultra else best_fine
        return winner[0], winner[1]

    def _classify_scenario(self) -> str:
        hl_pool = self.pools[self.hyperlend_address]
        hf_pool = self.pools[self.hyperfi_address]
        hl_util = hl_pool.utilization
        hf_util = hf_pool.utilization
        hl_kink = hl_pool.kink
        hf_kink = hf_pool.kink

        if 0.78 <= hl_util <= 0.82 and 0.78 <= hf_util <= 0.82:
            return "edge_case_near_kink"
        if hl_util >= hl_kink and hf_util >= hf_kink:
            return "both_above_kink"
        if hl_util < hl_kink and hf_util < hf_kink:
            return "both_below_kink"
        return "mixed"

    def calculate_move_all_result(self, from_address: str, to_address: str) -> Dict[str, Any]:
        amount = self.position.get(from_address, 0.0)
        if amount <= 0:
            return {"error": "No funds to move"}
        from_pool = self.pools[from_address]
        to_pool = self.pools[to_address]

        new_tvl_from = max(1e-9, from_pool.tvl - amount)
        new_tvl_to = to_pool.tvl + amount

        new_util_from = from_pool.total_borrow / new_tvl_from
        new_util_to = to_pool.total_borrow / new_tvl_to if new_tvl_to > 0 else 0.0

        new_apy_from = estimate_supply_apy_for_util(from_pool, new_util_from)
        new_apy_to = estimate_supply_apy_for_util(to_pool, new_util_to)

        total_balance = sum(self.position.values())
        modeled_current_weighted_apy = self._modeled_current_weighted_apy()
        observed_current_weighted_apy = self._observed_current_weighted_apy()

        new_weighted_apy = new_apy_to  # move_all -> all funds in to_pool (model APY)
        gain_bps = (new_weighted_apy - modeled_current_weighted_apy) * 10000.0

        return {
            "action": "move_all",
            "from": from_address,
            "to": to_address,
            "from_protocol": from_pool.protocol,
            "to_protocol": to_pool.protocol,
            "amount": amount,
            "new_util_from": new_util_from,
            "new_util_to": new_util_to,
            "new_apy_from": new_apy_from,
            "new_apy_to": new_apy_to,
            "observed_current_weighted_apy": observed_current_weighted_apy,
            "modeled_current_weighted_apy": modeled_current_weighted_apy,
            "new_weighted_apy": new_weighted_apy,
            "gain_bps": gain_bps,
            "profitable": gain_bps > self.min_gain_bps
        }

    def find_equilibrium_rebalance(self) -> Optional[Dict[str, Any]]:
        best_move = None
        best_score = -float('inf')
        total_balance = sum(self.position.values())
        if total_balance <= 0:
            return None

        modeled_current_weighted_apy = self._modeled_current_weighted_apy()
        observed_current_weighted_apy = self._observed_current_weighted_apy()

        for from_address in list(self.position.keys()):
            if self.position[from_address] <= 0:
                continue
            for to_address in self.pools.keys():
                if from_address == to_address:
                    continue

                max_amount = self.position[from_address]
                from_pool = self.pools[from_address]
                to_pool = self.pools[to_address]

                # safe max withdraw
                max_withdraw_allowed = from_pool.tvl - (from_pool.total_borrow / self.max_safe_util) if self.max_safe_util > 0 else 0.0
                safe_max = min(max_amount, max(0.0, max_withdraw_allowed))
                if safe_max <= 0.0:
                    continue

                def score_function(amount: float) -> float:
                    if amount <= 0:
                        return 0.0
                    new_tvl_from = from_pool.tvl - amount
                    new_tvl_to = to_pool.tvl + amount
                    new_util_from = from_pool.total_borrow / new_tvl_from if new_tvl_from > 0 else 1.0
                    new_util_to = to_pool.total_borrow / new_tvl_to if new_tvl_to > 0 else 0.0

                    # ensure both utils within safe band
                    if not (self.min_safe_util <= new_util_from <= self.max_safe_util and
                            self.min_safe_util <= new_util_to <= self.max_safe_util):
                        return 0.0

                    new_apy_from = estimate_supply_apy_for_util(from_pool, new_util_from)
                    new_apy_to = estimate_supply_apy_for_util(to_pool, new_util_to)

                    apr_spread = abs(new_apy_from - new_apy_to)
                    current_spread = abs(estimate_supply_apy_for_util(from_pool, from_pool.utilization) - estimate_supply_apy_for_util(to_pool, to_pool.utilization))
                    reduces_spread = apr_spread < current_spread
                    spread_within_limit = apr_spread <= self.max_spread_bps / 10000.0
                    if not (spread_within_limit or reduces_spread):
                        return 0.0

                    new_balance_from = max(0.0, self.position.get(from_address, 0.0) - amount)
                    new_balance_to = self.position.get(to_address, 0.0) + amount
                    new_weighted_apy = (new_balance_from * new_apy_from + new_balance_to * new_apy_to) / total_balance
                    gain_bps = (new_weighted_apy - modeled_current_weighted_apy) * 10000.0

                    optimal_util = 0.825
                    util_score = 1.0 - (abs(new_util_from - optimal_util) + abs(new_util_to - optimal_util)) / 0.2
                    spread_score = 1.0 - (apr_spread / (self.max_spread_bps / 10000.0))
                    stability_score = util_score * 0.6 + spread_score * 0.4
                    yield_score = gain_bps / 100.0
                    combined_score = stability_score * 0.3 + yield_score * 0.7
                    return combined_score

                optimal_amount, optimal_score = self.find_optimal_amount_adaptive(safe_max, score_function)
                if optimal_score > best_score:
                    # compute final metadata for best
                    new_tvl_from = from_pool.tvl - optimal_amount
                    new_tvl_to = to_pool.tvl + optimal_amount
                    new_util_from = from_pool.total_borrow / new_tvl_from if new_tvl_from > 0 else 1.0
                    new_util_to = to_pool.total_borrow / new_tvl_to if new_tvl_to > 0 else 0.0
                    new_apy_from = estimate_supply_apy_for_util(from_pool, new_util_from)
                    new_apy_to = estimate_supply_apy_for_util(to_pool, new_util_to)
                    new_balance_from = max(0.0, self.position.get(from_address, 0.0) - optimal_amount)
                    new_balance_to = self.position.get(to_address, 0.0) + optimal_amount
                    new_weighted_apy = (new_balance_from * new_apy_from + new_balance_to * new_apy_to) / total_balance
                    gain_bps = (new_weighted_apy - modeled_current_weighted_apy) * 10000.0

                    optimal_util = 0.825
                    util_score = 1.0 - (abs(new_util_from - optimal_util) + abs(new_util_to - optimal_util)) / 0.2
                    apr_spread = abs(new_apy_from - new_apy_to)
                    spread_score = 1.0 - (apr_spread / (self.max_spread_bps / 10000.0))
                    stability_score = util_score * 0.6 + spread_score * 0.4

                    best_score = optimal_score
                    best_move = {
                        "action": "rebalance",
                        "from": from_address,
                        "to": to_address,
                        "from_protocol": from_pool.protocol,
                        "to_protocol": to_pool.protocol,
                        "amount": optimal_amount,
                        "new_util_from": new_util_from,
                        "new_util_to": new_util_to,
                        "new_apy_from": new_apy_from,
                        "new_apy_to": new_apy_to,
                        "observed_current_weighted_apy": observed_current_weighted_apy,
                        "modeled_current_weighted_apy": modeled_current_weighted_apy,
                        "new_weighted_apy": new_weighted_apy,
                        "gain_bps": gain_bps,
                        "stability_score": stability_score,
                        "profitable": gain_bps > self.min_gain_bps
                    }

        return best_move

    def optimize(self) -> Dict[str, Any]:
        # Use the new logic to find the single most profitable reallocation
        recommendation = find_most_profitable_reallocation(self.pools, self.position)
        
            
        # This function returns a single move or a hold action
        if recommendation.get("action") == "reallocate":
            return {
                "action": "reallocate",
                "from_protocol": recommendation.get("from_protocol"),
                "from_address": recommendation.get("from_address"),
                "to_protocol": recommendation.get("to_protocol"),
                "to_address": recommendation.get("to_address"),
                "amount": recommendation.get("amount"),
                "reason": recommendation.get("reason"),
                "current_weighted_apy": recommendation.get("current_weighted_apy", 0) / 100,
                "new_weighted_apy": recommendation.get("new_weighted_apy", 0) / 100,
                "gain_bps": recommendation.get("improvement_bps", 0),
                "profitable": recommendation.get("improvement_bps", 0) > self.min_gain_bps
            }
        
        # If no profitable move found, return hold action
        return {
            "action": "hold",
            "reason": recommendation.get("reason", "No profitable moves found")
        }
        
    def optimize_legacy(self) -> Dict[str, Any]:
        """Legacy optimization method using the old approach"""
        scenario = self._classify_scenario()

        if scenario == "both_above_kink":
            result = self.find_equilibrium_rebalance()
            if result and result.get("profitable"):
                return result
            return {"action": "hold", "reason": "Both above kink, no profitable rebalance"}

        if scenario == "mixed":
            hl_pool = self.pools[self.hyperlend_address]
            if hl_pool.utilization > hl_pool.kink:
                move_result = self.calculate_move_all_result(self.hyperfi_address, self.hyperlend_address)
                if move_result.get("new_util_to", 0) > hl_pool.kink and move_result.get("profitable"):
                    return move_result
            else:
                move_result = self.calculate_move_all_result(self.hyperlend_address, self.hyperfi_address)
                if move_result.get("new_util_to", 0) > self.pools[self.hyperfi_address].kink and move_result.get("profitable"):
                    return move_result

            reb = self.find_equilibrium_rebalance()
            if reb and reb.get("profitable"):
                return reb

        if scenario in ("both_below_kink", "edge_case_near_kink"):
            reb = self.find_equilibrium_rebalance()
            if reb and reb.get("profitable"):
                return reb

        return {"action": "hold", "reason": "No profitable moves found"}


# -----------------------------
# External function (transaction-ready, no Web3 conversions)
# -----------------------------
def optimize_pools_structured(cron_data: Dict[str, Any], current_position: Dict[str, float], min_gain_bps: float = 10.0) -> Dict[str, Any]:
    try:
        # Parse the cron_data with pool addresses as keys
        pools = parse_cron_struct(cron_data)
        
        # Get protocol to address mappings from the pools dictionary
        try:
            protocol_to_address = pools["protocol_to_address"]
            address_to_protocol = pools["address_to_protocol"]
            # Remove the mappings from the pools dictionary to avoid issues with CombinedOptimizer
            pools_copy = {k: v for k, v in pools.items() if k not in ["protocol_to_address", "address_to_protocol"]}
        except (KeyError, TypeError):
            # Fallback in case the mappings weren't stored in the pools dictionary
            protocol_to_address = {}
            address_to_protocol = {}
            pools_copy = dict(pools)
            for addr, pool in pools_copy.items():
                if isinstance(pool, CronPoolData):
                    protocol_to_address[pool.protocol] = addr
                    address_to_protocol[addr] = pool.protocol

        # Use the direct evaluate_move_recommendation function
        # This handles all protocol types including Felix
        recommendation = evaluate_move_recommendation(pools_copy, current_position)
        
        # Format the recommendation for compatibility with the rest of the system
        if recommendation.get("action") == "move_all":
            result = {
                "action": "move_all",
                "from": recommendation.get("from_address"),
                "to": recommendation.get("to_address"),
                "from_protocol": recommendation.get("from"),
                "to_protocol": recommendation.get("to"),
                "amount": recommendation.get("amount"),
                "new_util_from": recommendation.get("new_lower_apy", 0) / 100,  # Convert from percentage
                "new_util_to": recommendation.get("new_higher_apy", 0) / 100,  # Convert from percentage
                "observed_current_weighted_apy": recommendation.get("current_weighted_apy", 0) / 100,
                "modeled_current_weighted_apy": recommendation.get("current_weighted_apy", 0) / 100,
                "new_weighted_apy": recommendation.get("new_weighted_apy", 0) / 100,
                "gain_bps": recommendation.get("improvement_bps", 0),
                "profitable": recommendation.get("improvement_bps", 0) > min_gain_bps
            }
        else:
            result = {
                "action": "hold",
                "reason": recommendation.get("reason", "No profitable moves found")
            }

        optimization_details = {
            "current_position": current_position,
            "optimization_result": result
        }
        
        # Add withdrawal and allocation details if needed
        if result.get("action") in ("rebalance", "move_all"):
            from_address = result.get("from")
            to_address = result.get("to")
            from_protocol = result.get("from_protocol")
            to_protocol = result.get("to_protocol")
            amount_usd = result.get("amount")

            withdrawal = {
                "pool_address": from_address,
                "protocol": from_protocol,
                "amount_usd": amount_usd
            }
            
            allocations = [{
                "pool_address": to_address,
                "protocol": to_protocol,
                "amount_usd": amount_usd
            }]

            # Try to add token unit information if available
            try:
                from_pool = pools_copy.get(from_address)
                if from_pool and from_pool.token_price_usd and from_pool.token_decimals:
                    token_amount = float(amount_usd) / float(from_pool.token_price_usd)
                    token_units = token_amount * (10 ** from_pool.token_decimals)
                    withdrawal["amount_token_units"] = str(token_units)
            except Exception:
                pass

            try:
                to_pool = pools_copy.get(to_address)
                if to_pool and to_pool.token_price_usd and to_pool.token_decimals:
                    token_amount = float(amount_usd) / float(to_pool.token_price_usd)
                    token_units = token_amount * (10 ** to_pool.token_decimals)
                    allocations[0]["amount_token_units"] = str(token_units)
            except Exception:
                pass

            optimization_details["withdrawal"] = withdrawal
            optimization_details["allocations"] = allocations
        
        return optimization_details
        
    except Exception as e:
        # Provide a graceful fallback with error information
        return {
            "current_position": current_position,
            "optimization_result": {
                "action": "hold",
                "reason": f"Optimization error: {str(e)}"
            },
            "error": str(e)
        }
        return {
            "action": result.get("action"),
            "transaction_instructions": transaction_instructions,
            "optimization_details": optimization_details,
            "profitable": result.get("profitable", False),
            "gain_bps": result.get("gain_bps", 0),
            "from_protocol": from_protocol,
            "to_protocol": to_protocol,
            "from_address": from_address,
            "to_address": to_address,
            "amount": amount_usd
        }
    else:
        return {
            "action": "hold",
            "reason": result.get("reason", "No profitable moves found"),
            "transaction_instructions": None,
            "optimization_details": optimization_details
        }


# -----------------------------
# Pretty print (simple)
# -----------------------------
def print_result(res: Dict[str, Any]):
    print("\n=== RESULT ===")
    if not res:
        print("No result")
        return
    if "error" in res:
        print("Error:", res["error"])
        return

    if res.get("action") == "hold":
        print("Action: HOLD --", res.get("reason"))
        return

    if res.get("action") in ("rebalance", "move_all"):
        from_protocol = res.get("from_protocol") or res.get("from")
        to_protocol = res.get("to_protocol") or res.get("to")
        amount = res.get("amount")

        if res.get("action") == "move_all":
            print(f"ACTION: MOVE ALL ${amount:,.2f} from {from_protocol} -> {to_protocol}")
        else:
            print(f"ACTION: REBALANCE ${amount:,.2f} from {from_protocol} -> {to_protocol}")

        if res.get("transaction_instructions"):
            print("\n=== TRANSACTION INSTRUCTIONS ===")
            print(f"Scenario Type: {res['transaction_instructions']['scenario_type']}")

            withdrawals = res['transaction_instructions'].get('withdrawals', [])
            if withdrawals:
                print("\nWithdrawals:")
                for i, w in enumerate(withdrawals):
                    amt_info = f"${w['amount_usd']:.6f}"
                    token_units = w.get("amount_token_units")
                    if token_units:
                        amt_info += f" ({int(token_units):,} token units)"
                    addr = w.get("pool_address") or "<no address>"
                    print(f"  {i+1}. {amt_info} from {w['protocol']} (Pool: {addr})")

            allocations = res['transaction_instructions'].get('allocations', [])
            if allocations:
                print("\nAllocations:")
                for i, a in enumerate(allocations):
                    amt_info = f"${a['amount_usd']:.6f}"
                    token_units = a.get("amount_token_units")
                    if token_units:
                        amt_info += f" ({int(token_units):,} token units)"
                    addr = a.get("pool_address") or "<no address>"
                    print(f"  {i+1}. {amt_info} to {a['protocol']} (Pool: {addr})")

        if res.get("optimization_details") and res["optimization_details"].get("optimization_result"):
            opt_result = res["optimization_details"]["optimization_result"]
            print("\n=== OPTIMIZATION DETAILS ===")
            if "new_util_from" in opt_result and "new_util_to" in opt_result:
                print(f"New utils: {opt_result['new_util_from']:.4f} (from), {opt_result['new_util_to']:.4f} (to)")
            if "gain_bps" in opt_result:
                print(f"Gain: {opt_result['gain_bps']:.2f} bps | Stability: {opt_result.get('stability_score', 0):.3f}")
            if "observed_current_weighted_apy" in opt_result:
                print(f"Observed current APY (from provided values): {opt_result['observed_current_weighted_apy']*100:.3f}%")
            if "modeled_current_weighted_apy" in opt_result:
                print(f"Modeled current APY (from model): {opt_result['modeled_current_weighted_apy']*100:.3f}%")
            if "new_weighted_apy" in opt_result:
                print(f"New weighted APY (modeled): {opt_result['new_weighted_apy']*100:.3f}%")

    print("================\n")

