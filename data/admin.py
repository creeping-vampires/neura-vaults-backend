from django.contrib import admin
from .models import User, Agent, AgentWallet, AgentFunds, AgentTrade, UserCredits, Withdrawal, Thought, UserRole, InviteCode

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('privy_address', 'is_active', 'is_deleted', 'deleted_at', 'created_at', 'updated_at', 'description')
    list_filter = ('is_active', 'is_deleted', 'created_at')
    search_fields = ('privy_address', 'description')
    readonly_fields = ('created_at', 'updated_at', 'is_deleted', 'deleted_at')
    ordering = ('-created_at',)

    def get_queryset(self, request):
        """Show all users including deleted ones in admin."""
        return User.all_objects.all()

@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'base_token', 'trade_frequency', 'is_deleted', 'deleted_at')
    list_filter = ('is_deleted', 'base_token', 'trade_frequency', 'llm_model', 'trading_system')
    search_fields = ('name', 'user__privy_address', 'strategy_description')
    readonly_fields = ('is_deleted', 'deleted_at')
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'profile_image')
        }),
        ('Trading Configuration', {
            'fields': ('base_token', 'min_trade_size', 'max_trade_size', 'whitelist_presets', 'trade_frequency')
        }),
        ('Strategy Details', {
            'fields': ('strategy_description', 'detailed_instructions')
        }),
        ('System Configuration', {
            'fields': ('llm_model', 'trading_system')
        }),
        ('Deletion Status', {
            'fields': ('is_deleted', 'deleted_at'),
            'classes': ('collapse',)
        })
    )

    def get_queryset(self, request):
        """Show all agents including deleted ones in admin."""
        return Agent.all_objects.all()

@admin.register(AgentWallet)
class AgentWalletAdmin(admin.ModelAdmin):
    list_display = ('agent_name', 'address')
    search_fields = ('agent__name', 'address')

    def agent_name(self, obj):
        return obj.agent.name
    agent_name.short_description = 'Agent Name'

@admin.register(AgentFunds)
class AgentFundsAdmin(admin.ModelAdmin):
    list_display = ('agent_name', 'token_symbol', 'amount', 'wallet_address')
    list_filter = ('token_symbol',)
    search_fields = ('wallet__agent__name', 'token_symbol', 'token_name')

    def agent_name(self, obj):
        return obj.wallet.agent.name
    agent_name.short_description = 'Agent Name'

    def wallet_address(self, obj):
        return obj.wallet.address
    wallet_address.short_description = 'Wallet Address'

@admin.register(AgentTrade)
class AgentTradeAdmin(admin.ModelAdmin):
    list_display = ('agent_name', 'from_token', 'to_token', 'from_amount', 'to_amount', 'amount_usd', 'from_price', 'to_price', 'transaction_hash', 'created_at')
    list_filter = ('from_token', 'to_token', 'created_at')
    search_fields = ('agent__name', 'from_token', 'to_token', 'transaction_hash')
    readonly_fields = ('created_at',)

    def agent_name(self, obj):
        return obj.agent.name
    agent_name.short_description = 'Agent Name'

@admin.register(UserCredits)
class UserCreditsAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('user__privy_address',)
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_email', 'agent_name', 'token_symbol', 'amount', 'status', 'created_at')
    list_filter = ('status', 'token_symbol', 'created_at')
    search_fields = ('user__email', 'agent__name', 'trx_hash', 'token_symbol')
    readonly_fields = ('created_at', 'updated_at', 'token_symbol')
    list_select_related = ('user', 'agent', 'fund')
    ordering = ('-created_at',)
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'
    user_email.admin_order_field = 'user__email'
    
    def agent_name(self, obj):
        return obj.agent.name
    agent_name.short_description = 'Agent Name'
    agent_name.admin_order_field = 'agent__name'

@admin.register(Thought)
class ThoughtAdmin(admin.ModelAdmin):
    list_display = ('thoughtId', 'agent', 'agent_role', 'createdAt', 'thought')
    list_filter = ('agent_role', 'createdAt')
    search_fields = ('thought', 'agent__name')
    ordering = ('-createdAt',)
    readonly_fields = ('thoughtId', 'createdAt')


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'created_at', 'updated_at')
    list_filter = ('role', 'created_at')
    search_fields = ('user__privy_address', 'role')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'created_by', 'creator_role', 'redeemable_credits', 'assign_kol_role', 'status', 'redeemed_by', 'redeemed_at', 'created_at', 'expires_at')
    list_filter = ('status', 'creator_role', 'assign_kol_role', 'created_at')
    search_fields = ('code', 'created_by__privy_address', 'redeemed_by__privy_address')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
