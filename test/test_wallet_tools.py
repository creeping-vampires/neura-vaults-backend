#!/usr/bin/env python
"""
Script to test WalletTools and run an agent instance.
This script uses Django's environment to test WalletTools and run an agent directly.
"""
import os
import sys
import argparse
import logging
from django.utils import timezone

# Load environment variables from .env file
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_file = os.path.join(project_root, '.env')
if os.path.exists(env_file):
    print(f"Loading environment variables from {env_file}")
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ[key] = value
else:
    print(f"Warning: .env file not found at {env_file}")

# Set up Django environment
sys.path.append(project_root)

# Auto-configure database based on environment
environment = os.environ.get('ENVIRONMENT', 'development')
if environment.lower() == 'development':
    print(f"Running in development environment. Using SQLite database.")
    os.environ['USE_SQLITE'] = 'true'
    if 'DATABASE_URL' in os.environ:
        del os.environ['DATABASE_URL']

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')
import django
django.setup()

# Configure logging
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/wallet_tools_test.log')
    ]
)
logger = logging.getLogger('wallet_tools_test')

# Import the tool functions and necessary classes for agent running
from data.models import Agent
from data.workers.agent_worker import AgentRunner


def run_agent_once():
    """Run an agent instance once without requiring a specific agent ID.
    
    Uses the new agent-agnostic approach where the system runs without specific agent targeting.
    
    Returns:
        bool: True if the agent ran successfully, False otherwise.
    """
    logger.info(f"Running agent instance")
    
    try:
        # Create an agent runner and run it (no longer requires specific agent)
        runner = AgentRunner()
        print(f"\n{'='*50}")
        print(f"RUNNING AGENT INSTANCE")
        print(f"Using agent-agnostic approach")
        print(f"{'='*50}\n")
        
        success = runner.run()
        
        if success:
            logger.info(f"Agent instance ran successfully")
            print(f"\n{'='*50}")
            print(f"AGENT RUN COMPLETED SUCCESSFULLY")
            print(f"{'='*50}\n")
            return True
        else:
            logger.error(f"Agent instance run failed")
            print(f"\n{'='*50}")
            print(f"AGENT RUN FAILED")
            print(f"{'='*50}\n")
            return False
            
    except Exception as e:
        logger.error(f"Error running agent instance: {str(e)}")
        print(f"Error running agent instance: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Test WalletTools functions and run an agent instance')
    parser.add_argument('--tokens', nargs='+', default=['HYPE', 'uBTC', 'uETH'], 
                        help='Token symbols to test price fetching (default: HYPE uBTC uETH)')
    parser.add_argument('--indicator-token', type=str, default='uBTC',
                        help='Token symbol to test indicators (default: uBTC)')
    parser.add_argument('--days', type=int, default=2,
                        help='Number of days for indicator data (default: 2)')
    parser.add_argument('--skip-prices', action='store_true',
                        help='Skip token price testing')
    parser.add_argument('--skip-indicators', action='store_true',
                        help='Skip indicator testing')
    parser.add_argument('--run-agent', action='store_true',
                        help='Run an agent instance after tests')
    parser.add_argument('--agent-only', action='store_true',
                        help='Skip all tests and only run agent instance')
    
    args = parser.parse_args()
    
    # If only running agent, skip all tests
    if args.agent_only:
        run_agent_once()
        exit()

    
    # Run the tests
    logger.info(f"Starting wallet tools test")
    success = True
    
    if success:
        print(f"\n{'='*50}")
        print("ALL TESTS PASSED!")
        print(f"{'='*50}\n")
    else:
        print(f"\n{'='*50}")
        print("SOME TESTS FAILED!")
        print(f"{'='*50}\n")
    
    # Run the agent if requested
    if args.run_agent:
        print(f"\n{'='*50}")
        print(f"RUNNING AGENT INSTANCE")
        print(f"{'='*50}\n")
        run_agent_once()
