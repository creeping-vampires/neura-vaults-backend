from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from django.conf import settings
import json

from data.agent_utils import fetch_latest_apy_data,fetch_protocol_status
from .tools.liquidity_pool_tools import (
    execute_yield_allocation
)
from .output_parser import  IndicatorsSummaryMessage, TradeSummaryMessage, StrategyMessage, ValidationMessage
from .callbacks import step_callback

@CrewBase
class CryptoAnalysisCrew:
    """Yield Optimization Crew for DefAI operations"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"
    agent_id = None  # Will be set when crew is initialized
    latest_apy_data = None
    formatted_apy_data = None  # Will store the formatted portfolio data

    # Using GPT-4 for yield optimization
    llm = ChatOpenAI(
        model='gpt-4o-mini',
        api_key=settings.OPENAI_API_KEY
    )

    def __init__(self):
        """Initialize the crew with an agent ID.
        
        Args:
            agent_id: The ID of the agent this crew is working for
        """
        super().__init__()
        # self.agent_id = agent_id
        # Fetch and store the raw portfolio data
        self.latest_apy_data = fetch_latest_apy_data()
        self.protocol_status = fetch_protocol_status()
        print('protocol status ', self.protocol_status)
        # Format the portfolio data for yield optimization analysis
        self.formatted_apy_data = self._format_apy_data()
        print('formatted apy data ', self.formatted_apy_data)

    def _format_apy_data(self):
        """Format the YieldReport data for yield optimization analysis.
        
        Returns:
            str: Formatted APY data as a string for agent backstory
        """
        try:
            latest_apy_data = self.latest_apy_data
            protocol_status = self.protocol_status
            
            # Handle error case
            if isinstance(latest_apy_data, dict) and 'error' in latest_apy_data:
                return f"Error fetching APY data: {latest_apy_data['error']}"
            
            # Handle empty data case
            if not latest_apy_data or len(latest_apy_data) == 0:
                return "No APY optimization data available. Using mock data for analysis."

            # Filter out Felix protocol and group by protocol for better readability
            filtered_data = [result for result in latest_apy_data if result['protocol'] != 'Felix']
            
            # Handle case where all data is filtered out
            if not filtered_data:
                return "No valid APY data available after filtering. Using mock data for analysis."

            # Create a string with formatted APY data for agent
            apy_data_str = "Current USDe yield opportunities across pools:\n\n"
            
            # Add protocol status information first
            if isinstance(protocol_status, dict) and protocol_status.get('success'):
                apy_data_str += "🏦 VAULT STATUS:\n"
                balances = protocol_status.get('balances', {})
                asset_info = protocol_status.get('asset', {})
                pools_info = protocol_status.get('pools', {})
                
                apy_data_str += f"  • Asset: {asset_info.get('symbol', 'Unknown')}\n"
                apy_data_str += f"  • Total Assets: {balances.get('total_assets', 0):.4f} {asset_info.get('symbol', '')}\n"
                apy_data_str += f"  • Idle Assets Available: {balances.get('idle_balance', 0):.4f} {asset_info.get('symbol', '')}\n"
                apy_data_str += f"  • Allocated Assets: {balances.get('allocated_assets', 0):.4f} {asset_info.get('symbol', '')}\n"
                
                # Current pool allocations
                if pools_info.get('balances'):
                    apy_data_str += "📊 CURRENT ALLOCATIONS:\n"
                    for pool in pools_info['balances']:
                        if pool['balance'] > 0:
                            apy_data_str += f"  • {pool['address']}: {pool['balance']:.4f} {asset_info.get('symbol', '')} ({pool['percentage']:.2f}%)\n"
                    apy_data_str += "\n"
                
                # Allocation guidance
                idle_balance = balances.get('idle_balance', 0)
                if idle_balance > 0.01:
                    apy_data_str += f"💡 ALLOCATION OPPORTUNITY: {idle_balance:.4f} {asset_info.get('symbol', '')} available for deployment\n\n"
            
            # Group by protocol for better readability
            protocol_groups = {}
            for result in filtered_data:
                protocol = result['protocol']
                if protocol not in protocol_groups:
                    protocol_groups[protocol] = []
                protocol_groups[protocol].append(result)
            
            # Format data by protocol (limit to 1 entry per protocol)
            apy_data_str += "🎯 YIELD OPPORTUNITIES:\n\n"
            for protocol, results in protocol_groups.items():
                # Limit to first 1 result per protocol
                limited_results = results[:1]
                for result in limited_results:
                    apy_data_str += f"Pool Address: {result['pool_address']}\n"
                    apy_data_str += f"Pool Name: {result['protocol']}\n"
                    apy_data_str += f"Token: {result['token']}\n"
                    apy_data_str += f"Token Address: {result['token_address']}\n"
                    apy_data_str += f"APY: {result['apy']:.2f}%\n"
                    apy_data_str += f"TVL: ${result['tvl']:,.2f}\n"
                    if result['is_current_best']:
                        apy_data_str += f"BEST YIELD for {result['token']}\n"
                    apy_data_str += f"Last updated: {result['created_at'][:19]}\n"
                    apy_data_str += "\n"
                apy_data_str += "\n"
            
            return apy_data_str
        except Exception as e:
            # Return an error message if formatting fails
            return f"Error formatting APY data: {str(e)}. Using mock data for analysis."

    @agent
    def pool_analyzer_agent(self) -> Agent:
        """Agent that analyzes liquidity pools and identifies yield opportunities"""
        return Agent(
            config=self.agents_config["pool_analyzer_agent"],
            tools=[],
            backstory=self.formatted_apy_data,
            allow_delegation=False,
            verbose=True,
            llm=self.llm,
        )
        
    @agent
    def yield_qa_agent(self) -> Agent:
        """Agent that reviews and validates yield allocation strategies"""
        return Agent(
            config=self.agents_config["yield_qa_agent"],
            tools=[],
            backstory=self.formatted_apy_data,
            allow_delegation=False,
            verbose=True,
            llm=self.llm,
        )

    @agent
    def yield_executor_agent(self) -> Agent:
        """Agent that executes the yield allocation strategy"""
        return Agent(
            config=self.agents_config["yield_executor_agent"],
            tools=[execute_yield_allocation],
            backstory=self.formatted_apy_data,
            allow_delegation=False,
            verbose=True,
            llm=self.llm,
        )   

    @task
    def pool_analyzer_task(self) -> Task:
        """Task to analyze liquidity pools and recommend allocations based on protocol status and APY data"""
        return Task(
            config=self.tasks_config["pool_analyzer_task"],
            agent=self.pool_analyzer_agent(),
            context=[],
            callback=step_callback,
            output_pydantic=IndicatorsSummaryMessage,
            description="""
            Analyze the current vault status and yield opportunities to make asset allocation decisions.
            
            Your analysis should include:
            1. Review the vault status (idle assets, current allocations, liquidity ratio)
            2. Analyze available yield opportunities across different protocols
            3. Consider risk factors and diversification
            4. Recommend specific allocation amounts and target pools
            5. Provide reasoning for your allocation strategy
            
            Focus on:
            - Maximizing yield while managing risk
            - Maintaining appropriate liquidity levels
            - Diversifying across protocols when beneficial
            - Using complete pool addresses for execution
            
            CRITICAL DECISION LOGIC (follow in this exact order):
            
            1. FIRST PRIORITY - Check for idle assets:
               - If free_balance > 0, ALWAYS recommend "DEPLOY_IDLE"
               - Target the highest APY pool for deployment
               - Amount should equal the free_balance amount
            
            2. SECOND PRIORITY - If no idle assets (free_balance = 0):
               - If current allocation is already in the BEST YIELD pool → "NO_ACTION"
               - If current allocation is NOT in the best yield pool → "MOVE_ALL"
               - Do NOT recommend moving to the same pool assets are already in
            
            EXAMPLES:
            - free_balance: "0.1000" → target_decision: "DEPLOY_IDLE" (deploy the 0.1000 to best pool)
            - free_balance: "0" + already in best pool → target_decision: "NO_ACTION"
            - free_balance: "0" + not in best pool → target_decision: "MOVE_ALL"
            
            Always check free_balance first before making any other decisions.
            """
        )
        
    @task
    def yield_qa_task(self) -> Task:
        """Task to review and validate the pool analysis and allocation strategy"""
        return Task(
            config=self.tasks_config["yield_qa_task"],
            agent=self.yield_qa_agent(),
            context=[self.pool_analyzer_task()],
            callback=step_callback,
            output_pydantic=StrategyMessage,
            description="""
            Review and validate the allocation strategy proposed by the pool analyzer.
            
            Your validation should include:
            1. Verify the allocation recommendations make sense given current market conditions
            2. Check that pool addresses and amounts are correct
            3. Assess risk levels and ensure they align with strategy goals
            4. Validate that the strategy optimizes for yield while maintaining safety
            5. Confirm execution feasibility
            
            Provide:
            - Approval or rejection of the strategy with clear reasoning
            - Any modifications or improvements to the proposed allocation
            - Final recommended allocation amounts and target pools
            - Risk assessment and mitigation strategies
            
            Only approve strategies that are well-reasoned and executable.
            """
        )

    @task
    def yield_executor_task(self) -> Task:
        """Task to execute the approved yield allocation strategy using AiAgent contract"""
        return Task(
            config=self.tasks_config["yield_executor_task"],
            agent=self.yield_executor_agent(),
            context=[self.yield_qa_task()],
            callback=step_callback,
            output_pydantic=TradeSummaryMessage,
            description="""
            Execute the approved allocation strategy using the execute_yield_allocation tool and AiAgent contract.
            
            CRITICAL: You MUST use the execute_yield_allocation tool to perform actual blockchain transactions.
            DO NOT generate mock or placeholder transaction data.
            
            EXECUTION STEPS:
            1. Parse the approved allocation strategy from the QA agent
            2. Determine scenario type: IDLE_DEPLOYMENT or REBALANCING
            3. Format the strategy for the execute_yield_allocation tool:
            
            For IDLE_DEPLOYMENT (only idle assets to deploy):
            {
              "scenario_type": "IDLE_DEPLOYMENT",
              "withdrawals": [],
              "allocations": [
                {
                  "pool_address": "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b",
                  "amount": "100000000000000000",
                  "protocol": "HypurrFi"
                }
              ]
            }
            
            For REBALANCING (withdraw from current + deposit to new):
            CRITICAL: For rebalancing, the deposit amount MUST equal the withdrawal amount.
            Do NOT use total vault balance for deposit amount.
            {
              "scenario_type": "REBALANCING", 
              "withdrawals": [
                {
                  "pool_address": "0x00A89d7a5A02160f20150EbEA7a2b5E4879A1A8b",
                  "amount": "200000000000000000",
                  "protocol": "HyperLend"
                }
              ],
              "allocations": [
                {
                  "pool_address": "0xceCcE0EB9DD2Ef7996e01e25DD70e461F918A14b", 
                  "amount": "200000000000000000",
                  "protocol": "HypurrFi"
                }
              ]
            }
            
            REBALANCING AMOUNT LOGIC:
            - If withdrawing 0.2 USDe from Pool A, deposit exactly 0.2 USDe to Pool B
            - If withdrawing 1.5 USDe from Pool A, deposit exactly 1.5 USDe to Pool B
            - Do NOT add idle assets to the rebalancing amount
            - Idle assets should only be deployed in separate IDLE_DEPLOYMENT scenarios
            
            4. Call execute_yield_allocation tool with the formatted strategy
            5. Parse the actual transaction results from the tool
            6. Report the real transaction hashes, gas costs, and execution details
            
            IMPORTANT: 
            - Always use the execute_yield_allocation tool for actual blockchain execution
            - Use real transaction hashes returned by the tool
            - Report actual gas costs and block numbers
            - If QA recommends "no action", return summary with 0 transactions
            - For amounts, use wei format (multiply by 10^18 for whole tokens)
            - Use complete pool addresses from the strategy
            - For rebalancing: withdrawal amount = deposit amount (1:1 ratio)
            
            The execute_yield_allocation tool will handle the actual blockchain transactions and return real transaction details.
            """
        )

    @crew
    def crew(self) -> Crew:
        """Create the yield optimization crew"""
        return Crew(
            agents=[
                self.pool_analyzer_agent(),
                self.yield_qa_agent(),
                self.yield_executor_agent()
            ],
            tasks=[
                self.pool_analyzer_task(),
                self.yield_qa_task(),
                self.yield_executor_task()
            ],
            process=Process.sequential,
            verbose=True,
        )