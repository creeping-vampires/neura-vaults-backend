from django.db import models
from django.utils import timezone
from django.conf import settings


class User(models.Model):
    """Model for storing users."""
    privy_address = models.CharField(max_length=255, unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.privy_address

    class Meta:
        default_manager_name = 'objects'
        base_manager_name = 'objects'

    objects = models.Manager()  # Default manager that filters out deleted users
    all_objects = models.Manager().from_queryset(models.QuerySet)()  # Manager that includes deleted users

    def delete(self, *args, **kwargs):
        """Soft delete the user and all their agents."""
        # Soft delete all associated agents
        for agent in self.agents.all():
            agent.delete()  # This will call Agent's soft delete method
        
        # Soft delete the user
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()


class Agent(models.Model):
    """Custom AI trading agent associated with a user."""
    # Status choices for the agent
    class StatusChoices(models.TextChoices):
        IDLE = 'idle', 'Idle'
        RUNNING = 'running', 'Running'
        PAUSED = 'paused', 'Paused'
        DELETED = 'deleted', 'Deleted'
    
    # Trading system choices for the agent
    class TradingSystemChoices(models.TextChoices):
        VALUE = 'value', 'Value'
        SWING = 'swing', 'Swing'
        SCALPER = 'scalper', 'Scalper'
        CUSTOM = 'custom', 'Custom'
        UNIT_FARMER = 'unit_farmer', 'Unit Farmer'
        
    # Risk profile choices for the agent
    class RiskProfileChoices(models.TextChoices):
        CONSERVATIVE = 'conservative', 'Conservative'
        MODERATE = 'moderate', 'Moderate'
        HIGH_RISK = 'highRisk', 'High Risk'
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agents')
    name = models.CharField(max_length=100)
    profile_image = models.ImageField(upload_to='agent_profiles/', blank=True, null=True)

    base_token = models.CharField(max_length=100)
    min_trade_size = models.DecimalField(max_digits=20, decimal_places=8)
    max_trade_size = models.DecimalField(max_digits=20, decimal_places=8)
    min_stable_size = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    max_stable_size = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    whitelist_presets = models.TextField(help_text="Serialized list of whitelisted presets")
    trade_frequency = models.IntegerField(help_text="Trade frequency in minutes")
    strategy_description = models.TextField()
    detailed_instructions = models.TextField()
    llm_model = models.CharField(max_length=100)
    risk_profile = models.CharField(
        max_length=20,
        choices=RiskProfileChoices.choices,
        null=True,
        blank=True,
        help_text="Risk profile: conservative, moderate, or high risk"
    )
    trading_system = models.CharField(
        max_length=20,
        choices=TradingSystemChoices.choices,
        help_text="Trading system type: value, swing, or scalper"
    )
    status = models.CharField(
        max_length=10,
        choices=StatusChoices.choices,
        default=StatusChoices.IDLE,
        help_text="Current status of the agent"
    )
    version = models.IntegerField(default=1, help_text="Agent version number")
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} (User: {self.user.privy_address})"

    class Meta:
        default_manager_name = 'objects'
        base_manager_name = 'objects'

    objects = models.Manager()  # Default manager that filters out deleted agents
    all_objects = models.Manager().from_queryset(models.QuerySet)()  # Manager that includes deleted agents

    def delete(self, *args, **kwargs):
        """Soft delete the agent."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save()


class AgentWallet(models.Model):
    """Wallet associated with an agent."""
    agent = models.OneToOneField(Agent, on_delete=models.CASCADE, related_name='wallet')
    address = models.CharField(max_length=255)
    wallet_id = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Wallet for {self.agent.name}"


class Withdrawal(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='withdrawals', null=False, blank=False)
    agent = models.ForeignKey('Agent', on_delete=models.CASCADE, related_name='withdrawals')
    fund = models.ForeignKey('AgentFunds', on_delete=models.CASCADE, related_name='withdrawals')
    amount = models.DecimalField(max_digits=36, decimal_places=18, help_text='Decimal formatted value of the token')
    amount_wei = models.DecimalField(max_digits=78, decimal_places=0, help_text='Raw amount received in request body (wei)', null=True)
    usd_value = models.DecimalField(default=0, max_digits=78, decimal_places=10, help_text='USD value of the token', null=True)
    token_symbol = models.CharField(max_length=20)
    to_address = models.CharField(max_length=42, blank=True, null=True, help_text='Ethereum address to withdraw funds to')
    status = models.CharField(max_length=10, choices=StatusChoices.choices, default=StatusChoices.PENDING)
    trx_hash = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Withdrawal {self.id} - {self.amount} {self.token_symbol} - {self.status}"

    class Meta:
        ordering = ['-created_at']


class AgentFunds(models.Model):
    """Funds in the agent's wallet."""
    wallet = models.ForeignKey(AgentWallet, on_delete=models.CASCADE, related_name='funds')
    token_name = models.CharField(max_length=100)
    token_symbol = models.CharField(max_length=20)
    token_address = models.CharField(max_length=255, blank=True, null=True)
    amount = models.DecimalField(max_digits=30, decimal_places=10)
    decimals = models.IntegerField(default=18, help_text='Number of decimal places for the token')
    is_active = models.BooleanField(default=True, help_text='Whether this fund entry is active')

    def __str__(self):
        return f"{self.token_symbol} in {self.wallet.agent.name}'s wallet"


class PortfolioSnapshot(models.Model):
    """
    Historical snapshot of an agent's portfolio value for PNL calculations.
    """
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='portfolio_snapshots')
    timestamp = models.DateTimeField()
    total_usd_value = models.DecimalField(max_digits=30, decimal_places=10)
    token_values_json = models.TextField()  # JSON string of token values
    
    # PNL fields
    absolute_pnl_usd = models.DecimalField(default=0, max_digits=30, decimal_places=10, null=True, blank=True)
    percentage_pnl = models.DecimalField(default=0, max_digits=30, decimal_places=10, null=True, blank=True)
    total_deposits = models.DecimalField(default=0, max_digits=30, decimal_places=10, null=True, blank=True)
    total_withdrawals = models.DecimalField(default=0, max_digits=30, decimal_places=10, null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['agent', 'timestamp']),
        ]
    
    def __str__(self):
        return f"Portfolio snapshot for {self.agent.name} at {self.timestamp}"


class AgentTrade(models.Model):
    """Record of a trade made by an agent."""
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='trades')
    from_token = models.CharField(max_length=50)
    to_token = models.CharField(max_length=50)
    amount_usd = models.DecimalField(max_digits=20, decimal_places=2)
    from_amount = models.DecimalField(max_digits=20, decimal_places=2)
    to_amount = models.DecimalField(max_digits=20, decimal_places=2)
    from_price = models.DecimalField(max_digits=20, decimal_places=2)
    to_price = models.DecimalField(max_digits=20, decimal_places=2)
    transaction_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Trade by {self.agent.name}: {self.from_token} → {self.to_token}"


class VaultPrice(models.Model):
    """
    Stores vault price data including highest pool APY and share price.
    """
    vault_address = models.CharField(max_length=42)
    token = models.CharField(max_length=10)
    protocol = models.CharField(max_length=50, null=True, blank=True)
    pool_apy = models.DecimalField(max_digits=20, decimal_places=8, default=0)
    share_price = models.CharField(max_length=78)  # Raw share price (very large number)
    share_price_formatted = models.DecimalField(max_digits=20, decimal_places=8)  # Formatted for display
    total_assets = models.CharField(max_length=78)  # Raw total assets (very large number)
    total_supply = models.CharField(max_length=78)  # Raw total supply (very large number)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.token} - {self.created_at}"


class VaultDepositRun(models.Model):
    """
    Model to track each vault deposit worker run and its overall results.
    """
    class StatusChoices(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'
    
    status = models.CharField(max_length=10, choices=StatusChoices.choices)
    vault_address = models.CharField(max_length=42)
    asset_address = models.CharField(max_length=42)
    asset_symbol = models.CharField(max_length=10)
    asset_decimals = models.IntegerField(default=18)
    queue_length_before = models.IntegerField(default=0)
    queue_length_after = models.IntegerField(default=0)
    processed_count = models.IntegerField(default=0)
    batch_size = models.IntegerField(default=5)
    total_assets_to_deposit = models.CharField(max_length=78, default="0", help_text="Total assets to deposit in wei (stored as string to avoid numeric overflow)")
    idle_assets_before = models.CharField(max_length=78, default="0", help_text="Idle assets in vault before deposit in wei (stored as string to avoid numeric overflow)")
    best_pool_address = models.CharField(max_length=42, null=True, blank=True, help_text="Address of the best pool selected for deposit")
    best_pool_name = models.CharField(max_length=50, null=True, blank=True, help_text="Name of the best protocol/pool selected for deposit")
    error_message = models.TextField(null=True, blank=True)
    execution_duration_seconds = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Vault Deposit Run {self.id} - {self.created_at} - {self.status}"


class VaultDepositTransaction(models.Model):
    """
    Model to track individual transactions from vault deposit runs.
    """
    class StatusChoices(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'
    
    run = models.ForeignKey(VaultDepositRun, on_delete=models.CASCADE, related_name='transactions')
    transaction_hash = models.CharField(max_length=66)  # 0x + 64 hex chars
    gas_used = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=StatusChoices.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Tx {self.transaction_hash[:10]}... - {self.status}"


class VaultWithdrawalRun(models.Model):
    """
    Model to track each vault withdrawal worker run and its overall results.
    """
    class StatusChoices(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        SKIPPED = 'skipped', 'Skipped'
    
    status = models.CharField(max_length=10, choices=StatusChoices.choices)
    vault_address = models.CharField(max_length=42)
    queue_length_before = models.IntegerField(default=0)
    queue_length_after = models.IntegerField(default=0)
    processed_count = models.IntegerField(default=0)
    batch_size = models.IntegerField(default=5)
    total_withdrawal_amount = models.BigIntegerField(default=0, help_text="Total amount withdrawn in token units")
    total_withdrawal_amount_formatted = models.DecimalField(max_digits=30, decimal_places=18, default=0, help_text="Total amount withdrawn in human-readable format")
    asset_symbol = models.CharField(max_length=10, default="USDe", help_text="Token symbol")
    asset_decimals = models.IntegerField(default=18, help_text="Token decimals")
    error_message = models.TextField(null=True, blank=True)
    execution_duration_seconds = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Vault Withdrawal Run {self.id} - {self.created_at} - {self.status}"


class VaultWithdrawalTransaction(models.Model):
    """
    Model to track individual transactions from vault withdrawal runs.
    """
    class StatusChoices(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        PENDING = 'pending', 'Pending'
    
    run = models.ForeignKey(VaultWithdrawalRun, on_delete=models.CASCADE, related_name='transactions')
    transaction_hash = models.CharField(max_length=66)  # 0x + 64 hex chars
    gas_used = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=StatusChoices.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Tx {self.transaction_hash[:10]}... - {self.status}"


class UserCredits(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='credits')
    balance = models.IntegerField(default=settings.DEFAULT_USER_CREDITS)  # Default 2 credits
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.privy_address} - {self.balance} credits"

    class Meta:
        verbose_name = "User Credits"
        verbose_name_plural = "User Credits"


class CreditRequest(models.Model):
    """Model for storing credit requests from users."""
    class StatusChoices(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='credit_requests')
    privy_id = models.CharField(max_length=255, db_index=True, null=True, blank=True, help_text="Privy ID of the user making the request")
    twitter_handle = models.CharField(max_length=255)
    status = models.CharField(
        max_length=10,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING
    )
    credits_requested = models.IntegerField(default=1)
    credits_granted = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Credit Request by {self.user.privy_address} - {self.twitter_handle} - {self.status}"

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Credit Request"
        verbose_name_plural = "Credit Requests"


class Thought(models.Model):
    thoughtId = models.AutoField(primary_key=True)
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='thoughts', null=True, blank=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    thought = models.TextField(null=False, blank=False)
    agent_role = models.CharField(max_length=255, blank=False, null=False)

    def __str__(self):
        agent_name = self.agent.name if self.agent else "Agent-Agnostic"
        return f"Thought by {agent_name} in {self.agent_role}"


class AgnosticThought(models.Model):
    """
    Stores thoughts from agent-agnostic mode (when no specific agent is associated).
    This table is separate from the main Thought table to provide clear separation
    between agent-specific and agent-agnostic thoughts.
    """
    thoughtId = models.AutoField(primary_key=True)
    createdAt = models.DateTimeField(auto_now_add=True)
    thought = models.TextField(null=False, blank=False)
    agent_role = models.CharField(max_length=255, blank=False, null=False)
    
    # Additional fields for better monitoring and debugging
    execution_mode = models.CharField(max_length=50, default='agent-agnostic', null=False)
    crew_id = models.CharField(max_length=255, null=True, blank=True)  # For tracking crew execution
    
    class Meta:
        db_table = 'data_agnosticthought'
        ordering = ['-createdAt']
    
    def __str__(self):
        return f"Agnostic Thought by {self.agent_role} at {self.createdAt}"


class CapitalFlow(models.Model):
    """
    Tracks capital flows (deposits and withdrawals) for agents.
    Used for accurate PNL calculations.
    """
    FLOW_TYPE_CHOICES = [
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
    ]
    agent = models.ForeignKey(Agent, on_delete=models.CASCADE, related_name='capital_flows')
    timestamp = models.DateTimeField(auto_now_add=True)
    flow_type = models.CharField(max_length=20, choices=FLOW_TYPE_CHOICES)
    token_address = models.CharField(max_length=42)
    token_symbol = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=30, decimal_places=10)
    usd_value = models.DecimalField(max_digits=30, decimal_places=10)
    transaction_hash = models.CharField(max_length=66, null=True, blank=True)
    detected_from_snapshot = models.ForeignKey(PortfolioSnapshot, null=True, blank=True, 
                                             on_delete=models.SET_NULL, related_name='detected_flows')
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['transaction_hash'],
                condition=models.Q(flow_type='deposit', transaction_hash__isnull=False),
                name='unique_deposit_transaction_hash'
            )
        ]
        indexes = [
            models.Index(fields=['agent', 'timestamp']),
            models.Index(fields=['agent', 'flow_type']),
        ]
    
    def __str__(self):
        return f"{self.flow_type.capitalize()} of {self.amount} {self.token_symbol} for {self.agent.name}"


class UserRole(models.Model):
    """Model for storing user roles."""
    class RoleChoices(models.TextChoices):
        USER = 'user', 'User'
        KOL = 'kol', 'KOL'
        ADMIN = 'admin', 'Admin'
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='roles')
    role = models.CharField(
        max_length=20,
        choices=RoleChoices.choices,
        default=RoleChoices.USER
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'role')
        verbose_name = "User Role"
        verbose_name_plural = "User Roles"

    def __str__(self):
        return f"{self.user.privy_address} - {self.get_role_display()}"


class InviteCode(models.Model):
    """Model for storing invite codes."""
    class StatusChoices(models.TextChoices):
        ACTIVE = 'active', 'Active'
        USED = 'used', 'Used'
        EXPIRED = 'expired', 'Expired'
    
    code = models.CharField(max_length=20, unique=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_invite_codes')
    creator_role = models.CharField(max_length=20, choices=UserRole.RoleChoices.choices)
    redeemable_credits = models.IntegerField()
    assign_kol_role = models.BooleanField(default=False)
    status = models.CharField(
        max_length=10,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE
    )
    redeemed_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name='redeemed_invite_codes',
        null=True,
        blank=True
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Invite Code: {self.code} ({self.get_status_display()})"

    def is_valid(self):
        """Check if the invite code is valid (active and not expired)."""
        if self.status != self.StatusChoices.ACTIVE:
            return False
        if self.expires_at and self.expires_at < timezone.now():
            self.status = self.StatusChoices.EXPIRED
            self.save()
            return False
        return True

    def redeem(self, user):
        """Redeem the invite code for a user."""
        if not self.is_valid():
            return False
        
        self.status = self.StatusChoices.USED
        self.redeemed_by = user
        self.redeemed_at = timezone.now()
        self.save()
        
        # Add credits to the user
        from .data_access_layer import UserCreditsDAL
        UserCreditsDAL.add_credits(user, self.redeemable_credits)
        
        # If this is an admin-generated code that assigns KOL role
        if self.assign_kol_role:
            UserRole.objects.get_or_create(
                user=user,
                role=UserRole.RoleChoices.KOL
            )
        
        return True


class OptimizationResult(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    from_protocol = models.CharField(max_length=100)
    to_protocol = models.CharField(max_length=100)
    amount_usd = models.DecimalField(max_digits=20, decimal_places=2)
    current_apr_from = models.FloatField()
    current_apr_to = models.FloatField()
    projected_apr = models.FloatField()
    utilization_from = models.FloatField()
    utilization_to = models.FloatField()
    extra_yield_bps = models.FloatField()
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'poolApy'
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['from_protocol', 'to_protocol']),
        ]

    def __str__(self):
        return f"{self.timestamp} - {self.from_protocol}→{self.to_protocol}"


class YieldMonitorRun(models.Model):
    """
    Model to track each yield monitor worker run and its overall results.
    """
    class StatusChoices(models.TextChoices):
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
        PARTIAL = 'partial', 'Partial Success'
        SKIPPED = 'skipped', 'Skipped'

    # Run metadata
    timestamp = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=StatusChoices.choices)
    
    # Vault-level information
    vault_address = models.CharField(max_length=42, help_text="YieldAllocatorVault contract address")
    asset_address = models.CharField(max_length=42, help_text="Asset token contract address")
    asset_symbol = models.CharField(max_length=20, help_text="Asset token symbol")
    asset_decimals = models.IntegerField(help_text="Asset token decimals")
    
    # Yield calculation results
    total_principal_deposited = models.DecimalField(
        max_digits=78, decimal_places=0, 
        help_text="Total principal deposited across all pools (in wei)"
    )
    current_total_value = models.DecimalField(
        max_digits=78, decimal_places=0,
        help_text="Current total value of vault assets (in wei)"
    )
    total_yield_generated = models.DecimalField(
        max_digits=78, decimal_places=0,
        help_text="Total yield generated (current_value - principal) (in wei)"
    )
    total_yield_percentage = models.DecimalField(
        max_digits=10, decimal_places=6,
        help_text="Yield percentage (yield/principal * 100)"
    )
    idle_assets = models.DecimalField(
        max_digits=78, decimal_places=0,
        help_text="Idle assets in vault (in wei)"
    )
    
    # Execution results
    total_withdrawn = models.DecimalField(
        max_digits=78, decimal_places=0, default=0,
        help_text="Total amount withdrawn across all pools (in wei)"
    )
    total_reinvested = models.DecimalField(
        max_digits=78, decimal_places=0, default=0,
        help_text="Total amount reinvested across all pools (in wei)"
    )
    pools_processed = models.IntegerField(default=0, help_text="Number of pools processed")
    pools_with_yield = models.IntegerField(default=0, help_text="Number of pools that had yield claimed")
    
    # Thresholds and configuration used
    yield_threshold_used = models.DecimalField(
        max_digits=10, decimal_places=8,
        help_text="Yield threshold percentage used for this run"
    )
    min_claim_amount_usd = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Minimum claim amount in USD used for this run"
    )
    max_gas_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=2,
        help_text="Maximum gas cost in USD used for this run"
    )
    
    # Error information
    error_message = models.TextField(blank=True, null=True, help_text="Error message if run failed")
    
    # Execution time tracking
    execution_duration_seconds = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        help_text="Duration of the worker run in seconds"
    )
    
    def __str__(self):
        return f"YieldMonitorRun {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {self.status}"
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp']),
            models.Index(fields=['status']),
            models.Index(fields=['vault_address']),
        ]


class YieldMonitorPoolSnapshot(models.Model):
    """
    Model to track individual pool information for each yield monitor run.
    """
    # Link to the parent run
    monitor_run = models.ForeignKey(
        YieldMonitorRun, 
        on_delete=models.CASCADE, 
        related_name='pool_snapshots'
    )
    
    # Pool information
    pool_address = models.CharField(max_length=42, help_text="Pool contract address")
    pool_name = models.CharField(max_length=100, blank=True, null=True, help_text="Pool name if available")
    
    # Pool financial data at time of run
    principal_deposited = models.DecimalField(
        max_digits=78, decimal_places=0,
        help_text="Principal amount deposited in this pool (in wei)"
    )
    principal_percentage = models.DecimalField(
        max_digits=10, decimal_places=6,
        help_text="Percentage of total principal this pool represents"
    )
    
    # Yield calculation for this pool
    calculated_yield_share = models.DecimalField(
        max_digits=78, decimal_places=0, default=0,
        help_text="This pool's calculated share of total yield (in wei)"
    )
    yield_percentage = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text="Yield percentage for this pool"
    )
    
    # Pool processing results
    was_processed = models.BooleanField(default=False, help_text="Whether this pool was processed for yield claiming")
    skip_reason = models.TextField(blank=True, null=True, help_text="Reason why pool was skipped if not processed")
    
    def __str__(self):
        return f"Pool {self.pool_address[:10]}... - {self.monitor_run.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
    
    class Meta:
        ordering = ['-monitor_run__timestamp', 'pool_address']
        indexes = [
            models.Index(fields=['pool_address']),
            models.Index(fields=['monitor_run', 'pool_address']),
        ]


class YieldMonitorTransaction(models.Model):
    """
    Model to track individual transactions (withdrawals and deposits) for each pool.
    """
    class TransactionType(models.TextChoices):
        WITHDRAWAL = 'withdrawal', 'Withdrawal'
        DEPOSIT = 'deposit', 'Deposit'
    
    class TransactionStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESS = 'success', 'Success'
        FAILED = 'failed', 'Failed'
    
    # Link to the parent run and pool
    monitor_run = models.ForeignKey(
        YieldMonitorRun, 
        on_delete=models.CASCADE, 
        related_name='transactions'
    )
    pool_snapshot = models.ForeignKey(
        YieldMonitorPoolSnapshot,
        on_delete=models.CASCADE,
        related_name='transactions'
    )
    
    # Transaction details
    transaction_type = models.CharField(max_length=10, choices=TransactionType.choices)
    transaction_hash = models.CharField(max_length=66, help_text="Ethereum transaction hash")
    block_number = models.BigIntegerField(null=True, blank=True, help_text="Block number where transaction was mined")
    
    # Transaction amounts
    amount_wei = models.DecimalField(
        max_digits=78, decimal_places=0,
        help_text="Transaction amount in wei"
    )
    amount_formatted = models.DecimalField(
        max_digits=30, decimal_places=18,
        help_text="Transaction amount in human-readable format"
    )
    
    # Transaction execution details
    gas_used = models.BigIntegerField(null=True, blank=True, help_text="Gas used for the transaction")
    gas_price_wei = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True,
        help_text="Gas price used for the transaction (in wei)"
    )
    transaction_cost_usd = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Estimated transaction cost in USD"
    )
    
    # Status and timing
    status = models.CharField(max_length=10, choices=TransactionStatus.choices, default=TransactionStatus.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    
    # Error information
    error_message = models.TextField(blank=True, null=True, help_text="Error message if transaction failed")
    
    def __str__(self):
        return f"{self.transaction_type} - {self.transaction_hash[:10]}... - {self.amount_formatted} {self.monitor_run.asset_symbol}"
    
    class Meta:
        ordering = ['-submitted_at']
        indexes = [
            models.Index(fields=['transaction_hash']),
            models.Index(fields=['monitor_run', 'transaction_type']),
            models.Index(fields=['pool_snapshot', 'transaction_type']),
            models.Index(fields=['status']),
        ]


class VaultRebalance(models.Model):
    """
    Model to track vault rebalancing operations, including both withdrawal and deposit transactions.
    """
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'
    STATUS_CHOICES = [
        (PENDING, 'Pending'),
        (COMPLETED, 'Completed'),
        (FAILED, 'Failed'),
    ]
    
    WITHDRAWAL = 'withdrawal'
    DEPOSIT = 'deposit'
    TRANSACTION_TYPE_CHOICES = [
        (WITHDRAWAL, 'Withdrawal'),
        (DEPOSIT, 'Deposit'),
    ]
    
    # Rebalance operation details
    rebalance_id = models.CharField(max_length=64, help_text="Unique ID for the rebalance operation")
    transaction_type = models.CharField(
        max_length=20, 
        choices=TRANSACTION_TYPE_CHOICES,
        help_text="Type of transaction: withdrawal or deposit"
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES,
        default=PENDING,
        help_text="Status of the transaction"
    )
    
    # Protocol and pool information
    from_protocol = models.CharField(max_length=50, null=True, blank=True, help_text="Source protocol name")
    to_protocol = models.CharField(max_length=50, null=True, blank=True, help_text="Destination protocol name")
    from_pool_address = models.CharField(max_length=42, null=True, blank=True, help_text="Source pool address")
    to_pool_address = models.CharField(max_length=42, null=True, blank=True, help_text="Destination pool address")
    
    # Amount information
    amount_usd = models.DecimalField(
        max_digits=30, 
        decimal_places=18, 
        default=0,
        help_text="USD value of the transaction"
    )
    amount_token = models.DecimalField(
        max_digits=78, 
        decimal_places=18, 
        default=0,
        help_text="Token amount in decimal format"
    )
    amount_token_raw = models.CharField(
        max_length=78, 
        null=True, 
        blank=True,
        help_text="Raw token amount (wei)"
    )
    token_symbol = models.CharField(max_length=10, default="USDe", help_text="Token symbol")
    token_decimals = models.IntegerField(default=18, help_text="Token decimals")
    
    # Transaction details
    transaction_hash = models.CharField(max_length=66, null=True, blank=True, help_text="Transaction hash")
    block_number = models.IntegerField(null=True, blank=True, help_text="Block number where transaction was confirmed")
    gas_used = models.BigIntegerField(null=True, blank=True, help_text="Gas used for the transaction")
    gas_price = models.BigIntegerField(null=True, blank=True, help_text="Gas price in wei")
    
    # Error information
    error_message = models.TextField(null=True, blank=True, help_text="Error message if transaction failed")
    
    # Strategy summary
    strategy_summary = models.TextField(null=True, blank=True, help_text="AI-generated summary of the rebalancing strategy")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, help_text="When the record was created")
    updated_at = models.DateTimeField(auto_now=True, help_text="When the record was last updated")
    
    class Meta:
        db_table = 'vault_rebalance'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"{self.transaction_type} - {self.from_protocol} to {self.to_protocol} - {self.status}"


class YieldMonitorMetrics(models.Model):

    """
    Model to track aggregated metrics and performance over time.
    """
    # Time period for these metrics
    date = models.DateField(help_text="Date for these daily metrics")
    vault_address = models.CharField(max_length=42, help_text="YieldAllocatorVault contract address")
    
    # Daily aggregated metrics
    total_runs = models.IntegerField(default=0, help_text="Total number of worker runs")
    successful_runs = models.IntegerField(default=0, help_text="Number of successful runs")
    failed_runs = models.IntegerField(default=0, help_text="Number of failed runs")
    
    # Yield metrics
    total_yield_claimed = models.DecimalField(
        max_digits=78, decimal_places=0, default=0,
        help_text="Total yield claimed on this date (in wei)"
    )
    total_yield_reinvested = models.DecimalField(
        max_digits=78, decimal_places=0, default=0,
        help_text="Total yield reinvested on this date (in wei)"
    )
    average_yield_percentage = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text="Average yield percentage for the day"
    )
    
    # Transaction metrics
    total_transactions = models.IntegerField(default=0, help_text="Total number of transactions")
    total_gas_cost_usd = models.DecimalField(
        max_digits=15, decimal_places=2, default=0,
        help_text="Total gas costs in USD for the day"
    )
    
    # Performance metrics
    average_execution_time = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        help_text="Average execution time in seconds"
    )
    
    # Portfolio growth metrics
    vault_value_start = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True,
        help_text="Vault value at start of day (in wei)"
    )
    vault_value_end = models.DecimalField(
        max_digits=78, decimal_places=0, null=True, blank=True,
        help_text="Vault value at end of day (in wei)"
    )
    daily_growth_percentage = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text="Daily growth percentage"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Metrics {self.date} - {self.vault_address[:10]}..."
    
    class Meta:
        ordering = ['-date']
        unique_together = ['date', 'vault_address']
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['vault_address']),
        ]


class YieldReport(models.Model):
    """
    Stores yield comparison data from the bot.
    """
    token = models.CharField(max_length=50, help_text="The token symbol, e.g., HYPE, USDT0", null=True, blank=True)
    protocol = models.CharField(max_length=100, help_text="The protocol or pool name, e.g., HyperLend", null=True, blank=True)
    apy = models.DecimalField(max_digits=10, decimal_places=4, help_text="Annual Percentage Yield")
    tvl = models.DecimalField(max_digits=20, decimal_places=2, help_text="Total Value Locked")
    token_address = models.CharField(max_length=255, blank=True, null=True, help_text="The token's contract address")
    pool_address = models.CharField(max_length=255, blank=True, null=True, help_text="The protocol's pool contract address")
    is_current_best = models.BooleanField(default=False, help_text="Is this the best APY for this token in the report?")
    created_at = models.DateTimeField(auto_now_add=True)
    params = models.TextField(default="{}")

    def __str__(self):
        return f"{self.protocol} - {self.token}: {self.apy}%"

    class Meta:
        verbose_name = "Yield Report"
        verbose_name_plural = "Yield Reports"
        ordering = ['-created_at', 'token', '-apy']


class PoolAPR(models.Model):
    """
    Model to store APR/APY data for Nura Vault pools.
    Tracks historical APR/APY calculations for different pools.
    """
    # Pool identification
    pool_address = models.CharField(max_length=42, help_text="Pool/Vault contract address")
    pool_name = models.CharField(max_length=100, blank=True, null=True, help_text="Pool name if available")
    
    # Time period for calculation
    timestamp = models.DateTimeField(auto_now_add=True, help_text="When this APR was calculated")
    calculation_window_days = models.IntegerField(default=7, help_text="Number of days used for APR calculation")
    
    # Price per share data
    pps_start = models.DecimalField(max_digits=30, decimal_places=18, help_text="Price per share at start of window")
    pps_end = models.DecimalField(max_digits=30, decimal_places=18, help_text="Price per share at end of window")
    
    # Block information
    block_start = models.BigIntegerField(help_text="Block number at start of calculation window")
    block_end = models.BigIntegerField(help_text="Block number at end of calculation window")
    
    # Calculated rates
    period_return = models.DecimalField(max_digits=10, decimal_places=6, help_text="Period return as decimal (e.g., 0.05 for 5%)")
    apr = models.DecimalField(max_digits=10, decimal_places=6, help_text="Annualized Percentage Rate (simple interest)")
    apy = models.DecimalField(max_digits=10, decimal_places=6, help_text="Annual Percentage Yield (compound interest)")
    
    # Metadata
    rpc_url = models.CharField(max_length=500, blank=True, null=True, help_text="RPC URL used for calculation")
    calculation_status = models.CharField(
        max_length=20, 
        choices=[
            ('success', 'Success'),
            ('failed', 'Failed'),
            ('partial', 'Partial')
        ],
        default='success'
    )
    error_message = models.TextField(blank=True, null=True, help_text="Error message if calculation failed")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        if self.calculation_status == 'success':
            return f"{self.pool_name or self.pool_address[:10]}... - APR: {self.apr*100:.2f}% APY: {self.apy*100:.2f}% ({self.timestamp.strftime('%Y-%m-%d')})"
        else:
            return f"{self.pool_name or self.pool_address[:10]}... - Failed: {self.error_message[:50]}... ({self.timestamp.strftime('%Y-%m-%d')})"
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['pool_address', '-timestamp']),
            models.Index(fields=['calculation_status']),
            models.Index(fields=['-timestamp']),
        ]


class RebalancingTrade(models.Model):
    """Model to track yield allocation and rebalancing transactions.
    Stores details of each transaction executed through the execute_yield_allocation tool.
    """
    
    class TransactionType(models.TextChoices):
        DEPOSIT = 'DEPOSIT', 'Deposit'
        WITHDRAWAL = 'WITHDRAWAL', 'Withdrawal'
    
    class ScenarioType(models.TextChoices):
        IDLE_DEPLOYMENT = 'IDLE_DEPLOYMENT', 'Idle Deployment'
        REBALANCING = 'REBALANCING', 'Rebalancing'
    
    class TransactionStatus(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Success'
        FAILED = 'FAILED', 'Failed'
        PENDING = 'PENDING', 'Pending'
    
    # Basic transaction info
    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)
    scenario_type = models.CharField(max_length=20, choices=ScenarioType.choices)
    status = models.CharField(max_length=20, choices=TransactionStatus.choices)
    
    # Pool and protocol info
    pool_address = models.CharField(max_length=42, help_text="Pool contract address")
    protocol = models.CharField(max_length=100, help_text="Protocol name (e.g., Aave, HypurrFi)")
    
    # Amount information
    amount_wei = models.DecimalField(
        max_digits=78, decimal_places=0,
        help_text="Transaction amount in wei"
    )
    amount_formatted = models.DecimalField(
        max_digits=30, decimal_places=18,
        help_text="Transaction amount in human-readable format"
    )
    
    # Blockchain transaction details
    transaction_hash = models.CharField(max_length=66, blank=True, null=True, help_text="Ethereum transaction hash")
    block_number = models.BigIntegerField(blank=True, null=True, help_text="Block number where transaction was mined")
    executor_address = models.CharField(max_length=42, blank=True, null=True, help_text="Address that executed the transaction")
    
    # Gas information
    gas_used = models.BigIntegerField(blank=True, null=True, help_text="Gas used for the transaction")
    gas_cost_eth = models.DecimalField(
        max_digits=30, decimal_places=18, blank=True, null=True,
        help_text="Gas cost in ETH"
    )
    
    # Execution metadata
    allocation_index = models.IntegerField(blank=True, null=True, help_text="Index in the allocation array")
    execution_timestamp = models.DateTimeField(help_text="When the transaction was executed")
    error_message = models.TextField(blank=True, null=True, help_text="Error message if transaction failed")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        amount_str = f"{float(self.amount_formatted):.6f}" if self.amount_formatted else "0"
        return f"{self.transaction_type} - {amount_str} to {self.protocol} ({self.status})"
    
    class Meta:
        ordering = ['-execution_timestamp']
        indexes = [
            models.Index(fields=['scenario_type', '-execution_timestamp']),
            models.Index(fields=['transaction_type', '-execution_timestamp']),
            models.Index(fields=['status']),
            models.Index(fields=['pool_address']),
            models.Index(fields=['-execution_timestamp']),
        ]


class VaultPrice(models.Model):
    """
    Stores vault price data including highest pool APY and share price.
    """
    vault_address = models.CharField(max_length=255, help_text="The vault contract address")
    token = models.CharField(max_length=50, help_text="The token symbol, e.g., USDe, USDT0", null=True, blank=True)
    protocol = models.CharField(max_length=100, help_text="Protocol with highest APY, e.g., HyperLend, HypurrFi", null=True, blank=True)
    pool_apy = models.DecimalField(max_digits=10, decimal_places=4, help_text="Highest APY from YieldReport excluding Felix")
    share_price = models.CharField(max_length=78, help_text="Raw share price calculation (totalAssets * 10^18) / totalSupply as string")
    share_price_formatted = models.DecimalField(max_digits=20, decimal_places=8, help_text="Formatted share price for display")
    total_assets = models.CharField(max_length=78, help_text="Total assets in the vault as string")
    total_supply = models.CharField(max_length=78, help_text="Total supply of vault shares as string")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Vault {self.vault_address}: Share Price {self.share_price_formatted}"

    class Meta:
        verbose_name = "Vault Price"
        verbose_name_plural = "Vault Prices"
        ordering = ['-created_at']


class VaultAPY(models.Model):
    """
    Stores calculated 24-hour and 7-day APY values for vaults.
    """
    vault_address = models.CharField(max_length=255, help_text="The vault contract address")
    token = models.CharField(max_length=50, help_text="The token symbol, e.g., USDe, USDT0", null=True, blank=True)
    
    # 24-hour APY data
    apy_24h = models.DecimalField(max_digits=20, decimal_places=8, help_text="24-hour APY calculation")
    midnight_share_price = models.DecimalField(max_digits=20, decimal_places=8, help_text="Share price at midnight")
    current_share_price = models.DecimalField(max_digits=20, decimal_places=8, help_text="Current share price")
    
    # 7-day APY data
    apy_7d = models.DecimalField(max_digits=20, decimal_places=8, help_text="7-day APY calculation", null=True, blank=True)
    seven_day_share_price = models.DecimalField(max_digits=20, decimal_places=8, help_text="Share price from 7 days ago", null=True, blank=True)
    
    # Calculation metadata
    days_elapsed = models.DecimalField(max_digits=10, decimal_places=6, help_text="Days elapsed for calculation")
    exponential = models.DecimalField(max_digits=10, decimal_places=6, help_text="Exponential factor used in calculation")
    calculation_time = models.DateTimeField(auto_now_add=True, help_text="When this calculation was performed")
    
    def __str__(self):
        return f"Vault {self.vault_address}: 24h APY {self.apy_24h*100:.4f}%, 7d APY {self.apy_7d*100:.4f if self.apy_7d else 0}%"

    class Meta:
        verbose_name = "Vault APY"
        verbose_name_plural = "Vault APYs"
        ordering = ['-calculation_time']
        indexes = [
            models.Index(fields=['vault_address', '-calculation_time']),
            models.Index(fields=['-calculation_time']),
        ]