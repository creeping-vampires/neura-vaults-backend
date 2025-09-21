from crewai.tools import tool
import requests
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
from data.models import RebalancingTrade
from web3 import Web3
from decimal import Decimal

logger = logging.getLogger(__name__)

@tool("Execute Yield Allocation")
def execute_yield_allocation(allocation_strategy_json: str) -> str:
    """
    Execute a yield allocation strategy supporting both idle asset deployment and rebalancing.
    
    Args:
        allocation_strategy_json (str): JSON string with allocation strategy in format:
            {
                "scenario_type": "IDLE_DEPLOYMENT" | "REBALANCING",
                "withdrawals": [{"pool_address": "0x...", "amount": "1000000000000000000", "protocol": "Aave"}],
                "allocations": [{"pool_address": "0x...", "amount": "1000000000000000000", "protocol": "HypurrFi"}]
            }
    
    Returns:
        str: JSON string containing execution results with real transaction hashes
    """
    try:
        from data.agent_utils import execute_pool_investment, execute_pool_withdrawal
        
        # Parse allocation strategy
        allocation_strategy = json.loads(allocation_strategy_json)
        scenario_type = allocation_strategy.get("scenario_type", "IDLE_DEPLOYMENT")
        withdrawals = allocation_strategy.get("withdrawals", [])
        allocations = allocation_strategy.get("allocations", [])
        
        if not allocations:
            return json.dumps({
                "success": False,
                "error": "No allocations provided in strategy",
                "timestamp": datetime.now().isoformat()
            })
        
        # Initialize tracking variables
        transaction_results = []
        total_invested = 0
        total_withdrawn = 0
        successful_transactions = 0
        failed_transactions = 0
        
        logger.info(f"=== Executing {scenario_type} Strategy ===")
        logger.info(f"Withdrawals: {len(withdrawals)}, Allocations: {len(allocations)}")
        
        # Step 1: Execute withdrawals (if any)
        if withdrawals:
            logger.info("=== Executing Withdrawal Phase ===")
            
            for i, withdrawal in enumerate(withdrawals):
                pool_address = withdrawal.get("pool_address", "").strip()
                amount_str = withdrawal.get("amount", "0").strip()
                protocol = withdrawal.get("protocol", "Unknown")
                
                # Validate withdrawal parameters
                if not pool_address or not amount_str:
                    error_msg = f"Invalid withdrawal parameters: pool_address='{pool_address}', amount='{amount_str}'"
                    logger.error(error_msg)
                    
                    # Save failed withdrawal to database
                    try:
                        RebalancingTrade.objects.create(
                            transaction_type=RebalancingTrade.TransactionType.WITHDRAWAL,
                            scenario_type=scenario_type,
                            status=RebalancingTrade.TransactionStatus.FAILED,
                            pool_address=pool_address or "INVALID",
                            protocol=protocol,
                            amount_wei=Decimal('0'),
                            amount_formatted=Decimal('0'),
                            allocation_index=i,
                            execution_timestamp=datetime.now(),
                            error_message=error_msg
                        )
                    except Exception as db_error:
                        logger.error(f"Failed to save failed withdrawal to database: {str(db_error)}")
                    
                    transaction_results.append({
                        "transaction_type": "WITHDRAWAL",
                        "allocation_index": i,
                        "pool_address": pool_address,
                        "protocol": protocol,
                        "amount": amount_str,
                        "success": False,
                        "error": error_msg
                    })
                    failed_transactions += 1
                    continue
                
                # Convert amount to integer (assuming it's already in wei)
                try:
                    amount_wei = int(float(amount_str))
                    if amount_wei <= 0:
                        raise ValueError("Amount must be positive")
                except (ValueError, TypeError) as e:
                    error_msg = f"Invalid withdrawal amount format: {amount_str} - {str(e)}"
                    logger.error(error_msg)
                    
                    # Save failed withdrawal to database
                    try:
                        RebalancingTrade.objects.create(
                            transaction_type=RebalancingTrade.TransactionType.WITHDRAWAL,
                            scenario_type=scenario_type,
                            status=RebalancingTrade.TransactionStatus.FAILED,
                            pool_address=pool_address,
                            protocol=protocol,
                            amount_wei=Decimal('0'),
                            amount_formatted=Decimal('0'),
                            allocation_index=i,
                            execution_timestamp=datetime.now(),
                            error_message=error_msg
                        )
                    except Exception as db_error:
                        logger.error(f"Failed to save failed withdrawal to database: {str(db_error)}")
                    
                    transaction_results.append({
                        "transaction_type": "WITHDRAWAL",
                        "allocation_index": i,
                        "pool_address": pool_address,
                        "protocol": protocol,
                        "amount": amount_str,
                        "success": False,
                        "error": error_msg
                    })
                    failed_transactions += 1
                    continue
                
                # Validate pool address format
                try:
                    Web3.to_checksum_address(pool_address)
                except Exception as e:
                    error_msg = f"Invalid withdrawal pool address format: {pool_address} - {str(e)}"
                    logger.error(error_msg)
                    
                    # Save failed withdrawal to database
                    try:
                        RebalancingTrade.objects.create(
                            transaction_type=RebalancingTrade.TransactionType.WITHDRAWAL,
                            scenario_type=scenario_type,
                            status=RebalancingTrade.TransactionStatus.FAILED,
                            pool_address=pool_address,
                            protocol=protocol,
                            amount_wei=Decimal(str(amount_wei)),
                            amount_formatted=Decimal(str(Web3.from_wei(amount_wei, 'ether'))),
                            allocation_index=i,
                            execution_timestamp=datetime.now(),
                            error_message=error_msg
                        )
                    except Exception as db_error:
                        logger.error(f"Failed to save failed withdrawal to database: {str(db_error)}")
                    
                    transaction_results.append({
                        "transaction_type": "WITHDRAWAL",
                        "allocation_index": i,
                        "pool_address": pool_address,
                        "protocol": protocol,
                        "amount": amount_str,
                        "success": False,
                        "error": error_msg
                    })
                    failed_transactions += 1
                    continue
                
                logger.info(f"Executing withdrawal {i+1}/{len(withdrawals)}: {Web3.from_wei(amount_wei, 'ether'):.6f} tokens from {protocol} pool {pool_address}")
                
                # Execute the withdrawal transaction
                withdrawal_result = execute_pool_withdrawal(amount_wei, pool_address)
                
                if withdrawal_result.get("success", False):
                    logger.info(f"Successfully executed withdrawal {i+1}")
                    successful_transactions += 1
                    total_withdrawn += amount_wei
                    
                    # Save successful withdrawal to database
                    try:
                        RebalancingTrade.objects.create(
                            transaction_type=RebalancingTrade.TransactionType.WITHDRAWAL,
                            scenario_type=scenario_type,
                            status=RebalancingTrade.TransactionStatus.SUCCESS,
                            pool_address=withdrawal_result["pool_address"],
                            protocol=protocol,
                            amount_wei=Decimal(str(amount_wei)),
                            amount_formatted=Decimal(str(withdrawal_result["amount_withdrawn_formatted"])),
                            transaction_hash=withdrawal_result["transaction_hash"],
                            block_number=withdrawal_result.get("block_number"),
                            executor_address=withdrawal_result.get("executor_address"),
                            gas_used=withdrawal_result.get("gas_used"),
                            gas_cost_eth=Decimal(str(withdrawal_result.get("gas_cost_eth", "0"))),
                            allocation_index=i,
                            execution_timestamp=datetime.now(),
                        )
                        logger.info(f"Saved withdrawal transaction to database: {withdrawal_result['transaction_hash']}")
                    except Exception as db_error:
                        logger.error(f"Failed to save withdrawal to database: {str(db_error)}")
                    
                    transaction_results.append({
                        "transaction_type": "WITHDRAWAL",
                        "allocation_index": i,
                        "pool_address": withdrawal_result["pool_address"],
                        "protocol": protocol,
                        "amount": amount_str,
                        "amount_formatted": withdrawal_result["amount_withdrawn_formatted"],
                        "success": True,
                        "transaction_hash": withdrawal_result["transaction_hash"],
                        "gas_used": withdrawal_result["gas_used"],
                        "gas_cost_eth": withdrawal_result["gas_cost_eth"],
                        "block_number": withdrawal_result["block_number"],
                        "executor_address": withdrawal_result["executor_address"]
                    })
                else:
                    logger.error(f"Failed to execute withdrawal {i+1}: {withdrawal_result.get('error', 'Unknown error')}")
                    failed_transactions += 1
                    
                    # Save failed withdrawal to database
                    try:
                        RebalancingTrade.objects.create(
                            transaction_type=RebalancingTrade.TransactionType.WITHDRAWAL,
                            scenario_type=scenario_type,
                            status=RebalancingTrade.TransactionStatus.FAILED,
                            pool_address=pool_address,
                            protocol=protocol,
                            amount_wei=Decimal(str(amount_wei)),
                            amount_formatted=Decimal(str(Web3.from_wei(amount_wei, 'ether'))),
                            transaction_hash=withdrawal_result.get("transaction_hash"),
                            allocation_index=i,
                            execution_timestamp=datetime.now(),
                            error_message=withdrawal_result.get("error", "Unknown error")
                        )
                        logger.info(f"Saved failed withdrawal transaction to database")
                    except Exception as db_error:
                        logger.error(f"Failed to save failed withdrawal to database: {str(db_error)}")
                    
                    transaction_results.append({
                        "transaction_type": "WITHDRAWAL",
                        "allocation_index": i,
                        "pool_address": pool_address,
                        "protocol": protocol,
                        "amount": amount_str,
                        "success": False,
                        "error": withdrawal_result.get("error", "Unknown error"),
                        "transaction_hash": withdrawal_result.get("transaction_hash")
                    })
        
        # Step 2: Execute allocations (deposits)
        logger.info("=== Executing Allocation Phase ===")
        
        for i, allocation in enumerate(allocations):
            pool_address = allocation.get("pool_address", "").strip()
            amount_str = allocation.get("amount", "0").strip()
            protocol = allocation.get("protocol", "Unknown")
            
            # Validate allocation parameters
            if not pool_address or not amount_str:
                error_msg = f"Invalid allocation parameters: pool_address='{pool_address}', amount='{amount_str}'"
                logger.error(error_msg)
                
                # Save failed allocation to database
                try:
                    RebalancingTrade.objects.create(
                        transaction_type=RebalancingTrade.TransactionType.DEPOSIT,
                        scenario_type=scenario_type,
                        status=RebalancingTrade.TransactionStatus.FAILED,
                        pool_address=pool_address or "INVALID",
                        protocol=protocol,
                        amount_wei=Decimal('0'),
                        amount_formatted=Decimal('0'),
                        allocation_index=i,
                        execution_timestamp=datetime.now(),
                        error_message=error_msg
                    )
                except Exception as db_error:
                    logger.error(f"Failed to save failed allocation to database: {str(db_error)}")
                
                transaction_results.append({
                    "transaction_type": "DEPOSIT",
                    "allocation_index": i,
                    "pool_address": pool_address,
                    "protocol": protocol,
                    "amount": amount_str,
                    "success": False,
                    "error": error_msg
                })
                failed_transactions += 1
                continue
            
            # Convert amount to integer (assuming it's already in wei)
            try:
                amount_wei = int(float(amount_str))
                if amount_wei <= 0:
                    raise ValueError("Amount must be positive")
            except (ValueError, TypeError) as e:
                error_msg = f"Invalid amount format: {amount_str} - {str(e)}"
                logger.error(error_msg)
                
                # Save failed allocation to database
                try:
                    RebalancingTrade.objects.create(
                        transaction_type=RebalancingTrade.TransactionType.DEPOSIT,
                        scenario_type=scenario_type,
                        status=RebalancingTrade.TransactionStatus.FAILED,
                        pool_address=pool_address,
                        protocol=protocol,
                        amount_wei=Decimal('0'),
                        amount_formatted=Decimal('0'),
                        allocation_index=i,
                        execution_timestamp=datetime.now(),
                        error_message=error_msg
                    )
                except Exception as db_error:
                    logger.error(f"Failed to save failed allocation to database: {str(db_error)}")
                
                transaction_results.append({
                    "transaction_type": "DEPOSIT",
                    "allocation_index": i,
                    "pool_address": pool_address,
                    "protocol": protocol,
                    "amount": amount_str,
                    "success": False,
                    "error": error_msg
                })
                failed_transactions += 1
                continue
            
            # Validate pool address format
            try:
                Web3.to_checksum_address(pool_address)
            except Exception as e:
                error_msg = f"Invalid pool address format: {pool_address} - {str(e)}"
                logger.error(error_msg)
                
                # Save failed allocation to database
                try:
                    RebalancingTrade.objects.create(
                        transaction_type=RebalancingTrade.TransactionType.DEPOSIT,
                        scenario_type=scenario_type,
                        status=RebalancingTrade.TransactionStatus.FAILED,
                        pool_address=pool_address,
                        protocol=protocol,
                        amount_wei=Decimal(str(amount_wei)),
                        amount_formatted=Decimal(str(Web3.from_wei(amount_wei, 'ether'))),
                        allocation_index=i,
                        execution_timestamp=datetime.now(),
                        error_message=error_msg
                    )
                except Exception as db_error:
                    logger.error(f"Failed to save failed allocation to database: {str(db_error)}")
                
                transaction_results.append({
                    "transaction_type": "DEPOSIT",
                    "allocation_index": i,
                    "pool_address": pool_address,
                    "protocol": protocol,
                    "amount": amount_str,
                    "success": False,
                    "error": error_msg
                })
                failed_transactions += 1
                continue
            
            logger.info(f"Executing allocation {i+1}/{len(allocations)}: {Web3.from_wei(amount_wei, 'ether'):.6f} tokens to {protocol} pool {pool_address}")
            
            # Execute the investment transaction
            investment_result = execute_pool_investment(amount_wei, pool_address)
            
            if investment_result.get("success", False):
                logger.info(f"Successfully executed allocation {i+1}")
                successful_transactions += 1
                total_invested += amount_wei
                
                # Save successful allocation to database
                try:
                    RebalancingTrade.objects.create(
                        transaction_type=RebalancingTrade.TransactionType.DEPOSIT,
                        scenario_type=scenario_type,
                        status=RebalancingTrade.TransactionStatus.SUCCESS,
                        pool_address=investment_result["pool_address"],
                        protocol=protocol,
                        amount_wei=Decimal(str(amount_wei)),
                        amount_formatted=Decimal(str(investment_result["amount_invested_formatted"])),
                        transaction_hash=investment_result["transaction_hash"],
                        block_number=investment_result.get("block_number"),
                        executor_address=investment_result.get("executor_address"),
                        gas_used=investment_result.get("gas_used"),
                        gas_cost_eth=Decimal(str(investment_result.get("gas_cost_eth", "0"))),
                        allocation_index=i,
                        execution_timestamp=datetime.now(),
                    )
                    logger.info(f"Saved allocation transaction to database: {investment_result['transaction_hash']}")
                except Exception as db_error:
                    logger.error(f"Failed to save allocation to database: {str(db_error)}")
                
                transaction_results.append({
                    "transaction_type": "DEPOSIT",
                    "allocation_index": i,
                    "pool_address": investment_result["pool_address"],
                    "protocol": protocol,
                    "amount": amount_str,
                    "amount_formatted": investment_result["amount_invested_formatted"],
                    "success": True,
                    "transaction_hash": investment_result["transaction_hash"],
                    "gas_used": investment_result["gas_used"],
                    "gas_cost_eth": investment_result["gas_cost_eth"],
                    "block_number": investment_result["block_number"],
                    "executor_address": investment_result["executor_address"]
                })
            else:
                logger.error(f"Failed to execute allocation {i+1}: {investment_result.get('error', 'Unknown error')}")
                failed_transactions += 1
                
                # Save failed allocation to database
                try:
                    RebalancingTrade.objects.create(
                        transaction_type=RebalancingTrade.TransactionType.DEPOSIT,
                        scenario_type=scenario_type,
                        status=RebalancingTrade.TransactionStatus.FAILED,
                        pool_address=pool_address,
                        protocol=protocol,
                        amount_wei=Decimal(str(amount_wei)),
                        amount_formatted=Decimal(str(Web3.from_wei(amount_wei, 'ether'))),
                        transaction_hash=investment_result.get("transaction_hash"),
                        allocation_index=i,
                        execution_timestamp=datetime.now(),
                        error_message=investment_result.get("error", "Unknown error")
                    )
                    logger.info(f"Saved failed allocation transaction to database")
                except Exception as db_error:
                    logger.error(f"Failed to save failed allocation to database: {str(db_error)}")
                
                transaction_results.append({
                    "transaction_type": "DEPOSIT",
                    "allocation_index": i,
                    "pool_address": pool_address,
                    "protocol": protocol,
                    "amount": amount_str,
                    "success": False,
                    "error": investment_result.get("error", "Unknown error"),
                    "transaction_hash": investment_result.get("transaction_hash")
                })
        
        # Calculate summary statistics
        total_operations = len(withdrawals) + len(allocations)
        total_invested_formatted = Web3.from_wei(total_invested, 'ether') if total_invested > 0 else 0
        total_withdrawn_formatted = Web3.from_wei(total_withdrawn, 'ether') if total_withdrawn > 0 else 0
        success_rate = (successful_transactions / total_operations * 100) if total_operations else 0
        
        # Calculate total gas costs
        total_gas_cost_eth = sum(
            float(result.get("gas_cost_eth", "0")) 
            for result in transaction_results 
            if result.get("success", False)
        )
        
        execution_summary = {
            "success": successful_transactions > 0,
            "scenario_type": scenario_type,
            "timestamp": datetime.now().isoformat(),
            "strategy_summary": {
                "total_operations": total_operations,
                "total_withdrawals": len(withdrawals),
                "total_allocations": len(allocations),
                "successful_transactions": successful_transactions,
                "failed_transactions": failed_transactions,
                "success_rate_percent": round(success_rate, 2),
                "total_withdrawn_wei": total_withdrawn,
                "total_withdrawn_formatted": f"{total_withdrawn_formatted:.6f}",
                "total_invested_wei": total_invested,
                "total_invested_formatted": f"{total_invested_formatted:.6f}",
                "total_gas_cost_eth": f"{total_gas_cost_eth:.6f}"
            },
            "transaction_details": transaction_results
        }
        
        logger.info(f"=== {scenario_type} Execution Complete ===")
        logger.info(f"Successful: {successful_transactions}/{total_operations} ({success_rate:.1f}%)")
        if total_withdrawn > 0:
            logger.info(f"Total Withdrawn: {total_withdrawn_formatted:.6f} tokens")
        logger.info(f"Total Invested: {total_invested_formatted:.6f} tokens")
        logger.info(f"Total Gas Cost: {total_gas_cost_eth:.6f} ETH")
        
        return json.dumps(execution_summary, indent=2)
        
    except json.JSONDecodeError as e:
        error_msg = f"Invalid JSON format in allocation strategy: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        error_msg = f"Error executing yield allocation strategy: {str(e)}"
        logger.error(error_msg)
        return json.dumps({
            "success": False,
            "error": error_msg,
            "timestamp": datetime.now().isoformat()
        })
