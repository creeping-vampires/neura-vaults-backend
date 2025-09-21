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
    Background on our available lending protocols:
    - **HyperLend**: A stable, well-established protocol known for reliable but generally conservative yields. It follows a standard kinked interest rate model.
    - **HyperFi**: A sister protocol to HyperLend, often offering slightly more aggressive yields with a similar risk profile.
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

    # Construct a very specific prompt template to get consistent results
    prompt = f"""You are a DeFi yield optimization agent. Generate a concise summary of the rebalancing action.

    {background_knowledge}

    **Current Data:**
    - Source Protocol: {from_protocol}
    - Source APY: {current_apy_from}%
    - Destination Protocol: {to_protocol}
    - Destination APY: {new_apy_to}%
    - APY Improvement: {apy_improvement_bps} basis points
    - Amount Description: {amount_description}

    Generate a summary that follows EXACTLY this template, replacing the placeholders with the appropriate values:
    "The vault currently has assets allocated in [SOURCE_PROTOCOL], yielding [SOURCE_APY]%. However, [DESTINATION_PROTOCOL] is showing a higher APY of [DESTINATION_APY]%, giving us a [APY_IMPROVEMENT] bps improvement. Based on suggestion from Optimizer Agent moving [AMOUNT_DESCRIPTION] from [SOURCE_PROTOCOL] into [DESTINATION_PROTOCOL]. This ensures the vault is always positioned in the highest-yielding opportunity."

    **Your Summary:**
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a Santient yield optimization agent. your name is Santient"}, 
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=150
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error calling OpenAI API: {e}"
