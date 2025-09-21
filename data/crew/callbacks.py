import logging
from crewai import TaskOutput
from ..data_access_layer import ThoughtDAL, AgnosticThoughtDAL

logger = logging.getLogger(__name__)

def step_callback(output: TaskOutput) -> None:
    """
    Callback function to handle agent task outputs and store thoughts.
    Uses separate tables for agent-specific vs agent-agnostic modes.
    """
    try:
        # Extract agent_id from output if available
        agent_id = None
        if hasattr(output, 'pydantic') and output.pydantic:
            agent_id = getattr(output.pydantic, 'agent_id', None)
        
        # Get agent role from output
        agent_role = output.agent if output.agent else "Unknown Agent"
        
        # Get thought content
        thought_content = ""
        if hasattr(output, 'pydantic') and output.pydantic:
            if hasattr(output.pydantic, 'summary'):
                thought_content = output.pydantic.summary
            else:
                thought_content = str(output.pydantic)
        else:
            thought_content = str(output.raw)
        
        # Determine if this is agent-agnostic mode
        # Agent-agnostic mode: agent_id is None, 1 (default), or agent doesn't exist
        is_agent_agnostic = agent_id is None or agent_id == 1
        
        if is_agent_agnostic:
            # Use AgnosticThought table for agent-agnostic mode
            try:
                agnostic_thought = AgnosticThoughtDAL.create_agnostic_thought(
                    thought=thought_content,
                    agent_role=agent_role,
                    crew_id=getattr(output, 'task_id', None)  # Track crew execution if available
                )
                
                logger.info(f"Successfully stored agnostic thought - Agent: {agent_role}, Thought ID: {agnostic_thought.thoughtId}")
                
            except Exception as db_error:
                logger.error(f"Failed to store agnostic thought in database: {str(db_error)}")
                logger.info(f"Agent output (not stored): Role={agent_role}, Content={thought_content[:200]}...")
        else:
            # Use regular Thought table for agent-specific mode
            try:
                thought = ThoughtDAL.create_thought(
                    agent_id=agent_id,
                    thought=thought_content,
                    agent_role=agent_role
                )
                
                logger.info(f"Successfully stored agent-specific thought - Agent: {agent_role}, Thought ID: {thought.thoughtId}")
                
            except Exception as db_error:
                logger.error(f"Failed to store agent-specific thought in database: {str(db_error)}")
                logger.info(f"Agent output (not stored): Role={agent_role}, Content={thought_content[:200]}...")
            
    except Exception as e:
        logger.error(f"Error in step_callback: {str(e)}")
        # Don't raise the exception to avoid breaking the agent workflow