from .agent_views import AgentViewSet, admin_deactivate_agents, get_active_agent_ids, update_agent_balances, get_agent_pnl_graph_data
from .credit_request_views import CreditRequestViewSet, admin_view_credit_requests, admin_approve_credit_request
from .withdrawal_views import WithdrawalViewSet
from .dashboard_views import global_dashboard
from .health_views import health_check
from .authentication_views import UserViewSet, PrivyUser, PrivyUserRateThrottle, PrivyAuthenticationScheme
from .agent_thoughts_views import get_latest_agent_thoughts
from .utils import log_error
from .vault_views import VaultDepositViewSet, VaultWithdrawalViewSet
from .vault_rebalance_views import VaultRebalanceViewSet
from .error_views import handler404
from .index_view import index_view
from .docs_view import api_docs_redirect, api_docs_index
from .redirect_views import api_root_redirect

__all__ = [
    # ViewSets
    'AgentViewSet',
    'UserViewSet',
    'CreditRequestViewSet',
    'WithdrawalViewSet',
    # 'RebalancingTradeViewSet', # Removed - now using VaultRebalanceViewSet
    'VaultDepositViewSet',
    'VaultWithdrawalViewSet',
    'VaultRebalanceViewSet',
    
    # Standalone views
    'health_check',
    'global_dashboard',
    'admin_deactivate_agents',
    'get_active_agent_ids',
    'update_agent_balances',
    'admin_view_credit_requests',
    'admin_approve_credit_request',
    'get_agent_pnl_graph_data',
    'get_latest_agent_thoughts',
    
    # Authentication
    'PrivyUser',
    'PrivyUserRateThrottle',
    'PrivyAuthenticationScheme',
    
    # Utils
    'log_error',
    
    # Error handlers
    'handler404',
    
    # Documentation views
    'index_view',
    'api_docs_redirect',
    'api_docs_index',
    'api_root_redirect'
]
