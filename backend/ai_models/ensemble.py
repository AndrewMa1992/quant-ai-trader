"""
Multi-Model Signal Ensemble (Advanced)
- Dynamic profit-weighted voting
- GNN cross-stock signal integration
- Sharpe-aware Kelly position sizing
"""
from typing import Dict, List
import numpy as np
from backend.config import model_config


class SignalEnsemble:
    def __init__(self):
        self.weights = model_config.ENSEMBLE_WEIGHTS.copy()
        self._performance: Dict[str, List[float]] = {
            "transformer": [], "rl_agent": [], "sentiment": [],
            "technical": [], "cross_stock": [], "macro": [],
        }
        self._total_calls = 0
        self._profit_attribution: Dict[str, float] = {
            "transformer": 0.0, "rl_agent": 0.0, "sentiment": 0.0,
            "technical": 0.0, "cross_stock": 0.0, "macro": 0.0,
        }

    def fuse_signals(self, signals: Dict[str, Dict], cross_stock_boost: float = 1.0) -> Dict:
        """
        Fuse signals from all models.
        Args:
            signals: {model_name: signal_dict}
            cross_stock_boost: optional boost factor from cross-stock analysis
        """
        self._total_calls += 1
        normalized = self._normalize_signals(signals)
        weighted_score, total_confidence = 0.0, 0.0
        details = {}

        for model_name, signal in normalized.items():
            weight = self.weights.get(model_name, 0.2)
            if weight <= 0:
                continue
            score = signal.get("score", 0.0)
            confidence = signal.get("confidence", 0.5)
            weighted_score += score * weight * confidence
            total_confidence += weight * confidence
            details[model_name] = {
                "score": round(score, 4),
                "weight": round(weight, 3),
                "confidence": round(confidence, 3),
            }

        if total_confidence < 0.001:
            return {
                "decision": "hold", "strength": 0.0, "confidence": 0.0,
                "position_size": 0.0, "ensemble_score": 0.0,
                "details": details, "weights_snapshot": self.weights.copy(),
            }

        final_score = weighted_score / total_confidence
        # Apply cross-stock boost
        final_score *= cross_stock_boost
        # Confidence: weighted average with profit track record
        final_confidence = min(total_confidence * 3.0, 1.0)

        # Decision with adaptive thresholds
        threshold = 0.03  # Lowered for sensitivity
        if final_score > threshold:
            decision, strength = "buy", min(abs(final_score) * 3.5, 1.0)
        elif final_score < -threshold:
            decision, strength = "sell", min(abs(final_score) * 3.5, 1.0)
        else:
            decision, strength = "hold", 0.0

        position_size = self._kelly_position(final_score, final_confidence)

        return {
            "decision": decision,
            "strength": strength,
            "confidence": final_confidence,
            "position_size": position_size,
            "ensemble_score": float(final_score),
            "details": details,
            "weights_snapshot": self.weights.copy(),
        }

    def update_performance(self, model_name: str, profit_contribution: float):
        """Track profit contribution per model (not just accuracy)"""
        if model_name in self._performance:
            self._performance[model_name].append(profit_contribution)
            self._profit_attribution[model_name] += profit_contribution
            if len(self._performance[model_name]) > 200:
                self._performance[model_name] = self._performance[model_name][-200:]
            self._adjust_weights()

    def _normalize_signals(self, signals):
        normalized = {}
        for name, signal in signals.items():
            entry = {"confidence": signal.get("confidence", 0.5)}

            if name == "transformer":
                dir_val = 1.0 if signal.get("direction") == "up" else -1.0
                entry["score"] = dir_val * signal.get("confidence", 0.5)

            elif name == "rl_agent":
                # New per-stock RL signal format
                rl_signal = signal.get("signal", "neutral")
                if rl_signal == "buy":
                    entry["score"] = signal.get("strength", 0.5)
                elif rl_signal == "sell":
                    entry["score"] = -signal.get("strength", 0.5)
                else:
                    entry["score"] = 0.0
                entry["confidence"] = signal.get("confidence", 0.4)

            elif name == "cross_stock":
                cs_signal = signal.get("signal", "neutral")
                if cs_signal == "buy":
                    entry["score"] = signal.get("strength", 0.3)
                elif cs_signal == "sell":
                    entry["score"] = -signal.get("strength", 0.3)
                else:
                    entry["score"] = 0.0
                entry["confidence"] = 0.35  # Moderate confidence for GNN signals

            elif name in ("sentiment", "technical", "macro"):
                val = 1.0 if signal.get("signal") == "buy" else (
                    -1.0 if signal.get("signal") == "sell" else 0.0)
                entry["score"] = val * signal.get("strength", 0.5)

            else:
                entry["score"] = 0.0

            normalized[name] = entry
        return normalized

    def _adjust_weights(self):
        """Dynamic weight adjustment based on profit contribution (single-pass normalization)"""
        recent = {}
        for name in self._performance.keys():
            perf = self._performance[name]
            if len(perf) >= 10:
                avg_profit = np.mean(perf[-30:])
                recent[name] = max(avg_profit + 0.5, 0.1)
            else:
                recent[name] = 0.5

        # Apply raw weights to all tracked models, defaulting for untracked
        for name in self.weights:
            self.weights[name] = recent.get(name, 0.25)

        # Single-pass normalization (eliminates redundant second pass)
        ws = sum(self.weights.values())
        if ws > 0:
            for name in self.weights:
                self.weights[name] /= ws

    def _kelly_position(self, score, confidence):
        """Kelly criterion with Sharpe-aware adjustment"""
        if score <= 0:
            return 0.0
        # Win probability estimated from score and confidence
        win_prob = (1.0 + score * confidence) / 2.0
        win_prob = np.clip(win_prob, 0.3, 0.8)
        # Kelly fraction: f = (p*b - q) / b where b=1.0 (symmetric payoff)
        kelly = max(0.0, (win_prob * 1.0 - (1.0 - win_prob)) / 1.0)
        # Half-Kelly for safety, capped at max position
        return min(kelly * 0.5, model_config.RL_MAX_TRADE_PERCENT)

    def get_status(self):
        return {
            "weights": self.weights,
            "profit_attribution": self._profit_attribution,
            "performance": {
                n: {
                    "avg_profit": round(np.mean(p[-50:]), 4) if p else 0.0,
                    "samples": len(p)
                }
                for n, p in self._performance.items()
            },
            "total_calls": self._total_calls,
        }
