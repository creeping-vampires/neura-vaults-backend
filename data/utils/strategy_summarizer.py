import os
from openai import OpenAI
from typing import Dict, Any

def summarize_strategy_with_gpt(recommendation: Dict[str, Any]) -> str:
    """
    Summarizes a reallocation strategy using the OpenAI API to generate a
    human-readable explanation from an AI agent's perspective.

    Args:
        recommendation: A dictionary containing the details of the reallocation.

    Returns:
        A string containing the AI-generated summary.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "Error: OPENAI_API_KEY environment variable not set. Cannot generate summary."

    client = OpenAI(api_key=api_key)

    # Deconstruct the recommendation object for the prompt
    action = recommendation.get("action")
    reason = recommendation.get("reason")
    from_protocol = recommendation.get("from_protocol")
    to_protocol = recommendation.get("to_protocol")
    amount = recommendation.get("amount")
    amount_description = recommendation.get("amount_description", "the entire position")
    current_apy_from = recommendation.get("current_apy_from")
    new_apy_to = recommendation.get("new_apy_to")
    current_best_pool = recommendation.get("current_best_pool")

    # Background knowledge for the AI
    background_knowledge = """
    Background on our available lending protocols (no two are related to each other in any way):
    - **HyperLend**: A stable, well-established protocol known for reliable but generally conservative yields. It follows a standard kinked interest rate model.
    - **HyperFi**: An independent protocol offering competitive yields with its own risk profile and operational model.
    - **Felix**: A newer, highly dynamic protocol that uses a sophisticated, multi-market borrowing and lending model. Its APY can be volatile but often presents high-yield opportunities.
    """

    # Calculate the APY improvement in basis points
    apy_improvement_bps = 0
    if current_apy_from is not None and new_apy_to is not None:
        try:
            current_apy_from_float = float(current_apy_from)
            new_apy_to_float = float(new_apy_to)
            apy_improvement_bps = int((new_apy_to_float - current_apy_from_float) * 100)  # Convert to basis points
        except (ValueError, TypeError):
            apy_improvement_bps = 0

    # Single natural, conversational prompt
    prompt = f"""You are a DeFi yield optimization agent. Generate a natural language summary of the rebalancing action. Employ an analytical thinking tone.

    {background_knowledge}

    **Current Data (MUST be used accurately):**
    - Source Protocol: {from_protocol}
    - Source APY: {current_apy_from}%
    - Destination Protocol: {to_protocol}
    - Destination APY: {new_apy_to}%
    - APY Improvement: {apy_improvement_bps} basis points
    - Amount Description: {amount_description}

    **Requirements:**
    1. Use ALL the data above accurately - don't change any numbers or protocol names
    2. Sound natural and analytical, like a human trader in serious rumination about their decision
    3. Keep it concise (1-2 sentences)
    4. Show some personality and confidence in the decision
    5. Use natural transitions and varied sentence structures
    6. Do NOT assume any relationships between protocols - they are completely independent entities

    **Your Summary:**"""

    try:
        response = client.chat.completions.create(
            model="o3",
            messages=[
                {"role": "system", "content": "You are an experienced DeFi yield optimization agent. You're confident, analytical, and speak naturally about trading decisions. You always use exact data provided with sound logic and never guess numbers or protocol names."}, 
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error calling OpenAI API: {e}"


def validate_summary_accuracy(summary: str, recommendation: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate that the generated summary contains accurate data.
    
    Args:
        summary: The generated summary text
        recommendation: The original recommendation data
        
    Returns:
        A dictionary with validation results
    """
    from_protocol = recommendation.get("from_protocol", "")
    to_protocol = recommendation.get("to_protocol", "")
    current_apy_from = recommendation.get("current_apy_from", "")
    new_apy_to = recommendation.get("new_apy_to", "")
    
    validation = {
        "is_valid": True,
        "errors": [],
        "warnings": []
    }
    
    # Check if protocol names are present and correct
    if from_protocol and from_protocol not in summary:
        validation["errors"].append(f"Source protocol '{from_protocol}' not found in summary")
        validation["is_valid"] = False
    
    if to_protocol and to_protocol not in summary:
        validation["errors"].append(f"Destination protocol '{to_protocol}' not found in summary")
        validation["is_valid"] = False
    
    # Check if APY values are present (allowing for some formatting variations)
    if current_apy_from and str(current_apy_from) not in summary:
        validation["warnings"].append(f"Source APY '{current_apy_from}%' not found in summary")
    
    if new_apy_to and str(new_apy_to) not in summary:
        validation["warnings"].append(f"Destination APY '{new_apy_to}%' not found in summary")
    
    return validation
