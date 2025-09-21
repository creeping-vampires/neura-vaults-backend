"""
Cache utilities for the DefAI backend.
"""
import logging
from functools import wraps
from django.core.cache import cache
from django.utils.encoding import force_str
from rest_framework.response import Response

logger = logging.getLogger(__name__)

def cache_response(timeout=None, key_prefix='view'):
    """
    A simpler cache decorator that caches the data returned by the view function,
    not the Response object itself. This avoids issues with pickling DRF Response objects.
    
    Args:
        timeout: Cache timeout in seconds. If None, use default timeout.
        key_prefix: Prefix for the cache key.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(view_or_request, *args, **kwargs):
            # Check if first argument is a view instance (for class-based views) or request object
            if hasattr(view_or_request, 'request'):
                # Class-based view case
                request = view_or_request.request
            else:
                # Function-based view case
                request = view_or_request
                
            # Generate a simple cache key based on the path and query string
            path = force_str(request.path)
            query_string = force_str(request.META.get('QUERY_STRING', ''))
            cache_key = f"{key_prefix}:{path}:{query_string}"
            
            # Try to get from cache
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return Response(cached_data)
            
            # Generate the response
            logger.debug(f"Cache miss for {cache_key}")
            if hasattr(view_or_request, 'request'):
                # For class-based views, pass the view instance
                response = view_func(view_or_request, *args, **kwargs)
            else:
                # For function-based views, pass the request
                response = view_func(request, *args, **kwargs)
            
            # Cache the data, not the response object
            if hasattr(response, 'data'):
                cache.set(cache_key, response.data, timeout)
            
            return response
        return _wrapped_view
    return decorator

def clear_dashboard_cache():
    """
    Clear the dashboard cache to force a refresh of dashboard data.
    This can be called after important events like new trades being recorded.
    """
    # The dashboard endpoint is typically accessed at /api/dashboard/
    cache_key = "dashboard:/api/dashboard/"
    cache.delete(cache_key)
    logger.info("Dashboard cache cleared")
    
    # Also clear any variations with query parameters
    keys_to_delete = []
    for key in cache._cache.keys():  # Note: This is implementation-specific and may not work with all cache backends
        if key.startswith("dashboard:/api/dashboard/"):
            keys_to_delete.append(key)
    
    for key in keys_to_delete:
        cache.delete(key)
        logger.debug(f"Deleted cache key: {key}")
