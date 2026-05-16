from pydantic import BaseModel
from typing import Dict, List, Optional
from datetime import datetime


class ModelDetail(BaseModel):
    score: float
    weight: float
    confidence: float


class SignalCard(BaseModel):
    ticker: str
    decision: str
    strength: float
    confidence: float
    position_size: float
    ensemble_score: float
    details: Dict[str, ModelDetail]
    timestamp: str


class RunAnalysisRequest(BaseModel):
    tickers: Optional[List[str]] = None


class RunAnalysisResponse(BaseModel):
    status: str
    total: int
    timestamp: str
    signals: Dict[str, SignalCard]


class SignalHistoryEntry(BaseModel):
    cycle: int
    decision: str
    strength: float
    confidence: float
    timestamp: str


class SignalHistoryResponse(BaseModel):
    ticker: str
    history: List[SignalHistoryEntry]
