"""services/risk_service/barra/covariance.py – Covariance estimation.

Ledoit-Wolf Shrinkage: Σ_shrink = δ * F + (1 - δ) * S
where F is the structured (constant-correlation) target and S is sample covariance.
Exponential weighting with half-life (default 60 days).
Eigenvalue floor at 1e-8.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from loguru import logger

from services.data_service.storage.parquet_store import ParquetStore
from services.risk_service.config import risk_config


class CovarianceEstimator:
    """Estimates robust covariance matrix using Ledoit-Wolf shrinkage.

    Attributes:
        halflife: EWMA half-life in trading days.
        eigenvalue_floor: Minimum eigenvalue threshold.
    """

    def __init__(
        self,
        halflife: int | None = None,
        eigenvalue_floor: float | None = None,
    ) -> None:
        self.halflife = halflife or risk_config.BARRA_HALFLIFE
        self.eigenvalue_floor = eigenvalue_floor or risk_config.BARRA_EIGENVALUE_FLOOR
        self._lambda: float = 0.5 ** (1.0 / self.halflife)  # EWMA decay
        self._store = ParquetStore()

    def compute(self, tickers: list[str]) -> np.ndarray:
        """Compute shrinkage covariance matrix for a list of tickers.

        Args:
            tickers: List of ticker symbols.

        Returns:
            Covariance matrix as numpy array (n_tickers × n_tickers).
        """
        returns_matrix = self._build_returns_matrix(tickers)
        if returns_matrix is None or returns_matrix.shape[1] < 2:
            n = len(tickers)
            return np.eye(n) * 0.04  # Default 20% annual vol

        # Exponential weights
        n_obs = returns_matrix.shape[0]
        weights = np.array([self._lambda ** (n_obs - 1 - i) for i in range(n_obs)])
        weights /= weights.sum()

        # Weighted mean
        weighted_mean = (returns_matrix * weights[:, np.newaxis]).sum(axis=0)

        # Weighted sample covariance
        centered = returns_matrix - weighted_mean
        S = (centered * weights[:, np.newaxis]).T @ centered
        S = S / (1.0 - weights**2).sum()

        # Shrinkage target: constant correlation
        F = self._constant_correlation_target(S)

        # Shrinkage intensity (Ledoit-Wolf)
        delta = self._compute_shrinkage_intensity(centered, weights, S, F)
        delta = max(0.0, min(1.0, delta))

        # Shrunk covariance
        Sigma = delta * F + (1.0 - delta) * S

        # Eigenvalue adjustment
        Sigma = self._adjust_eigenvalues(Sigma)

        logger.info(f"Covariance: {Sigma.shape[0]}x{Sigma.shape[1]}, shrinkage={delta:.3f}, condition={np.linalg.cond(Sigma):.1f}")
        return Sigma

    def _build_returns_matrix(self, tickers: list[str]) -> np.ndarray | None:
        """Build a returns matrix from stored data.

        Args:
            tickers: List of tickers.

        Returns:
            (n_obs, n_tickers) numpy array or None.
        """
        ret_list: list[pd.Series] = []

        for ticker in tickers:
            df = self._store.read_daily(ticker)
            if df is None or len(df) < 63:
                continue
            col = "adj_close" if "adj_close" in df.columns else "close"
            ret = df[col].pct_change().dropna().tail(252)
            if len(ret) < 30:
                continue
            ret_list.append(ret)

        if len(ret_list) < 2:
            return None

        # Align by date
        combined = pd.concat(ret_list, axis=1, keys=tickers)
        combined = combined.dropna()
        return combined.values

    def _constant_correlation_target(self, S: np.ndarray) -> np.ndarray:
        """Build constant-correlation shrinkage target.

        Args:
            S: Sample covariance matrix.

        Returns:
            Constant-correlation target matrix.
        """
        n = S.shape[0]
        vols = np.sqrt(np.diag(S))
        corr = S / (vols[:, np.newaxis] * vols[np.newaxis, :] + 1e-10)

        # Average off-diagonal correlation
        off_diag = corr[~np.eye(n, dtype=bool)]
        rho_bar = float(off_diag.mean()) if len(off_diag) > 0 else 0.0

        F = np.eye(n) * (vols**2)
        for i in range(n):
            for j in range(i + 1, n):
                F[i, j] = F[j, i] = rho_bar * vols[i] * vols[j]

        return F

    def _compute_shrinkage_intensity(
        self,
        centered: np.ndarray,
        weights: np.ndarray,
        S: np.ndarray,
        F: np.ndarray,
    ) -> float:
        """Compute Ledoit-Wolf shrinkage intensity δ.

        Args:
            centered: Mean-centered returns.
            weights: EWMA weights.
            S: Sample covariance.
            F: Target covariance.

        Returns:
            Shrinkage intensity in [0, 1].
        """
        n_t, n_k = centered.shape
        if n_t < 10:
            return 0.5

        # Pi matrix (asymptotic variance of S)
        diff = S - F
        pi = (diff**2).sum()

        # Rho (asymptotic covariance)
        rho = 0.0
        for i in range(n_t):
            x = centered[i:i+1]
            xSx = float(x @ S @ x.T)
            rho += weights[i] * ((xSx - np.trace(S))**2)

        gamma = (S - F).ravel() @ (S - F).ravel()
        kappa = (pi - rho) / max(gamma, 1e-10)

        return float(max(0.0, min(1.0, kappa / n_t)))

    def _adjust_eigenvalues(self, Sigma: np.ndarray) -> np.ndarray:
        """Ensure all eigenvalues are above floor, adjust condition number.

        Args:
            Sigma: Covariance matrix.

        Returns:
            Adjusted positive-definite covariance matrix.
        """
        eigvals, eigvecs = np.linalg.eigh(Sigma)
        eigvals = np.maximum(eigvals, self.eigenvalue_floor)

        # Reconstruct
        Sigma_adj = eigvecs @ np.diag(eigvals) @ eigvecs.T

        # Ensure symmetry
        return (Sigma_adj + Sigma_adj.T) / 2.0

    def compute_correlation_from_covariance(self, Sigma: np.ndarray) -> np.ndarray:
        """Convert covariance to correlation matrix.

        Args:
            Sigma: Covariance matrix.

        Returns:
            Correlation matrix.
        """
        vols = np.sqrt(np.diag(Sigma))
        return Sigma / (vols[:, np.newaxis] * vols[np.newaxis, :] + 1e-10)
