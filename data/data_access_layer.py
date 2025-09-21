import logging
from datetime import datetime, time
from django.db import models
from django.http import Http404
from django.utils import timezone
from django.db.models import Sum
from django.db.models.functions import TruncDate
from django.db.models import Q
from django.db import transaction
from django.conf import settings
from .models import Agent, User, AgentWallet, AgentTrade, UserCredits, AgentFunds, Thought, CreditRequest,UserRole, InviteCode, OptimizationResult, YieldReport, AgnosticThought
from .utils.token_utils import get_token_info
from .utils.common import get_token_address
logger = logging.getLogger(__name__)

class AgentDAL:
    @staticmethod
    def get_agents_for_user(privy_address: str) -> models.QuerySet:
        """Get all non-deleted agents for a user."""
        return Agent.objects.filter(
            user__privy_address__iexact=privy_address,
            is_deleted=False
        )

    @staticmethod
    def get_agent_by_id(agent_id: int) -> Agent:
        """Get a non-deleted agent by ID."""
        try:
            agent = Agent.objects.get(id=agent_id)
            if agent.is_deleted:
                logger.warning(f"Attempted to access deleted agent: {agent_id}")
                raise Http404("Agent not found")
            return agent
        except Agent.DoesNotExist:
            raise Http404("Agent not found")

    @staticmethod
    def get_deleted_agents_for_user(privy_address: str) -> models.QuerySet:
        """Get all deleted agents for a user."""
        return Agent.all_objects.filter(
            user__privy_address__iexact=privy_address,
            is_deleted=True
        )

    @staticmethod
    def create_agent(user: User, **kwargs) -> Agent:
        """Create a new agent programmatically.
        
        Note: This method is for direct programmatic agent creation, not for use in API views.
        API views handle credit deduction separately to properly work with serializers.
        """
        # Check if user has sufficient credits
        if not UserCreditsDAL.has_sufficient_credits(user):
            raise ValueError("Insufficient credits to create agent")
        
        try:
            # Create the agent
            agent = Agent.objects.create(user=user, **kwargs)
            # Deduct one credit
            UserCreditsDAL.deduct_credits(user)
            return agent
        except Exception as e:
            logger.error(f"Error creating agent: {str(e)}")
            raise
            
    @staticmethod
    def get_active_agents_count(as_of: datetime = None) -> int:
        """Get the count of active agents (status=running) as of a specific time.
        
        Args:
            as_of: Optional datetime to count agents as of that time
                  If None, counts current active agents
        
        Returns:
            Count of active agents
        """
        # Base query for active agents
        query = Agent.objects.filter(
            status=Agent.StatusChoices.RUNNING,
            is_deleted=False
        )
        
        # For historical data, we can only check deletion time
        # since Agent model doesn't have created_at field
        if as_of:
            # For agents that were deleted, only include them if they were deleted after as_of
            deleted_filter = Q(deleted_at__isnull=True) | Q(deleted_at__gt=as_of)
            query = query.filter(deleted_filter)
        
        return query.count()
        
    @staticmethod
    def get_recent_trades(hours: int = 24, offset_hours: int = 0) -> models.QuerySet:
        """Get trades from the last N hours with optional offset.
        
        Args:
            hours: Number of hours to look back
            offset_hours: Optional offset in hours (for comparing previous periods)
            
        Returns:
            QuerySet of trades within the specified time period
        """
        from django.utils import timezone
        # Use server's local timezone for consistency with other time-based calculations
        now = timezone.localtime(timezone.now())
        
        # Calculate time thresholds with offset
        end_time = now - timezone.timedelta(hours=offset_hours)
        start_time = end_time - timezone.timedelta(hours=hours)
        
        logger.info(f"Getting recent trades from {start_time} to {end_time if offset_hours > 0 else now} (Server local time)")
        
        # For current period (no offset), include trades up to now
        if offset_hours == 0:
            return AgentTrade.objects.filter(created_at__gte=start_time)
        else:
            return AgentTrade.objects.filter(
                created_at__gte=start_time,
                created_at__lt=end_time
            )
    
    @staticmethod
    def get_daily_trade_volumes(days: int = 7) -> list:
        """Get daily trade volumes for the past N days.
        
        Returns:
            list: List of dictionaries with 'date' and 'volume' keys
        """
        # Calculate the date range using the server's local timezone
        now = timezone.localtime(timezone.now())
        end_date = now.date()
        start_date = end_date - timezone.timedelta(days=days-1)
        
        logger.info(f"Getting daily trade volumes from {start_date} to {end_date} (Server local time)")
        
        # Get trade volumes grouped by date
        daily_volumes = AgentTrade.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            volume=Sum('amount_usd')
        ).order_by('date')
        
        # Convert to list of dictionaries with date strings
        result = []
        for entry in daily_volumes:
            result.append({
                'date': entry['date'].strftime('%Y-%m-%d'),
                'volume': float(entry['volume'] or 0)
            })
        
        # Fill in missing dates with zero volume
        date_map = {item['date']: item['volume'] for item in result}
        complete_result = []
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            complete_result.append({
                'date': date_str,
                'volume': date_map.get(date_str, 0)
            })
            current_date += timezone.timedelta(days=1)
        
        return complete_result

    @staticmethod
    def get_current_day_trade_count() -> int:
        """Get total number of trades for the current day.
        
        This uses the same date-based filtering as get_daily_trade_volumes
        to ensure consistency between trade count and chart data.
        
        Returns:
            int: Total number of trades for the current day
        """
        # Calculate the current date using the server's local timezone
        now = timezone.localtime(timezone.now())
        current_date = now.date()
        
        logger.info(f"Getting current day trade count for {current_date} (Server local time)")
        
        # Get trade count for the current day
        trade_count = AgentTrade.objects.filter(
            created_at__date=current_date
        ).count()
        
        return trade_count
        
    @staticmethod
    def get_previous_day_trade_volume() -> float:
        """Get trade volume for the previous day.
        
        This uses the same date-based filtering as get_daily_trade_volumes
        to ensure consistency between metrics and chart data.
        
        Returns:
            float: Total trade volume for the previous day
        """
        # Calculate the previous date using the server's local timezone
        now = timezone.localtime(timezone.now())
        previous_date = (now - timezone.timedelta(days=1)).date()
        
        logger.info(f"Getting previous day trade volume for {previous_date} (Server local time)")
        
        # Get trade volume for the previous day
        trade_volume = AgentTrade.objects.filter(
            created_at__date=previous_date
        ).aggregate(volume=Sum('amount_usd'))
        
        return float(trade_volume['volume'] or 0)
    
    @staticmethod
    def get_previous_day_trade_count() -> int:
        """Get total number of trades for the previous day.
        
        This uses the same date-based filtering as get_daily_trade_volumes
        to ensure consistency between metrics and chart data.
        
        Returns:
            int: Total number of trades for the previous day
        """
        # Calculate the previous date using the server's local timezone
        now = timezone.localtime(timezone.now())
        previous_date = (now - timezone.timedelta(days=1)).date()
        
        logger.info(f"Getting previous day trade count for {previous_date} (Server local time)")
        
        # Get trade count for the previous day
        trade_count = AgentTrade.objects.filter(
            created_at__date=previous_date
        ).count()
        
        return trade_count

    @staticmethod
    def update_agent(agent: Agent, **kwargs) -> Agent:
        """Update an agent."""
        if agent.is_deleted:
            logger.warning(f"Attempted to update deleted agent: {agent.id}")
            raise Http404("Agent not found")
        
        for key, value in kwargs.items():
            setattr(agent, key, value)
        agent.save()
        return agent

    @staticmethod
    def delete_agent(agent: Agent) -> None:
        """Soft delete an agent."""
        agent.delete()  # This will call our custom delete method

    @staticmethod
    def restore_agent(agent_id: int) -> Agent:
        """Restore a deleted agent."""
        try:
            agent = Agent.all_objects.get(id=agent_id)
            if not agent.is_deleted:
                raise ValueError("Agent is not deleted")
            
            agent.is_deleted = False
            agent.deleted_at = None
            agent.save()
            return agent
        except Agent.DoesNotExist:
            raise Http404("Agent not found")

    @staticmethod
    def get_agent_trades(agent: Agent) -> models.QuerySet:
        """Get all trades for an agent."""
        if agent.is_deleted:
            logger.warning(f"Attempted to access trades of deleted agent: {agent.id}")
            raise Http404("Agent not found")
        return agent.trades.all()

class UserDAL:
    @staticmethod
    def get_users() -> models.QuerySet:
        """Get all non-deleted users."""
        return User.objects.filter(is_deleted=False)

    @staticmethod
    def get_user_by_privy_address(privy_address: str) -> User:
        """Get a user by privy address."""
        try:
            return User.objects.get(privy_address__iexact=privy_address, is_deleted=False)
        except User.DoesNotExist:
            raise Http404("User not found")

    @staticmethod
    def is_user_active(privy_address: str) -> bool:
        """Check if a user is active."""
        return User.objects.filter(
            privy_address__iexact=privy_address,
            is_active=True,
            is_deleted=False
        ).exists()

    @staticmethod
    def get_deleted_users() -> models.QuerySet:
        """Get all deleted users."""
        return User.all_objects.filter(is_deleted=True)

    @staticmethod
    def restore_user(user_id: int) -> User:
        """Restore a deleted user."""
        try:
            user = User.all_objects.get(id=user_id)
            if not user.is_deleted:
                raise ValueError("User is not deleted")
            
            user.is_deleted = False
            user.deleted_at = None
            user.save()
            return user
        except User.DoesNotExist:
            raise Http404("User not found")

class AgentWalletDAL:
    @staticmethod
    def create_wallet(agent: Agent, address: str, wallet_id: str) -> AgentWallet:
        """Create a wallet for an agent.
        
        Args:
            agent: The agent to create the wallet for
            address: The wallet address
            wallet_id: The unique identifier for the wallet
            
        Returns:
            AgentWallet: The created wallet instance
        """
        return AgentWallet.objects.create(agent=agent, address=address, wallet_id=wallet_id)

    @staticmethod
    def get_wallet_for_agent(agent: Agent) -> AgentWallet:
        """Get the wallet for an agent."""
        try:
            return agent.wallet
        except AgentWallet.DoesNotExist:
            raise Http404("Wallet not found")

class AgentFundsDAL:
    @staticmethod
    def create_fund(wallet: AgentWallet, token_name: str, token_symbol: str, token_address: str, amount: float, decimals: int = 18) -> AgentFunds:
        """Create a fund entry for an agent's wallet."""
        return AgentFunds.objects.create(
            wallet=wallet,
            token_name=token_name,
            token_symbol=token_symbol,
            token_address=token_address,
            amount=amount,
            decimals=decimals
        )
    
    @staticmethod
    def get_funds_for_wallet(wallet: AgentWallet) -> models.QuerySet:
        """Get all active funds for a wallet."""
        return AgentFunds.objects.filter(wallet=wallet, is_active=True)
    
    @staticmethod
    def get_all_funds_for_wallet(wallet: AgentWallet) -> models.QuerySet:
        """Get all funds (active and inactive) for a wallet."""
        return AgentFunds.objects.filter(wallet=wallet)
    
    @staticmethod
    def get_all_token_balances(as_of: datetime = None) -> dict:
        """Get total balances for all tokens across all wallets as of a specific time.
        
        Args:
            as_of: Optional datetime to get balances as of that time
                  If None, gets current balances
        
        Returns:
            dict: Dictionary mapping token symbols to their total balances
        """
        # Base query for all funds
        query = AgentFunds.objects.filter(is_active=True)
        
        # If we're looking at historical data, we need to consider:
        # 1. Only funds that existed at that time (Note: AgentFunds doesn't have created_at field)
        # 2. Only wallets/agents that existed at that time (Note: Agent doesn't have created_at field)
        if as_of:
            # Only consider wallets for agents that were active at that time
            # (either not deleted or deleted after as_of)
            active_agents_filter = Q(wallet__agent__deleted_at__isnull=True) | \
                                  Q(wallet__agent__deleted_at__gt=as_of)
            query = query.filter(active_agents_filter)
        
        # Get all unique token symbols from the filtered query
        token_symbols = query.values_list('token_symbol', flat=True).distinct()
        
        # Calculate total balance for each token
        balances = {}
        for symbol in token_symbols:
            total = query.filter(token_symbol=symbol).aggregate(total=Sum('amount'))
            balances[symbol] = float(total['total'] or 0)
            
        return balances

    @staticmethod
    def get_funds_for_agent(agent: Agent) -> models.QuerySet:
        """
        Retrieve all active funds (tokens and balances) for a given agent.

        Args:
            agent (Agent): The agent instance.

        Returns:
            QuerySet: All active AgentFunds objects for the agent's wallet, or an empty queryset if no wallet exists.
        """
        try:
            wallet = AgentWallet.objects.get(agent=agent)
            return AgentFunds.objects.filter(wallet=wallet, is_active=True)
        except AgentWallet.DoesNotExist:
            return AgentFunds.objects.none()
            
    @staticmethod
    def update_agent_preset_tokens(agent: Agent, new_whitelist_presets: list) -> None:
        """
        Update an agent's preset tokens. Deactivate funds with no balance that are no longer in the whitelist,
        and create new fund entries for new tokens in the whitelist.
        
        Args:
            agent (Agent): The agent instance
            new_whitelist_presets (list): List of new token symbols for the whitelist
        
        Returns:
            None
        """
        try:
            wallet = AgentWallet.objects.get(agent=agent)
            
            # Get token info from token_utils
            token_info = get_token_info()
            
            # Get current active funds
            current_funds = AgentFunds.objects.filter(wallet=wallet, is_active=True)
            current_tokens = {fund.token_symbol: fund for fund in current_funds}
            
            # Process tokens to remove (deactivate if they have no balance)
            for token_symbol, fund in current_tokens.items():
                if token_symbol != 'HYPE' and token_symbol not in new_whitelist_presets:
                    # Check if the fund has any balance
                    if fund.amount == 0:
                        # Deactivate the fund
                        fund.is_active = False
                        fund.save()
                        logger.info(f"Deactivated fund for token {token_symbol} in agent {agent.id}'s wallet")
            
            # Process tokens to add
            for token_symbol in new_whitelist_presets:
                if token_symbol not in current_tokens:
                    # Check if an inactive fund for this token already exists
                    existing_inactive_fund = AgentFunds.objects.filter(
                        wallet=wallet,
                        token_symbol=token_symbol,
                        is_active=False
                    ).first()
                    
                    if existing_inactive_fund:
                        # Reactivate the existing fund
                        existing_inactive_fund.is_active = True
                        existing_inactive_fund.save()
                        logger.info(f"Reactivated existing fund for token {token_symbol} in agent {agent.id}'s wallet")
                    else:
                        # Get token address
                        token_address = get_token_address(token_symbol)
                        
                        if token_address:
                            # Get token decimals
                            token_decimals = token_info.get(token_symbol, {}).get('decimals', 18)
                            
                            # Create new fund
                            AgentFundsDAL.create_fund(
                                wallet=wallet,
                                token_name=token_symbol,
                                token_symbol=token_symbol,
                                token_address=token_address,
                                amount=0,
                                decimals=token_decimals
                            )
                            logger.info(f"Added new fund for token {token_symbol} to agent {agent.id}'s wallet")
                        else:
                            logger.warning(f"Token address not found for {token_symbol}")
            
            # Update the agent's whitelist_presets field
            agent.whitelist_presets = str(new_whitelist_presets)
            agent.save()
            logger.info(f"Updated whitelist_presets for agent {agent.id}: {new_whitelist_presets}")
            
        except AgentWallet.DoesNotExist:
            logger.error(f"Wallet not found for agent {agent.id}")
            raise ValueError(f"Wallet not found for agent {agent.id}")
        except Exception as e:
            logger.error(f"Error updating preset tokens for agent {agent.id}: {str(e)}")
            raise

class UserCreditsDAL:
    @staticmethod
    def get_user_credits(user: User) -> UserCredits:
        """Get or create user credits."""
        credits, created = UserCredits.objects.get_or_create(user=user)
        return credits

    @staticmethod
    def has_sufficient_credits(user: User, required_credits: int = 1) -> bool:
        """Check if user has sufficient credits."""
        credits = UserCreditsDAL.get_user_credits(user)
        has_credits = credits.balance >= required_credits
        logger.info(f"Credit check for user {user.privy_address}: balance={credits.balance}, required={required_credits}, sufficient={has_credits}")
        return has_credits

    @staticmethod
    def deduct_credits(user: User, amount: int = 1) -> UserCredits:
        """Deduct credits from user's balance."""
        credits = UserCreditsDAL.get_user_credits(user)
        if credits.balance < amount:
            logger.warning(f"Insufficient credits for user {user.privy_address}: balance={credits.balance}, requested={amount}")
            raise ValueError("Insufficient credits")
        
        previous_balance = credits.balance
        credits.balance -= amount
        credits.save()
        logger.info(f"Deducted {amount} credits from user {user.privy_address}: previous={previous_balance}, new={credits.balance}")
        return credits

    @staticmethod
    def add_credits(user: User, amount: int = 1) -> UserCredits:
        """Add credits to user's balance."""
        credits = UserCreditsDAL.get_user_credits(user)
        previous_balance = credits.balance
        credits.balance += amount
        credits.save()
        logger.info(f"Added {amount} credits to user {user.privy_address}: previous={previous_balance}, new={credits.balance}")
        return credits 

class CreditRequestDAL:
    @staticmethod
    def create_credit_request(user: User, twitter_handle: str, credits_requested: int = None) -> CreditRequest:
        """
        Create a new credit request for a user.
        
        Args:
            user: The user requesting credits
            twitter_handle: Twitter handle of the user
            credits_requested: Number of credits requested (defaults to settings.DEFAULT_USER_CREDITS)
            
        Returns:
            CreditRequest: The created credit request instance
        """
        # Use the default from settings if not specified
        if credits_requested is None:
            credits_requested = settings.DEFAULT_USER_CREDITS
        return CreditRequest.objects.create(
            user=user,
            privy_id=user.privy_address,  # Store the Privy ID explicitly
            twitter_handle=twitter_handle,
            credits_requested=credits_requested
        )
    
    @staticmethod
    def get_credit_requests_for_user(user: User) -> models.QuerySet:
        """
        Get all credit requests for a user.
        
        Args:
            user: The user to get credit requests for
            
        Returns:
            QuerySet: All credit requests for the user
        """
        return CreditRequest.objects.filter(user=user)
    
    @staticmethod
    def get_pending_credit_requests() -> models.QuerySet:
        """
        Get all pending credit requests.
        
        Returns:
            QuerySet: All pending credit requests
        """
        return CreditRequest.objects.filter(status=CreditRequest.StatusChoices.PENDING)
    
    @staticmethod
    def approve_credit_request(credit_request: CreditRequest, credits_granted: int = None, notes: str = None) -> CreditRequest:
        """
        Approve a credit request and add credits to the user's balance.
        
        Args:
            credit_request: The credit request to approve
            credits_granted: Number of credits to grant (default: same as requested)
            notes: Optional notes about the approval
            
        Returns:
            CreditRequest: The updated credit request instance
        """
        with transaction.atomic():
            # If credits_granted not specified, use the requested amount
            if credits_granted is None:
                credits_granted = credit_request.credits_requested
                
            # Update the credit request
            credit_request.status = CreditRequest.StatusChoices.APPROVED
            credit_request.credits_granted = credits_granted
            credit_request.processed_at = timezone.now()
            if notes:
                credit_request.notes = notes
            credit_request.save()
            
            # Add credits to the user's balance
            UserCreditsDAL.add_credits(credit_request.user, credits_granted)
            
            return credit_request
    
    @staticmethod
    def reject_credit_request(credit_request: CreditRequest, notes: str = None) -> CreditRequest:
        """
        Reject a credit request.
        
        Args:
            credit_request: The credit request to reject
            notes: Optional notes about the rejection
            
        Returns:
            CreditRequest: The updated credit request instance
        """
        credit_request.status = CreditRequest.StatusChoices.REJECTED
        credit_request.processed_at = timezone.now()
        if notes:
            credit_request.notes = notes
        credit_request.save()
        return credit_request


class ThoughtDAL:
    @staticmethod
    def create_thought(agent_id: int = None, thought: str = "", agent_role: str = ""):
        """Create a new thought for an agent.
        
        Args:
            agent_id: The ID of the agent (optional for agent-agnostic mode)
            thought: The thought content
            agent_role: The role of the agent
            
        Returns:
            Thought: The created thought instance
        """
        try:
            agent = None
            if agent_id is not None:
                try:
                    agent = Agent.objects.get(id=agent_id)
                except Agent.DoesNotExist:
                    # For agent-agnostic mode, create thought without agent
                    agent = None
            
            return Thought.objects.create(
                agent=agent,
                thought=thought,
                agent_role=agent_role
            )
        except Exception as e:
            # Fallback: create thought without agent for agent-agnostic mode
            return Thought.objects.create(
                agent=None,
                thought=thought,
                agent_role=agent_role
            )
    
    @staticmethod
    def get_thoughts_for_agent(agent_id: int):
        """
        Get all thoughts for an agent.
        
        Args:
            agent_id: The ID of the agent
            
        Returns:
            QuerySet: All thoughts for the agent
            
        Raises:
            Http404: If the agent is not found
        """
        try:
            agent = Agent.objects.get(id=agent_id)
            return Thought.objects.filter(agent=agent).order_by('-created_at')
        except Agent.DoesNotExist:
            raise Http404(f"Agent with ID {agent_id} not found")


class AgnosticThoughtDAL:
    """Data Access Layer for AgnosticThought model - handles thoughts from agent-agnostic mode."""
    
    @staticmethod
    def create_agnostic_thought(thought: str, agent_role: str, crew_id: str = None):
        """Create a new thought for agent-agnostic mode.
        
        Args:
            thought: The thought content
            agent_role: The role of the agent
            crew_id: Optional crew execution ID for tracking
            
        Returns:
            AgnosticThought: The created agnostic thought instance
        """
        from .models import AgnosticThought
        
        return AgnosticThought.objects.create(
            thought=thought,
            agent_role=agent_role,
            crew_id=crew_id,
            execution_mode='agent-agnostic'
        )
    
    @staticmethod
    def get_recent_agnostic_thoughts(limit: int = 50):
        """Get recent agnostic thoughts.
        
        Args:
            limit: Maximum number of thoughts to return
            
        Returns:
            QuerySet: Recent agnostic thoughts ordered by creation time
        """
        from .models import AgnosticThought
        
        return AgnosticThought.objects.all()[:limit]
    
    @staticmethod
    def get_agnostic_thoughts_by_role(agent_role: str, limit: int = 50):
        """Get agnostic thoughts by agent role.
        
        Args:
            agent_role: The agent role to filter by
            limit: Maximum number of thoughts to return
            
        Returns:
            QuerySet: Agnostic thoughts for the specified role
        """
        from .models import AgnosticThought
        
        return AgnosticThought.objects.filter(agent_role=agent_role)[:limit]


class UserRoleDAL:
    """Data Access Layer for UserRole model."""
    
    @staticmethod
    def get_user_roles(user):
        """Get all roles for a user."""
        return UserRole.objects.filter(user=user)
    
    @staticmethod
    def get_users_with_role(role):
        """Get all users with a specific role."""
        return UserRole.objects.filter(role=role).select_related('user')
    
    @staticmethod
    def add_role_to_user(user, role):
        """Add a role to a user."""
        user_role, created = UserRole.objects.get_or_create(
            user=user,
            role=role
        )
        return user_role, created
    
    @staticmethod
    def remove_role_from_user(user, role):
        """Remove a role from a user."""
        try:
            user_role = UserRole.objects.get(user=user, role=role)
            user_role.delete()
            return True
        except UserRole.DoesNotExist:
            return False
    
    @staticmethod
    def has_role(user, role):
        """Check if a user has a specific role."""
        return UserRole.objects.filter(user=user, role=role).exists()
    
    @staticmethod
    def is_admin(user):
        """Check if a user is an admin."""
        return UserRoleDAL.has_role(user, UserRole.RoleChoices.ADMIN)
    
    @staticmethod
    def is_kol(user):
        """Check if a user is a KOL."""
        return UserRoleDAL.has_role(user, UserRole.RoleChoices.KOL)
    
    @staticmethod
    def is_admin_or_kol(user):
        """Check if a user is an admin or KOL."""
        return UserRole.objects.filter(
            user=user, 
            role__in=[UserRole.RoleChoices.ADMIN, UserRole.RoleChoices.KOL]
        ).exists()


class InviteCodeDAL:
    """Data Access Layer for InviteCode model."""
    
    @staticmethod
    def get_invite_codes_by_user(user):
        """Get all invite codes created by a user."""
        return InviteCode.objects.filter(created_by=user).order_by('-created_at')
    
    @staticmethod
    def get_active_invite_codes_by_user(user):
        """Get all active invite codes created by a user."""
        return InviteCode.objects.filter(
            created_by=user,
            status=InviteCode.StatusChoices.ACTIVE,
            expires_at__gt=timezone.now()
        ).order_by('-created_at')
    
    @staticmethod
    def get_invite_code_by_code(code):
        """Get an invite code by its code."""
        try:
            return InviteCode.objects.get(code=code)
        except InviteCode.DoesNotExist:
            return None
    
    @staticmethod
    def is_valid_invite_code(code):
        """Check if an invite code is valid."""
        invite_code = InviteCodeDAL.get_invite_code_by_code(code)
        if invite_code:
            return invite_code.is_valid()
        return False
        
    @staticmethod
    def count_daily_invite_codes(user):
        """Count the number of invite codes created by a user today."""
        today = timezone.localtime(timezone.now()).date()
        today_start = timezone.make_aware(datetime.combine(today, time.min))
        today_end = timezone.make_aware(datetime.combine(today, time.max))
        
        return InviteCode.objects.filter(
            created_by=user,
            created_at__range=(today_start, today_end)
        ).count()
        
class OptimizationResultDAO:
    """Data Access Object for optimization results"""
    
    @staticmethod
    def create_result(result_data: dict) -> OptimizationResult:
        """Create new optimization record"""
        with transaction.atomic():
            return OptimizationResult.objects.create(
                from_protocol=result_data["from_protocol"],
                to_protocol=result_data["to_protocol"],
                amount_usd=result_data["amount_usd"],
                current_apr_from=result_data["current_apr_from"],
                current_apr_to=result_data["current_apr_to"],
                projected_apr=result_data["projected_apr"],
                utilization_from=result_data["utilization_from"],
                utilization_to=result_data["utilization_to"],
                extra_yield_bps=result_data["extra_yield_bps"],
                notes=result_data.get("notes", "")
            )
    
    @staticmethod
    def get_latest_results(limit=10):
        """Get most recent optimization results"""
        return OptimizationResult.objects.all().order_by('-timestamp')[:limit]

class YieldReportDAL:
    """
    Data Access Layer for YieldReport model.
    """
    @staticmethod
    def create_yield_report(token, protocol, apy, tvl, token_address=None, pool_address=None, is_current_best=False,params="{}"):
        """
        Creates a new yield report entry.

        Args:
            token (str): The token symbol.
            protocol (str): The protocol name.
            apy (Decimal): The Annual Percentage Yield.
            tvl (Decimal): The Total Value Locked.
            token_address (str, optional): The token's contract address. Defaults to None.
            is_current_best (bool, optional): If it's the best APY for the token. Defaults to False.

        Returns:
            YieldReport: The newly created YieldReport object.
        """
        report = YieldReport.objects.create(
            token=token,
            protocol=protocol,
            apy=apy,
            tvl=tvl,
            token_address=token_address,
            pool_address=pool_address,
            is_current_best=is_current_best,
            params=params 
        )
        return report

    @staticmethod
    def get_latest_reports_by_token():
        """
        Retrieves the most recent report for each token.

        Returns:
            QuerySet: A QuerySet of the latest YieldReport objects for each token.
        """
        latest_reports = YieldReport.objects.distinct('token').order_by('token', '-created_at')
        return latest_reports

    @staticmethod
    def get_all_reports():
        """
        Retrieves all yield reports, ordered by creation date.

        Returns:
            QuerySet: A QuerySet of all YieldReport objects.
        """
        return YieldReport.objects.all().order_by('-created_at')
    
    @staticmethod
    def get_formatted_latest_yields():
        """
        Retrieves the latest yield data for all tokens and formats it
        for agent consumption, identifying the best protocol for each token.

        Returns:
            dict: A dictionary where keys are token symbols. Each value is
                  another dictionary containing a list of all protocol reports
                  and a 'current_best' key with the name of the top protocol.
        """
        # Get the timestamp of the most recent report entry
        try:
            latest_run_time = YieldReport.objects.latest('created_at').created_at
        except YieldReport.DoesNotExist:
            return {} # Return empty dict if there's no data

        # Fetch all reports from that specific timestamp
        latest_reports = YieldReport.objects.filter(created_at=latest_run_time)

        # Structure the data for the agent
        formatted_data = {}
        for report in latest_reports:
            token = report.token
            if token not in formatted_data:
                formatted_data[token] = {
                    'reports': [],
                    'current_best': None
                }
            
            # Add the report for the protocol
            formatted_data[token]['reports'].append({
                'protocol': report.protocol,
                'apy': report.apy,
                'tvl': report.tvl,
                'pool_address': report.pool_address
            })

            # If this is the best one, set the 'current_best' field
            if report.is_current_best:
                formatted_data[token]['current_best'] = report.protocol
        
        return formatted_data
