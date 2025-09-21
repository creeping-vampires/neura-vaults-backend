import json
import logging
from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from ..models import PortfolioSnapshot, CapitalFlow, Withdrawal

logger = logging.getLogger(__name__)

class AdjustedPnLCalculator:
    """
    Service for calculating adjusted PnL that accounts for deposits and withdrawals.
    """
    
    @staticmethod
    def calculate_adjusted_pnl(agent, current_value):
        """
        Calculate adjusted PnL for an agent, accounting for deposits and withdrawals.
        
        Args:
            agent: The Agent instance
            current_value: The current USD value of the agent's portfolio

            net_deposit = total_deposits_usd - total_withdrawals_usd
            portfolio_value = get_current_portfolio_value(wallet_address)

            unrealized_pnl = portfolio_value - net_deposit
            
        Returns:
            dict: Adjusted PnL metrics
        """
        try:
            # Get the first and latest snapshots
            # snapshots_query = PortfolioSnapshot.objects.filter(agent=agent)
            
            # if start_date:
            #     first_snapshot = snapshots_query.filter(timestamp__gte=start_date).order_by('timestamp').first()
            # else:
            #     first_snapshot = snapshots_query.order_by('timestamp').first()
                
            # if end_date:
            #     latest_snapshot = snapshots_query.filter(timestamp__lte=end_date).order_by('-timestamp').first()
            # else:
            #     latest_snapshot = snapshots_query.order_by('-timestamp').first()
            
            # if not first_snapshot or not latest_snapshot:
            #     return {
            #         'success': False,
            #         'message': 'Not enough snapshots to calculate PnL'
            #     }
            
            # # If first and latest are the same, no PnL to calculate
            # if first_snapshot.id == latest_snapshot.id:
            #     return {
            #         'success': True,
            #         'absolute_pnl_usd': 0,
            #         'percentage_pnl': 0,
            #         'adjusted_percentage_pnl': 0,
            #         'initial_value': float(first_snapshot.total_usd_value),
            #         'final_value': float(latest_snapshot.total_usd_value),
            #         'total_deposits': 0,
            #         'total_withdrawals': 0,
            #         'first_snapshot_timestamp': first_snapshot.timestamp.isoformat(),
            #         'latest_snapshot_timestamp': latest_snapshot.timestamp.isoformat()
            #     }
            
            # Get all deposits by agent from Capital flow
            deposits = CapitalFlow.objects.filter(
                agent=agent,
                flow_type='deposit'
            )
            
            
            # Get all withdrawals by agent from Withdrawal model
            withdrawals = Withdrawal.objects.filter(
                agent=agent
            )
            
            # Convert to Decimal for precise calculations
            total_deposits = sum((Decimal(str(deposit.usd_value)) if not isinstance(deposit.usd_value, Decimal) else deposit.usd_value) for deposit in deposits)
            total_withdrawals = sum((Decimal(str(withdrawal.usd_value)) if not isinstance(withdrawal.usd_value, Decimal) else withdrawal.usd_value) for withdrawal in withdrawals)
            
            # Calculate raw PNL
            net_deposit = total_deposits - total_withdrawals
            # Convert current_value to Decimal for consistent type handling
            portfolio_value = Decimal(str(current_value)) if not isinstance(current_value, Decimal) else current_value
            unrealized_pnl = portfolio_value - Decimal(str(net_deposit))

            percentage_pnl = (unrealized_pnl / Decimal(str(net_deposit))) * 100 if Decimal(str(net_deposit)) > 0 else 0


            # initial_value = float(first_snapshot.total_usd_value)
            # final_value = float(latest_snapshot.total_usd_value)
            # raw_pnl = final_value - initial_value
            
            # # Calculate adjusted PNL by removing the effect of deposits and withdrawals
            # # Deposits artificially increase PNL, so subtract them
            # # Withdrawals artificially decrease PNL, so add them back
            # adjusted_pnl = raw_pnl - float(total_deposits) + float(total_withdrawals)
            
            # # Calculate adjusted initial value for percentage calculations
            # # This represents what the initial value would have been without capital flows
            # adjusted_initial_value = initial_value
            
            # Calculate percentage PnL
            # percentage_pnl = (raw_pnl / initial_value) * 100 if initial_value > 0 else 0
            # adjusted_percentage_pnl = (adjusted_pnl / adjusted_initial_value) * 100 if adjusted_initial_value > 0 else 0
            
            return {
                'success': True,
                'absolute_pnl_usd': float(unrealized_pnl),
                'percentage_pnl': float(percentage_pnl),
                'total_deposits': float(total_deposits),
                'total_withdrawals': float(total_withdrawals),
            }
            
        except Exception as e:
            logger.error(f"Error calculating adjusted PnL for agent {agent.id}: {str(e)}")
            return {
                'success': False,
                'message': f"Error: {str(e)}"
            }

class SnapshotPnLUpdater:
    """
    Service for updating portfolio snapshots with PNL values.
    """
    
    @staticmethod
    def update_snapshot_pnl(snapshot):
        """
        Calculate and update PNL values for a given snapshot.
        
        Args:
            snapshot: The PortfolioSnapshot instance to update
            recent_deposit: Optional dict with information about a deposit that was just recorded
                       (to ensure it's properly excluded from adjusted PNL)
        
        Returns:
            bool: True if update was successful, False otherwise
        """
        try:
            agent = snapshot.agent

            # new logic 

            adjusted_result = AdjustedPnLCalculator.calculate_adjusted_pnl(agent=agent,
            current_value=snapshot.total_usd_value)

            snapshot.absolute_pnl_usd = adjusted_result.get('absolute_pnl_usd', 0)
            snapshot.percentage_pnl = adjusted_result.get('percentage_pnl', 0)
            snapshot.total_deposits = adjusted_result.get('total_deposits', 0)
            snapshot.total_withdrawals = adjusted_result.get('total_withdrawals', 0)
            snapshot.save()

            # old logic 
            # Calculate 24h PNL
            # twenty_four_hours_ago = snapshot.timestamp - timezone.timedelta(hours=24)
            # reference_snapshot_24h = PortfolioSnapshot.objects.filter(
            #     agent=agent,
            #     timestamp__lte=twenty_four_hours_ago
            # ).order_by('-timestamp').first()
            
            # # If no snapshot from 24h ago, use the earliest available snapshot
            # if not reference_snapshot_24h:
            #     reference_snapshot_24h = PortfolioSnapshot.objects.filter(
            #         agent=agent,
            #         timestamp__lt=snapshot.timestamp
            #     ).order_by('timestamp').first()
            
            # # Calculate all-time PNL (from first snapshot)
            # reference_snapshot_all_time = PortfolioSnapshot.objects.filter(
            #     agent=agent
            # ).order_by('timestamp').first()
            
            # Update 24h PNL if reference snapshot exists
            # if reference_snapshot_24h and reference_snapshot_24h.id != snapshot.id:
            #     # Calculate raw 24h PNL
            #     initial_value = float(reference_snapshot_24h.total_usd_value)
            #     final_value = float(snapshot.total_usd_value)
            #     raw_pnl = final_value - initial_value
            #     percentage_pnl = (raw_pnl / initial_value) * 100 if initial_value > 0 else 0
                
            #     # Calculate adjusted 24h PNL
            #     adjusted_result = AdjustedPnLCalculator.calculate_adjusted_pnl(
            #         agent=agent,
            #         start_date=reference_snapshot_24h.timestamp,
            #         end_date=snapshot.timestamp
            #     )
                
                # If we have a recent deposit that might not be in the database yet,
                # manually adjust the PNL calculation to exclude it
                # if recent_deposit and adjusted_result.get('success', False):
                #     # Subtract the recent deposit from adjusted PNL
                #     adjusted_absolute_pnl = adjusted_result.get('adjusted_absolute_pnl_usd', raw_pnl)
                #     adjusted_absolute_pnl -= float(recent_deposit['usd_value'])
                    
                #     # Recalculate adjusted percentage PNL
                #     adjusted_initial_value = adjusted_result.get('adjusted_initial_value', initial_value)
                #     adjusted_percentage_pnl = (adjusted_absolute_pnl / adjusted_initial_value) * 100 if adjusted_initial_value > 0 else 0
                    
                #     # Update the result
                #     adjusted_result['adjusted_absolute_pnl_usd'] = adjusted_absolute_pnl
                #     adjusted_result['adjusted_percentage_pnl'] = adjusted_percentage_pnl
                    
                #     logger.info(f"Manually adjusted PNL to exclude recent deposit of {recent_deposit['usd_value']} USD")
                
                # if adjusted_result.get('success', False):
                    # snapshot.pnl_24h_absolute = Decimal(str(raw_pnl))
                    # snapshot.pnl_24h_percentage = Decimal(str(percentage_pnl))
                    # snapshot.pnl_24h_adjusted_absolute = Decimal(str(adjusted_result.get('adjusted_absolute_pnl_usd', raw_pnl)))
                    # snapshot.pnl_24h_adjusted_percentage = Decimal(str(adjusted_result.get('adjusted_percentage_pnl', percentage_pnl)))
                    # snapshot.pnl_reference_snapshot_24h = reference_snapshot_24h
            
            # Update all-time PNL if reference snapshot exists and is different from 24h reference
            # if reference_snapshot_all_time and reference_snapshot_all_time.id != snapshot.id:
            #     # Calculate raw all-time PNL
            #     initial_value = float(reference_snapshot_all_time.total_usd_value)
            #     final_value = float(snapshot.total_usd_value)
            #     raw_pnl = final_value - initial_value
            #     percentage_pnl = (raw_pnl / initial_value) * 100 if initial_value > 0 else 0
                
            #     snapshot.pnl_all_time_absolute = Decimal(str(raw_pnl))
            #     snapshot.pnl_all_time_percentage = Decimal(str(percentage_pnl))
            #     snapshot.pnl_reference_snapshot_all_time = reference_snapshot_all_time
            
            # Save the updated snapshot
            # snapshot.save()
            return True
            
        except Exception as e:
            logger.error(f"Error updating PNL for snapshot {snapshot.id}: {str(e)}")
            return False
