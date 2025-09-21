from langchain.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Union, Optional

class FundsSummaryMessage(BaseModel):
    summary: str
    output_data: Dict[str, str]
    agent_id: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'FundsSummaryMessage':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

class IndicatorsSummaryMessage(BaseModel):
    summary: str
    output_data: Dict[str, Any]
    agent_id: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'IndicatorsSummaryMessage':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

class StrategyMessage(BaseModel):
    summary: str
    output_data: Dict[str, Any]
    agent_id: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StrategyMessage':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
    
    class Config:
        json_schema_extra = {
            "example": {
                "strategy_summary": "Based on technical analysis, we should capitalize on the oversold condition of uETH while taking some profits on uBTC.",
                "trade_opportunities": [
                    {
                        "action": "buy",
                        "token": "uETH",
                        "rationale": "RSI at 32 indicates oversold conditions",
                        "priority": 4,
                        "target_token": "HYPE"
                    }
                ],
                "market_assessment": "Market showing sector rotation from BTC to ETH"
            }
        }

class ValidationMessage(BaseModel):
    summary: str
    output_data: Dict[str, Any]
    agent_id: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ValidationMessage':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
    
    class Config:
        json_schema_extra = {
            "example": {
                "validation_summary": "The strategy is generally sound with strong technical support for the uETH buy recommendation.",
                "validated_opportunities": [
                    {
                        "action": "buy",
                        "token": "uETH",
                        "validation_status": "approved",
                        "comments": "Confirmed oversold conditions",
                        "priority": 4,
                        "target_token": "HYPE"
                    }
                ],
                "risk_assessment": "Strategy has moderate risk with strong technical support."
            }
        }

class TradeSummaryMessage(BaseModel):
    summary: str
    output_data: Optional[Dict[str, Any]] = Field(default_factory=dict)
    agent_id: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradeSummaryMessage':
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()

    class Config:
        json_schema_extra = {
            "example": {
                "trade_summary": "Trade summary text...",
                "transaction": {
                    "to": "0x...",
                    "data": "0x...",
                    "value": "10000000000000000"
                }
            }
        }