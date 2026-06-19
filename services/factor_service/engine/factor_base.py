"""services/factor_service/engine/factor_base.py – Abstract base class for all factors.

Every factor must:
1. Inherit from FactorBase
2. Define: name, category, subcategory, description
3. Implement: compute(df: pd.DataFrame) -> pd.Series

Input DataFrame must contain OHLCV columns plus any required prior factors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Optional

import pandas as pd


class FactorBase(ABC):
    """Abstract base class for all quant factors.

    Subclasses must implement compute() which takes a DataFrame
    with OHLCV data (plus any pre-computed factors) and returns
    a Series of factor values indexed by date.

    Attributes:
        factor_id: Unique factor identifier (e.g. 'F001').
        name: Human-readable factor name.
        category: Factor category (technical/fundamental/alternative/microstructure).
        subcategory: Finer classification.
        description: What the factor measures.
        formula_ref: Academic/professional reference.
        lookback_default: Default lookback window in trading days.
        frequency: Update frequency.
        neutralizable: Whether sector/market-cap neutralization is appropriate.
        direction: Expected alpha sign (1=positive, -1=negative, 0=neutral).
    """

    factor_id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    category: ClassVar[str] = "technical"
    subcategory: ClassVar[str] = ""
    description: ClassVar[str] = ""
    formula_ref: ClassVar[str] = ""
    lookback_default: ClassVar[int] = 21
    frequency: ClassVar[str] = "daily"
    neutralizable: ClassVar[bool] = True
    direction: ClassVar[int] = 0

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """Compute factor values from OHLCV + prior-factor data.

        Args:
            df: DataFrame with columns: open, high, low, close, adj_close, volume,
                plus any previously computed factor columns.
                Must have a DatetimeIndex.

        Returns:
            Series of factor values indexed by date.
        """
        ...

    def validate_input(self, df: pd.DataFrame) -> None:
        """Validate that the input DataFrame has required columns.

        Args:
            df: Input DataFrame to validate.

        Raises:
            ValueError: If required columns are missing.
        """
        required = {"close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"Factor '{self.name}' requires columns: {missing}. "
                f"Available: {list(df.columns)}"
            )

        if len(df) < 2:
            raise ValueError(
                f"Factor '{self.name}' requires at least 2 rows, got {len(df)}"
            )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(id={self.factor_id}, name={self.name})>"

    def to_dict(self) -> dict:
        """Serialize factor metadata to dictionary."""
        return {
            "id": self.factor_id,
            "name": self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "description": self.description,
            "formula_ref": self.formula_ref,
            "lookback_default": self.lookback_default,
            "frequency": self.frequency,
            "neutralizable": self.neutralizable,
            "direction": self.direction,
        }
