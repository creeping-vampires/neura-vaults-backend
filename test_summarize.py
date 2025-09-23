#!/usr/bin/env python3
"""
Simple test script that calls summarize_strategy_with_gpt on dummy data.
"""

import os
import sys
import json
from typing import Dict, Any

# Add the project root to the Python path to import the module
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# Define a mock implementation for testing
def mock_summarize_strategy(recommendation: Dict[str, Any]) -> str:
    """Mock implementation that returns a predefined summary."""
    from_protocol = recommendation.get("from_protocol", "SourceProtocol")
    to_protocol = recommendation.get("to_protocol", "DestProtocol")
    current_apy_from = recommendation.get("current_apy_from", "0")
    new_apy_to = recommendation.get("new_apy_to", "0")
    amount_desc = recommendation.get("amount_description", "some assets")
    
    return f"MOCK SUMMARY: Moving {amount_desc} from {from_protocol} ({current_apy_from}%) to {to_protocol} ({new_apy_to}%) to optimize yield based on current market conditions."

# Try to import the real function, fall back to mock if OpenAI is not available
try:
    from data.utils.strategy_summarizer import summarize_strategy_with_gpt
    print("Using actual summarize_strategy_with_gpt function")
    
    # Check if OpenAI API key is set
    if not os.environ.get("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY not set, using mock implementation")
        summarize_strategy_with_gpt = mock_summarize_strategy
        
except ImportError:
    print("Warning: Could not import strategy_summarizer, using mock implementation")
    summarize_strategy_with_gpt = mock_summarize_strategy

# Define dummy data
dummy_recommendation = {
    "action": "reallocate",
    "from_protocol": "HyperLend",
    "to_protocol": "Felix",
    "amount": 1000000000000000000,
    "amount_description": "1.0 USDe",
    "current_apy_from": 12.5,
    "new_apy_to": 18.7,
    "reason": "Moving funds from HyperLend to Felix offers the highest resulting APY.",
    "current_best_pool": "Felix"
}

# Call the function
print("Calling summarize_strategy_with_gpt with dummy data...")
summary = summarize_strategy_with_gpt(dummy_recommendation)
print("\nGenerated Summary:")
print(summary)
