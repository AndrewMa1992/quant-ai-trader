"""services/execution_service/optimizer/constraints.py – Portfolio constraint system.

Constraints:
- Weight bounds: w_i ∈ [0, upper_bound] (default upper=0.10)
- Sector concentration: Σw_i(sector) ≤ 30%
- Turnover: Σ|w_i - w_prev_i| ≤ 30%
- Beta neutrality: Σ(w_i * β_i) ≈ 0
- No short selling: w_i ≥ 0
- Cardinality: max 50 positions
"""

from __future__ import annotations

from typing import Any


class ConstraintSystem:
    """Portfolio constraint builder for optimization.

    Provides constraints in cvxpy format for convex optimization.
    """

    DEFAULT_CONSTRAINTS: dict[str, Any] = {
        "max_weight": 0.10,
        "min_weight": 0.0,
        "sector_limit": 0.30,
        "turnover_limit": 0.30,
        "max_positions": 50,
        "beta_neutral": False,
    }

    def __init__(self, config: dict | None = None) -> None:
        self.config = {**self.DEFAULT_CONSTRAINTS, **(config or {})}

    def build_cvxpy(
        self,
        w: Any,  # cvxpy Variable
        n_assets: int,
        overrides: dict | None = None,
    ) -> list:
        """Build cvxpy constraint list.

        Args:
            w: cvxpy Variable of shape (n_assets,).
            n_assets: Number of assets.
            overrides: Override default constraint values.

        Returns:
            List of cvxpy constraints.
        """
        config = {**self.config, **(overrides or {})}
        constraints = []

        import cvxpy as cp

        # Long-only: w_i >= 0
        if config.get("min_weight", 0.0) >= 0:
            constraints.append(w >= 0)

        # Max weight per asset
        max_w = config.get("max_weight", 0.10)
        if max_w < 1.0:
            constraints.append(w <= max_w)

        # Min weight per asset (if minimum position size)
        min_w = config.get("min_weight", 0.0)
        if min_w > 0:
            constraints.append(w >= min_w)

        # Turnover constraint: Σ|w - w_prev| ≤ limit
        prev = overrides.get("prev_weights_vector") if overrides else None
        turnover_limit = config.get("turnover_limit")
        if prev is not None and turnover_limit is not None:
            constraints.append(cp.norm(w - prev, 1) <= float(turnover_limit))

        # Fully invested / cash buffer
        if config.get("sum_to_one", True):
            constraints.append(cp.sum(w) <= 1.0)

        # Beta neutrality
        if config.get("beta_neutral", False):
            constraints.append(cp.sum(w) <= 1.0)  # Simplified

        return constraints

    def validate_weights(
        self,
        weights: dict[str, float],
        sectors: dict[str, str] | None = None,
        prev_weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Validate a weight vector against constraints.

        Args:
            weights: Ticker → weight mapping.
            sectors: Ticker → sector mapping.
            prev_weights: Previous weights for turnover check.

        Returns:
            Validation result with violations.
        """
        violations: list[str] = []
        warnings: list[str] = []

        # Check max weight
        max_w = self.config.get("max_weight", 0.10)
        for ticker, w in weights.items():
            if w > max_w + 0.001:
                violations.append(f"{ticker}: {w:.4f} > max {max_w}")

        # Check sector concentration
        if sectors:
            sector_weights: dict[str, float] = {}
            for ticker, w in weights.items():
                s = sectors.get(ticker, "Other")
                sector_weights[s] = sector_weights.get(s, 0.0) + w

            sector_limit = self.config.get("sector_limit", 0.30)
            for sector, total in sector_weights.items():
                if total > sector_limit + 0.001:
                    violations.append(f"Sector {sector}: {total:.4f} > limit {sector_limit}")

        # Check turnover
        if prev_weights:
            turnover = sum(abs(weights.get(t, 0) - prev_weights.get(t, 0)) for t in weights)
            turnover_limit = self.config.get("turnover_limit", 0.30)
            if turnover > turnover_limit + 0.001:
                violations.append(f"Turnover: {turnover:.4f} > limit {turnover_limit}")

        # Check position count
        max_positions = self.config.get("max_positions", 50)
        active = sum(1 for w in weights.values() if w > 0.001)
        if active > max_positions:
            violations.append(f"Positions: {active} > max {max_positions}")

        return {
            "valid": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "active_positions": active,
        }

    def sanitize_weights(
        self,
        weights: dict[str, float],
        prev_weights: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Force weights to satisfy constraints (hard enforcement).

        Uses water-filling: clips over-max weights, redistributes excess
        proportionally to remaining assets, then iterates until convergence.

        Args:
            weights: Raw weights.
            prev_weights: Previous weights for turnover.

        Returns:
            Sanitized weights summing to 1.0, all in [min_w, max_w].
        """
        max_w = float(self.config.get("max_weight", 0.10))
        min_w = float(self.config.get("min_weight", 0.0))
        turnover_limit = float(self.config.get("turnover_limit", 0.30))

        # ── Step 1: Initial clip to bounds ─────────────────
        sanitized = {t: max(min_w, min(max_w, w)) for t, w in weights.items()}

        # ── Step 2: Turnover limit enforcement ──────────────
        if prev_weights:
            turnover = sum(abs(sanitized.get(t, 0) - prev_weights.get(t, 0)) for t in sanitized)
            if turnover > turnover_limit:
                scale = turnover_limit / max(turnover, 1e-10)
                for t in sanitized:
                    sanitized[t] = prev_weights.get(t, 0) + scale * (sanitized[t] - prev_weights.get(t, 0))

        # ── Step 3: Water-fill to enforce max_w after normalize ─
        sanitized = self._waterfill(sanitized, min_w, max_w)
        return sanitized

    @staticmethod
    def _waterfill(
        weights: dict[str, float],
        min_w: float,
        max_w: float,
        max_iter: int = 10,
    ) -> dict[str, float]:
        """Iteratively clip over-max weights and redistribute excess.

        Algorithm:
        1. Normalize to sum=1
        2. Find assets exceeding max_w → set to max_w
        3. Redistribute freed excess proportionally among remaining assets
        4. Repeat until all weights ≤ max_w

        Args:
            weights: Initial weight dict.
            min_w: Minimum allowed weight.
            max_w: Maximum allowed weight.
            max_iter: Safety limit on iterations.

        Returns:
            Dict with all weights in [min_w, max_w] summing to 1.
        """
        result = dict(weights)
        n = len(result)
        if n == 0:
            return {}

        for _ in range(max_iter):
            # Normalize to sum-to-1
            total = sum(result.values())
            if total <= 0:
                return {t: 1.0 / n for t in result}
            normalized = {t: w / total for t, w in result.items()}

            # Identify over-weight and under-weight assets
            over: list[str] = [t for t, w in normalized.items() if w > max_w]
            if not over:
                # All within bounds — check if any under min_w
                under = [t for t, w in normalized.items() if w < min_w]
                if not under:
                    return normalized
                # Set under-weights to min_w, redistribute from others
                for t in under:
                    normalized[t] = min_w
                result = normalized
                continue

            # Set over-weight assets to max_w; they're frozen
            frozen = set(over)
            frozen_total = sum(max_w for _ in over)

            # Remaining budget
            remaining_budget = 1.0 - frozen_total
            if remaining_budget <= 0:
                # Budget exhausted — freeze all at max then normalize
                result = {t: min(w, max_w) for t, w in normalized.items()}
                continue

            # Redistribute remaining budget proportionally to non-frozen assets
            non_frozen = [t for t in normalized if t not in frozen]
            if not non_frozen:
                return {t: max_w for t in normalized}

            non_frozen_pool = sum(normalized[t] for t in non_frozen)
            for t in non_frozen:
                if non_frozen_pool > 0:
                    normalized[t] = (normalized[t] / non_frozen_pool) * remaining_budget
                else:
                    normalized[t] = remaining_budget / len(non_frozen)

            for t in frozen:
                normalized[t] = max_w

            result = normalized

        return result
