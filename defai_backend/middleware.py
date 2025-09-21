from django.db import connections
import logging

logger = logging.getLogger(__name__)

class CloseDatabaseConnectionsMiddleware:
    """
    Middleware to close database connections after each request.
    This helps prevent connection pool exhaustion by ensuring connections
    are properly closed and returned to the pool.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process the request
        response = self.get_response(request)
        
        # Close all database connections
        connections.close_all()
        logger.debug("Closed all database connections after request")
        
        return response
