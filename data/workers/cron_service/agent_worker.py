"""
Agent Worker - Automated Yield Optimization Agent
Runs the AI agent to analyze yield opportunities and execute allocation strategies
Based on the agent-agnostic approach for yield optimization
"""
import os
import sys
import time
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import json


# Add the project root to Python path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Configure Django BEFORE importing any Django models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'defai_backend.settings')

import django
django.setup()

from django.utils import timezone
from django.db import connection
from data.crew import CryptoAnalysisCrew

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class AgentWorker:
    """
    Worker that runs the AI agent to analyze yield opportunities and execute allocation strategies
    Uses the agent-agnostic approach for yield optimization
    """
    
    def __init__(self):
        """Initialize the agent worker"""
        # Load environment variables
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        self.rpc_url = os.getenv('RPC_URL')
        self.yield_allocator_vault_address = os.getenv('YIELD_ALLOCATOR_VAULT_ADDRESS')
        self.ai_agent_address = os.getenv('AI_AGENT_ADDRESS')
        
        # Log all environment variables for debugging
        logger.info("=== Agent Worker Environment Variables ===")
        logger.info(f"OPENAI_API_KEY: {'***' if self.openai_api_key else 'NOT SET'}")
        logger.info(f"RPC_URL: {self.rpc_url}")
        logger.info(f"YIELD_ALLOCATOR_VAULT_ADDRESS: {self.yield_allocator_vault_address}")
        logger.info(f"AI_AGENT_ADDRESS: {self.ai_agent_address}")
        
        # Initialize the crypto analysis crew
        self.crew = CryptoAnalysisCrew()
        
        logger.info("Agent Worker initialized successfully")
    
    def validate_environment(self):
        """Validate that all required environment variables are set"""
        logger.info("Validating environment variables...")
        
        required_vars = {
            'OPENAI_API_KEY': self.openai_api_key,
            'RPC_URL': self.rpc_url,
            'YIELD_ALLOCATOR_VAULT_ADDRESS': self.yield_allocator_vault_address,
            'AI_AGENT_ADDRESS': self.ai_agent_address
        }
        
        missing_vars = []
        for var_name, var_value in required_vars.items():
            if not var_value:
                missing_vars.append(var_name)
        
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {missing_vars}")
        
        logger.info("✓ All required environment variables are set")
    
    def check_database_connectivity(self):
        """Check database connectivity"""
        logger.info("Checking database connectivity...")
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    logger.info("✓ Database connectivity check passed")
                else:
                    raise Exception("Database query returned unexpected result")
        except Exception as e:
            raise Exception(f"Database connectivity failed: {str(e)}")
    
    def prepare_agent_message(self):
        """Prepare the message for the AI crew"""
        logger.info("Preparing agent message...")
        
        message = (
            f"You are a Yield optimizer agent named Sentient. "
            f"Your strategy is to optimize yield by rebalancing assets from lower yield pool to the pool yielding higher APY. "
        )
        
        logger.info(f"Agent message prepared: {message[:100]}...")
        return message
    
    def run_agent_analysis(self):
        """Run the agent analysis and return the result"""
        logger.info("Starting agent analysis...")
        
        try:
            # Prepare the message for the AI crew
            message = self.prepare_agent_message()
            
            # Create the crew instance and run it
            logger.info("Creating crew instance...")
            crew_instance = self.crew.crew()
            logger.info("Crew instance created successfully")
            
            logger.info("Starting crew kickoff...")
            result = crew_instance.kickoff(
                inputs={"message": message, "wallet_address": "0xTestWalletAddress"}
            )
            logger.info("Crew kickoff completed successfully")
            
            return result
            
        except Exception as e:
            logger.error(f"Error during agent analysis: {str(e)}", exc_info=True)
            raise
    
    def process_agent_result(self, result):
        """Process the result from the AI crew and log decision details"""
        logger.info("Processing agent result...")
        logger.info(f"Result type: {type(result)}")
        logger.info(f"Result content: {str(result)[:500]}...")
        
        try:
            if hasattr(result, 'output_data'):
                output_data = result.output_data
                logger.info("Found output_data in result")
                
                if isinstance(output_data, dict):
                    target_decision = output_data.get('target_decision', 'UNKNOWN')
                    logger.info(f"🎯 Agent Decision: {target_decision}")
                    
                    if target_decision == 'NO_ACTION':
                        logger.info("Agent decided NO_ACTION - checking if this is correct...")
                        free_balance = output_data.get('current_summary', {}).get('free_balance', '0')
                        logger.info(f"Free balance reported: {free_balance}")
                        if float(free_balance) > 0:
                            logger.warning(f"⚠️  WARNING: Agent chose NO_ACTION but free_balance > 0! This might be incorrect.")
                        else:
                            logger.info("✓ NO_ACTION is correct - no idle assets to deploy")
                    
                    elif target_decision == 'DEPLOY_IDLE':
                        logger.info("🚀 Agent decided to deploy idle assets - this should trigger allocation")
                        target_pool = output_data.get('target_pool', {})
                        free_balance = output_data.get('current_summary', {}).get('free_balance', '0')
                        logger.info(f"Target pool: {target_pool}")
                        logger.info(f"Amount to deploy: {free_balance}")
                        
                        # TODO: Implement actual deployment logic here
                        logger.info("📝 TODO: Implement actual asset deployment")
                    
                    elif target_decision == 'MOVE_ALL':
                        logger.info("🔄 Agent decided to rebalance assets")
                        target_pool = output_data.get('target_pool', {})
                        current_positions = output_data.get('current_summary', {}).get('positions', [])
                        logger.info(f"Target pool: {target_pool}")
                        logger.info(f"Current positions: {current_positions}")
                        
                        # TODO: Implement actual rebalancing logic here
                        logger.info("📝 TODO: Implement actual asset rebalancing")
                    
                    else:
                        logger.warning(f"❓ Unknown target decision: {target_decision}")
                        
                    # Log additional details
                    expected_gain = output_data.get('expected_gain_bps', 0)
                    logger.info(f"Expected gain: {expected_gain} basis points")
                    
                else:
                    logger.warning(f"output_data is not a dict: {type(output_data)}")
            else:
                logger.warning("No output_data found in result")
                
        except Exception as e:
            logger.error(f"Error analyzing result: {str(e)}", exc_info=True)
        
        logger.info("Agent result processing completed")
    
    def run_single_execution(self):
        """Run a single agent execution cycle"""
        logger.info("=" * 60)
        logger.info(f"🤖 Starting Agent Worker Execution at {datetime.now()}")
        logger.info("=" * 60)
        
        try:
            # Validate environment
            self.validate_environment()
            
            # Check database connectivity
            self.check_database_connectivity()
            
            # Run agent analysis
            result = self.run_agent_analysis()
            
            # Process the result
            self.process_agent_result(result)
            
            logger.info("✅ Agent execution completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Agent execution failed: {str(e)}", exc_info=True)
            return False
        
        finally:
            logger.info("=" * 60)
            logger.info(f"🏁 Agent Worker Execution Finished at {datetime.now()}")
            logger.info("=" * 60)


def main():
    """Main function to run the agent worker"""
    logger.info("🚀 Starting Agent Worker...")
    
    try:
        # Create worker instance
        worker = AgentWorker()
        
        # Run single execution
        success = worker.run_single_execution()
        
        if success:
            logger.info("✅ Agent worker completed successfully")
            sys.exit(0)
        else:
            logger.error("❌ Agent worker failed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"💥 Critical error in agent worker: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
