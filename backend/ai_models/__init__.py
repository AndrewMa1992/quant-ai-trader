"""AI model layer — lazy-load; degrade to stubs if torch is missing."""

import logging
_lg = logging.getLogger(__name__)

_STUB_MODE = False
_stub_cache: dict = {}


def _try_import():
    global _STUB_MODE
    try:
        import torch  # noqa: F401 — probe whether torch is available
        from .predictor import TransformerPredictor
        from .rl_agent import TradingRLAgent
        from .sentiment import SentimentAnalyzer
        from .ensemble import SignalEnsemble
        from .trainer import ModelTrainer
        from .cross_stock import CrossStockCorrelation, cross_stock
        from .gat_network import GATSignalGenerator, gat_network, StockGAT
        return {
            "TransformerPredictor": TransformerPredictor,
            "TradingRLAgent": TradingRLAgent,
            "SentimentAnalyzer": SentimentAnalyzer,
            "SignalEnsemble": SignalEnsemble,
            "ModelTrainer": ModelTrainer,
            "CrossStockCorrelation": CrossStockCorrelation,
            "cross_stock": cross_stock,
            "GATSignalGenerator": GATSignalGenerator,
            "gat_network": gat_network,
            "StockGAT": StockGAT,
        }
    except ImportError as exc:
        _STUB_MODE = True
        _lg.warning("torch unavailable (%s); AI models degraded to stubs", exc)
        return {}


_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        _registry = _try_import()
    return _registry


def __getattr__(name):
    reg = _get_registry()
    if name in reg:
        return reg[name]
    if name.startswith("_"):
        raise AttributeError(name)
    # stub: return a placeholder class (cached to avoid recreating)
    if name not in _stub_cache:
        _lg.debug("AI model %s unavailable (torch missing); returning stub", name)
        _stub_cache[name] = type(name, (), {
            "__init__": lambda self, *a, **kw: None,
            "load": lambda self: False,
            "is_ready": lambda self: False,
            "model": None,  # GAT stub must expose .model to avoid AttributeError
            "predict_signal": lambda self, *a, **kw: {},
            "fuse_signals": lambda self, *a, **kw: {"decision": "hold", "strength": 0.0, "confidence": 0.0, "position_size": 0.0, "ensemble_score": 0.0, "details": {}},
            "analyze_and_trade": lambda self, *a, **kw: {},
            "load_or_retrain": lambda self: (False, False),
            "get_signal": lambda self, *a, **kw: {"signal": "neutral", "strength": 0.0, "confidence": 0.0},
            "compute_sector_momentum": lambda self, *a, **kw: None,
            "get_cross_stock_signal": lambda self, *a, **kw: {},
            "get_training_summary": lambda self: {"transformer": "stub", "rl_agent": "stub"},
            "train_all": lambda self, *a, **kw: None,
        })
    return _stub_cache[name]


__all__ = [
    "TransformerPredictor", "TradingRLAgent", "SentimentAnalyzer",
    "SignalEnsemble", "ModelTrainer", "CrossStockCorrelation", "cross_stock",
    "GATSignalGenerator", "gat_network", "StockGAT",
]
