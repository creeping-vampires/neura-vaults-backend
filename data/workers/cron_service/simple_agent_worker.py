#!/usr/bin/env python
"""
Simple Agent Worker Script
-------------------------
This script runs the agent worker directly without using CrewAI or LiteLLM to avoid dependency issues.
It performs basic yield monitoring and allocation tasks without the AI agent components.
"""

import os
import sys
import time
import logging
import datetime
import traceback
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("SimpleAgentWorker")

# Add the project root to the path so we can import our modules
project_root = str(Path(__file__).parent.parent.parent.absolute())
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import Django settings and setup
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')
import django
django.setup()

# Import required models and functions
try:
    from django.db import connection
    from data.models import User, Agent, YieldMonitorRun
    from data.workers.yield_monitor_worker import YieldMonitorWorker
    logger.info("Successfully imported required modules")
except Exception as e:
    logger.error(f"Error importing modules: {e}")
    logger.error(traceback.format_exc())
    sys.exit(1)

def check_environment():
    """Check if all required environment variables are set"""
    required_vars = [
        'OPENAI_API_KEY',
        'RPC_URL',
        'YIELD_ALLOCATOR_VAULT_ADDRESS',
        'AI_AGENT_ADDRESS'
    ]
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    logger.info("All required environment variables are set")
    return True

def check_database_connection():
    """Check if we can connect to the database"""
    try:
        # Try to query the User model to check database connection
        user_count = User.objects.count()
        logger.info(f"Database connection successful. User count: {user_count}")
        return True
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        logger.error(traceback.format_exc())
        return False

def run_yield_monitor():
    """Run the yield monitor worker without using CrewAI"""
    try:
        logger.info("Starting yield monitoring process")
        
        # Create a yield monitor worker instance
        worker = YieldMonitorWorker()
        
        # Run the monitoring process
        logger.info("Running yield monitor worker")
        result = worker.run()
        
        # Log the result
        logger.info(f"Yield monitor completed with result: {result}")
        
        # Save the run to the database
        YieldMonitorRun.objects.create(
            timestamp=datetime.datetime.now(),
            status="completed" if result else "failed",
            details=f"Manual run completed at {datetime.datetime.now()}"
        )
        
        return result
    except Exception as e:
        logger.error(f"Error running yield monitor: {e}")
        logger.error(traceback.format_exc())
        
        # Save the failed run to the database
        try:
            YieldMonitorRun.objects.create(
                timestamp=datetime.datetime.now(),
                status="failed",
                details=f"Error: {str(e)}"
            )
        except Exception as db_error:
            logger.error(f"Error saving run to database: {db_error}")
        
        return False

def main():
    """Main function to run the simple agent worker"""
    start_time = time.time()
    logger.info("Simple Agent Worker started")
    
    # Check environment and database connection
    if not check_environment():
        logger.error("Environment check failed")
        return 1
    
    if not check_database_connection():
        logger.error("Database connection check failed")
        return 1
    
    # Run the yield monitor
    success = run_yield_monitor()
    
    # Log execution time
    execution_time = time.time() - start_time
    logger.info(f"Simple Agent Worker completed in {execution_time:.2f} seconds")
    
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
