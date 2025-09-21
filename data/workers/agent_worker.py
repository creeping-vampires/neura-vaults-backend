import logging
import threading
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from django.utils import timezone
from django.db import transaction, connections
from django.conf import settings
from ..models import Agent
from ..data_access_layer import AgentDAL
from ..crew import CryptoAnalysisCrew
import os

logger = logging.getLogger(__name__)


class AgentRunner:
    """Class to run a single agent instance using agent-agnostic approach"""
    
    def __init__(self):
        self.agent_kind = 'YieldOptimizer'
        self.crew = CryptoAnalysisCrew()
    
    def run(self):
        """Run the agent's trading logic"""
        try:
            logger.info(f"Running agent instance of kind {self.agent_kind}")
            
            # Prepare the message for the AI crew
            message = self._prepare_message()

            print(message)
            
            # Create the crew instance and run it with the agent's instructions
            crew_instance = self.crew.crew()
            result = crew_instance.kickoff(
                inputs={"message": message, "wallet_address": "0xTestWalletAddress"}
            )
            
            # Process the result
            self._process_result(result)
            
            logger.info(f"Agent instance of kind {self.agent_kind} execution completed successfully")
            return True
        except Exception as e:
            logger.error(f"Error running agent instance of kind {self.agent_kind}: {str(e)}")
            return False
    
    def _get_agent_config(self):
        """Get configuration specific to the agent kind"""
        return {
            "strategy": "yield_optimization",
            "detailed_instructions": "Optimize yield by moving assets between pools",
            "risk_level": "moderate",
            "trading_system": "yield_optimizer"
        }
    
    def _prepare_message(self):
        """Prepare the message for the AI crew based on agent configuration"""
        # Construct the message for yield optimization agent
        message = (
            f"You are a Yield optimizer agent named Sentient. "
            f"Your strategy is to optimize yield by rebalancing assets from lower yield pool to the pool yielding higher APY. "
        )
        
        return message
    
    def _process_result(self, result):
        """Process the result from the AI crew"""
        logger.info(f"[AGENT] Processing agent result...")
        logger.info(f"[AGENT] Result type: {type(result)}")
        logger.info(f"[AGENT] Result content: {str(result)[:500]}...")
        
        # Try to extract decision information if available
        try:
            if hasattr(result, 'output_data'):
                output_data = result.output_data
                logger.info(f"[AGENT] Found output_data in result")
                
                if isinstance(output_data, dict):
                    target_decision = output_data.get('target_decision', 'UNKNOWN')
                    logger.info(f"[AGENT] Target decision: {target_decision}")
                    
                    if target_decision == 'NO_ACTION':
                        logger.info(f"[AGENT] Agent decided NO_ACTION - checking if this is correct...")
                        free_balance = output_data.get('current_summary', {}).get('free_balance', '0')
                        logger.info(f"[AGENT] Free balance reported: {free_balance}")
                        if float(free_balance) > 0:
                            logger.warning(f"[AGENT] WARNING: Agent chose NO_ACTION but free_balance > 0! This might be incorrect.")
                    
                    elif target_decision == 'DEPLOY_IDLE':
                        logger.info(f"[AGENT] Agent decided to deploy idle assets - this should trigger allocation")
                        target_pool = output_data.get('target_pool', {})
                        logger.info(f"[AGENT] Target pool: {target_pool}")
                    
                    elif target_decision == 'MOVE_ALL':
                        logger.info(f"[AGENT] Agent decided to rebalance assets")
                        target_pool = output_data.get('target_pool', {})
                        logger.info(f"[AGENT] Target pool: {target_pool}")
                    
                    else:
                        logger.warning(f"[AGENT] Unknown target decision: {target_decision}")
                else:
                    logger.warning(f"[AGENT] output_data is not a dict: {type(output_data)}")
            else:
                logger.warning(f"[AGENT] No output_data found in result")
                
        except Exception as e:
            logger.error(f"[AGENT] Error analyzing result: {str(e)}")
        
        # This will be implemented in the future to handle trade execution
        # For now, just log the result
        logger.info(f"[AGENT] Agent instance result logged successfully")


class AgentWorker:
    """Worker to run agents according to their trade frequency"""
    
    def __init__(self):
        self.running = False
        self.thread = None
        self.last_run_times = {}  # Store the last run time for each agent
        # Default to 10 concurrent agents, but allow configuration via settings
        self.max_concurrent_agents = getattr(settings, 'MAX_CONCURRENT_AGENTS', 10)

    def start(self):
        """Start the worker in a separate thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._run_loop, daemon=True)
            self.thread.start()
            logger.info("Agent worker started")

    def stop(self):
        """Stop the worker"""
        if self.running:
            self.running = False
            self.thread.join(timeout=5)
            logger.info("Agent worker stopped")
    
    def run_single_threaded(self):
        """Run all agents once in single-threaded mode (for daily cron jobs)"""
        logger.info("Starting single-threaded agent worker run")
        
        # Add environment validation
        try:
            self._validate_environment()
        except Exception as e:
            logger.error(f"Environment validation failed: {str(e)}")
            return False
        
        # Add database connectivity check
        try:
            self._check_database_connectivity()
        except Exception as e:
            logger.error(f"Database connectivity check failed: {str(e)}")
            return False
        
        # Run agent instance with detailed logging
        try:
            logger.info("Attempting to run agent instance...")
            success = self._run_agent()
            if success:
                logger.info("Agent instance completed successfully")
            else:
                logger.error("Agent instance returned failure status")
        except Exception as e:
            logger.error(f"Critical error in agent execution: {str(e)}", exc_info=True)
            return False
        
        logger.info("Finished processing all agents in single-threaded mode")
        return True
    
    def _validate_environment(self):
        """Validate critical environment variables"""
        critical_vars = [
            'OPENAI_API_KEY',
            'RPC_URL',
            'YIELD_ALLOCATOR_VAULT_ADDRESS',
            'AI_AGENT_ADDRESS'
        ]
        
        missing_vars = []
        for var in critical_vars:
            value = os.getenv(var)
            if not value:
                missing_vars.append(var)
            else:
                logger.info(f"✓ {var}: {'***' if 'KEY' in var else value}")
        
        if missing_vars:
            raise Exception(f"Missing critical environment variables: {missing_vars}")
        
        logger.info("Environment validation passed")
    
    def _check_database_connectivity(self):
        """Check database connectivity"""
        from django.db import connection
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
    
    def _run_agent(self):
        """Run a single agent instance and update its last run time"""
        try:
            logger.info(f"Creating AgentRunner instance...")
            runner = AgentRunner()
            
            logger.info(f"Starting agent execution...")
            success = runner.run()
            
            if success:
                logger.info(f"Agent execution completed successfully")
                # Update the last run time for tracking purposes
                current_time = timezone.now()
                self.last_run_times['default'] = current_time
                logger.info(f"Updated last run time to: {current_time}")
            else:
                logger.error(f"Agent execution returned False - check agent logs for details")
            
            return success
        except Exception as e:
            logger.error(f"Error running agent instance: {str(e)}", exc_info=True)
            return False
    
    def _run_loop(self):
        """Main worker loop"""
        while self.running:
            try:
                self._process_agents()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in agent worker loop: {str(e)}")
                time.sleep(60)  # Continue after error
    
    def _process_agents(self):
        """Process all agents that need to run"""
        now = timezone.now()
        
        # Get all running agents
        agents = Agent.objects.filter(
            status=Agent.StatusChoices.RUNNING,
            is_deleted=False
        )
        
        logger.info(f"Found {agents.count()} running agents to process")
        
        # # Check which agents need to run based on their trade frequency
        # agents_to_run = []
        # for agent in agents:
        #     last_run = self.last_run_times.get(agent.id)
            
        #     # If agent has never run or it's time to run again based on trade frequency
        #     if not last_run or now >= last_run + timedelta(minutes=agent.trade_frequency):
        #         agents_to_run.append(agent)
        
        # logger.info(f"{len(agents_to_run)} agents need to run now")
        
        # # Use ThreadPoolExecutor to run agents concurrently
        # with ThreadPoolExecutor(max_workers=self.max_concurrent_agents) as executor:
        #     # Submit all agents to the thread pool
        #     future_to_agent = {executor.submit(self._run_agent, agent): agent for agent in agents_to_run}
            
        #     # Process completed agents
        #     for future in as_completed(future_to_agent):
        #         agent = future_to_agent[future]
        #         try:
        #             success = future.result()
        #             if success:
        #                 logger.info(f"Agent {agent.id} ({agent.name}) completed successfully")
        #             else:
        #                 logger.error(f"Agent {agent.id} ({agent.name}) failed to complete")
        #         except Exception as e:
        #             logger.error(f"Agent {agent.id} ({agent.name}) raised an exception: {str(e)}")
        
        logger.info("Finished processing all agents in this cycle")
    
    def _process_agents_single_threaded(self):
        """Process all agents sequentially in single-threaded mode"""
        now = timezone.now()
        
        # # Get all running agents
        # agents = Agent.objects.filter(
        #     status=Agent.StatusChoices.RUNNING,
        #     is_deleted=False
        # )
        
        # logger.info(f"Found {agents.count()} running agents to process in single-threaded mode")
        
        # # Check which agents need to run based on their trade frequency
        # agents_to_run = []
        # for agent in agents:
        #     last_run = self.last_run_times.get(agent.id)
            
        #     # If agent has never run or it's time to run again based on trade frequency
        #     if not last_run or now >= last_run + timedelta(minutes=agent.trade_frequency):
        #         agents_to_run.append(agent)
        
        # logger.info(f"{len(agents_to_run)} agents need to run now (single-threaded mode)")
        
        # # Run agents sequentially (single-threaded)
        # for i, agent in enumerate(agents_to_run, 1):
        #     logger.info(f"Processing agent {i}/{len(agents_to_run)}: {agent.id} ({agent.name})")
        #     try:
        #         self._run_agent(agent)
        #         logger.info(f"Successfully processed agent {agent.id} ({agent.name})")
        #     except Exception as e:
        #         logger.error(f"Error processing agent {agent.id} ({agent.name}): {str(e)}")
        #         # Continue with next agent even if one fails
        #         continue

        # run agent instance
        self._run_agent()
        
        logger.info("Finished processing all agents in single-threaded mode")


# Singleton instance
agent_worker = AgentWorker()
