from django.apps import AppConfig
from django.db import connections
import logging

logger = logging.getLogger(__name__)

class DataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'data'
    
    def ready(self):
        """
        This method is called when Django starts.
        Close all database connections to ensure a clean start.
        """
        try:
            connections.close_all()
            logger.info("Successfully closed all database connections on server startup")
        except Exception as e:
            logger.error(f"Error closing database connections on startup: {str(e)}")
