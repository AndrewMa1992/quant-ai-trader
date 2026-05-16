"""
多模型信号融合 (Ensemble)
"""
from typing import Dict, List
import numpy as np
from loguru import logger
from backend.config import model_config


class SignalEnsemble:
    def __init__(self):
        self.weights = model_config.ENSEMBLE_WEIGHTS.copy()
        self._performance: Dict[str, List[float]] = {"transformer": [], "rl_agent": [], "sentiment": [], "technical": []}
        self._total_calls = 0

    def fuse_signals(self, signals: Dict[str, Dict]) -> Dict:
        self._total_calls += 1
        normalized = self._normalize_signals(signals)
        weighted_score, total_confidence = 0.0, 0.0
        details = {}
        for model_name, signal in normalized.items():
            weight = self.weights.get(model_name, 0.25)
            score, confidence = signal.get("score", 0.0), signal.get("confidence", 0.5)
            weighted_score += score * weight * confidence
            total_confidence += weight * confidence
            details[model_name] = {"score": score, "weight": weight, "confidence": confidence}
        final_score = weighted_score / (total_confidence + 1e-8)
        final_confidence = min(total_confidence, 1.0)
        if final_score > 0.15:
            decision, strength = "buy", min(abs(final_score), 1.0)
        elif final_score < -0.15:
            decision, strength = "sell", min(abs(final_score), 1.0)
        else:
            decision, strength = "hold", 0.0
        position_size = self._kelly_position(final_score, final_confidence)
        return {"decision": decision, "strength": strength, "confidence": final_confidence,
                "position_size": position_size, "ensemble_score": float(final_score),
                "details": details, "weights_snapshot": self.weights.copy()}

    def update_performance(self, model_name: str, was_correct: bool):
        if model_name in self._performance:
            self._performance[model_name].append(1.0 if was_correct else 0.0)
            if len(self._performance[model_name]) > 100:
                self._performance[model_name] = self._performance[model_name][-100:]
            self._adjust_weights()

    def _normalize_signals(self, signals):
        normalized = {}
        for name, signal in signals.items():
            entry = {"confidence": signal.get("confidence", 0.5)}
            if name == "transformer":
                dir_val = 1.0 if signal.get("direction") == "up" else -1.0
                entry["score"] = dir_val * signal.get("confidence", 0.5)
            elif name == "rl_agent":
                actions = signal.get("actions", [0.0])
                entry["score"] = np.clip(np.mean(actions) * 2, -1, 1)
            elif name in ("sentiment", "technical"):
                val = 1.0 if signal.get("signal") == "buy" else (-1.0 if signal.get("signal") == "sell" else 0.0)
                entry["score"] = val * signal.get("strength", 0.5)
            else:
                entry["score"] = 0.0
            normalized[name] = entry
        return normalized

    def _adjust_weights(self):
        recent = {}
        for name, perf in self._performance.items():
            recent[name] = np.mean(perf[-20:]) if len(perf) >= 10 else 0.5
        total = sum(recent.values())
        if total > 0:
            for name in self.weights:
                self.weights[name] = recent.get(name, 0.5) / total
        ws = sum(self.weights.values())
        if ws > 0:
            for name in self.weights:
                self.weights[name] /= ws

    def _kelly_position(self, score, confidence):
        if score <= 0: return 0.0
        win_prob = (1 + score * confidence) / 2
        kelly = max(0, (win_prob * 1.0 - (1 - win_prob)) / 1.0)
        return min(kelly * 0.5, model_config.RL_MAX_TRADE_PERCENT)

    def get_status(self):
        return {"weights": self.weights,
                "performance": {n: {"accuracy": round(np.mean(p[-50:]), 3) if p else 0.5, "samples": len(p)}
                                for n, p in self._performance.items()},
                "total_calls": self._total_calls}
