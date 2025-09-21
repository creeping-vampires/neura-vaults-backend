#!/usr/bin/env python
"""
Test script to validate environment setup configuration.
This script checks whether the application is correctly using local environment variables 
or AWS secrets based on the SETUP flag.
"""
import os
import sys
import logging
import django
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Test the environment setup configuration."""
    # Load environment variables from .env file
    load_dotenv()
    
    # Get the current SETUP mode
    setup_mode = os.getenv('SETUP', 'local').lower()
    logger.info(f"Current SETUP mode: {setup_mode.upper()}")
    
    # Check if Django settings are properly configured
    try:
        # Add the project directory to the Python path
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')
        
        # Initialize Django
        django.setup()
        
        # Import settings after Django is set up
        from django.conf import settings
        
        # Verify that the SETUP_MODE is correctly set in settings
        if hasattr(settings, 'SETUP_MODE'):
            logger.info(f"Django settings SETUP_MODE: {settings.SETUP_MODE.upper()}")
            if settings.SETUP_MODE == setup_mode:
                logger.info("✅ SETUP_MODE in Django settings matches environment variable")
            else:
                logger.error(f"❌ SETUP_MODE mismatch: env={setup_mode}, settings={settings.SETUP_MODE}")
        else:
            logger.error("❌ SETUP_MODE not found in Django settings")
        
        # Check if AWS secrets were loaded (if in AWS mode)
        if setup_mode == 'aws':
            # Check if AWS-specific settings are available
            aws_secret_name = getattr(settings, 'AWS_SECRET_NAME', os.environ.get('AWS_SECRET_NAME'))
            if aws_secret_name:
                logger.info(f"AWS Secret Name: {aws_secret_name}")
                logger.info("✅ AWS configuration detected")
            else:
                logger.warning("⚠️ AWS Secret Name not found, but SETUP=aws")
        else:
            logger.info("✅ Using local environment variables (SETUP=local)")
        
        # Log some key settings to verify configuration
        logger.info(f"ENVIRONMENT: {os.getenv('ENVIRONMENT', 'not set')}")
        logger.info(f"DEBUG mode: {getattr(settings, 'DEBUG', 'unknown')}")
        logger.info(f"DATABASE engine: {settings.DATABASES['default']['ENGINE']}")
        
        return True
    except Exception as e:
        logger.error(f"Error testing environment setup: {str(e)}")
        return False

if __name__ == "__main__":
    success = main()
    if success:
        logger.info("Environment setup test completed successfully")
    else:
        logger.error("Environment setup test failed")
        sys.exit(1)
