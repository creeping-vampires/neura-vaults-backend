import logging
import traceback

logger = logging.getLogger(__name__)

def log_error(error, context=None, include_traceback=True):
    """Helper function to log errors with context and stack trace."""
    error_context = {
        'error_type': type(error).__name__,
        'error_message': str(error),
        'context': context or {}
    }
    
    if include_traceback:
        error_context['traceback'] = traceback.format_exc()
    
    logger.error(
        f"Error: {error_context['error_type']} - {error_context['error_message']}",
        extra=error_context
    )
    return error_context
