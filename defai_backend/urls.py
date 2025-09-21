"""
URL configuration for defai project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from data.views import AgentViewSet, UserViewSet, WithdrawalViewSet, CreditRequestViewSet, health_check, update_agent_balances, global_dashboard, get_active_agent_ids, admin_deactivate_agents, admin_view_credit_requests, admin_approve_credit_request, get_agent_pnl_graph_data, get_latest_agent_thoughts, VaultRebalanceViewSet
from data.views.docs_view import api_docs_redirect, api_docs_index
from data.views.index_view import index_view
from data.views.redirect_views import api_root_redirect
from data.views.role_views import UserRoleViewSet, InviteCodeViewSet
from data.views.optimization_views import get_recent_pool_apy_results
from data.views.yield_monitor_views import get_yield_monitor_status, get_yield_monitor_history, get_pool_performance, get_daily_metrics, get_latest_vault_price, get_vault_price_chart_data
from data.views.vault_views import VaultDepositViewSet, VaultWithdrawalViewSet
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

# Create a router and register our viewsets with it
router = DefaultRouter()
# router.register(r'agent', AgentViewSet, basename='agent')
router.register(r'user', UserViewSet, basename='user')
# router.register(r'withdrawals', WithdrawalViewSet, basename='withdrawal')
# router.register(r'credit-requests', CreditRequestViewSet, basename='credit-request')
router.register(r'roles', UserRoleViewSet, basename='role')
# router.register(r'invite-codes', InviteCodeViewSet, basename='invite-code')
# Removed old rebalancing-trades endpoint - now using vault/rebalances
router.register(r'vault/deposits', VaultDepositViewSet, basename='vault-deposit')
router.register(r'vault/withdrawals', VaultWithdrawalViewSet, basename='vault-withdrawal')
router.register(r'vault/rebalances', VaultRebalanceViewSet, basename='vault-rebalance')

urlpatterns = [
    path('', index_view, name='index'),
    path('admin/', admin.site.urls),
    path('api/', api_root_redirect, name='api-root-redirect'),  # Redirect /api/ to /api/docs/
    path('api/', include(router.urls)),
    path('api/health/', health_check, name='health_check'),
    path('api/pool-apy/', get_recent_pool_apy_results, name='get_recent_pool_apy_results'),
    path('api/agent-thoughts/', get_latest_agent_thoughts, name='get_latest_agent_thoughts'),
    # path('api/update-balances/', update_agent_balances, name='update_agent_balances'),
    # path('api/dashboard/', global_dashboard, name='global_dashboard'),
    # path('api/active-agent-ids/', get_active_agent_ids, name='get_active_agent_ids'),
    # path('api/agent-pnl-graph/', get_agent_pnl_graph_data, name='get_agent_pnl_graph_data'),
    # path('api/admin/deactivate-agents/', admin_deactivate_agents, name='admin_deactivate_agents'),
    # path('api/admin/credit-requests/', admin_view_credit_requests, name='admin_view_credit_requests'),
    # path('api/admin/approve-credit-request/', admin_approve_credit_request, name='admin_approve_credit_request'),
    
    # Yield Monitor API endpoints
    path('api/yield-monitor/status/', get_yield_monitor_status, name='get_yield_monitor_status'),
    path('api/yield-monitor/history/', get_yield_monitor_history, name='get_yield_monitor_history'),
    path('api/yield-monitor/pool-performance/', get_pool_performance, name='get_pool_performance'),
    path('api/yield-monitor/daily-metrics/', get_daily_metrics, name='get_daily_metrics'),
    
    # Vault Price API endpoints
    path('api/vault/price/', get_latest_vault_price, name='get_latest_vault_price'),
    path('api/vault/price-chart/', get_vault_price_chart_data, name='get_vault_price_chart_data'),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    path('api/docs', api_docs_redirect, name='api-docs-redirect'),  # Handle missing trailing slash
    path('api/documentation/', api_docs_index, name='api-docs-index'),
]

# Serve media files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Configure custom error handlers
handler404 = 'data.views.error_views.handler404'
