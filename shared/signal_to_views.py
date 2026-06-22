"""
Signal → Black-Litterman Views 转换器
=====================================
将模型推理输出的原始信号转为 Black-Litterman 模型所需的 views 格式。
"""
from typing import List, Dict


def signals_to_bl_views(signals: List[Dict]) -> List[Dict]:
    """Convert model signals to Black-Litterman views.

    Args:
        signals: List of signal dicts, each containing:
            - ticker (str): 股票代码
            - signal (float): 信号值 ∈ [-1, 1]
            - confidence (float): 置信度 ∈ [0, 1]

    Returns:
        List of BL view dicts, each containing:
            - ticker (str): 股票代码
            - direction (str): "absolute" 绝对收益观点
            - return_pct (float): 年化预期收益（小数）
            - confidence (float): 置信度

    Rules:
        - |signal| >= 0.3 → 生成 view
        - 年化收益 = signal × 0.2（最大 ±20%）
        - 过滤低于阈值的信号
    """
    views: List[Dict] = []

    for entry in signals:
        ticker: str = entry.get("ticker", "")
        signal_val: float = entry.get("signal", 0.0)
        confidence: float = entry.get("confidence", 0.5)

        # 规则1: 信号强度需达到阈值（与管线 min_threshold 一致）
        if abs(signal_val) < 0.05:
            continue

        # 规则2: 年化收益 = signal × 0.2（max ±20%）
        annualized_return: float = signal_val * 0.2

        # Clamp to [-0.20, 0.20]
        annualized_return = max(-0.20, min(0.20, annualized_return))

        views.append({
            "ticker": ticker,
            "direction": "absolute",
            "return_pct": round(annualized_return, 6),
            "confidence": round(confidence, 4),
        })

    # 按置信度降序排列
    views.sort(key=lambda v: v["confidence"], reverse=True)

    return views


def dict_signals_to_bl_views(signals_dict: Dict[str, Dict]) -> List[Dict]:
    """Convert a dict-based signals format to BL views.

    Args:
        signals_dict: {ticker: {"signal": float, "confidence": float}, ...}

    Returns:
        List of BL view dicts (same format as signals_to_bl_views).
    """
    signals_list: List[Dict] = []
    for ticker, info in signals_dict.items():
        signals_list.append({
            "ticker": ticker,
            "signal": info.get("signal", info.get("strength", 0.0)),
            "confidence": info.get("confidence", 0.5),
        })
    return signals_to_bl_views(signals_list)


def validate_views(views: List[Dict]) -> List[Dict]:
    """Validate and clean BL views.

    Ensures all required fields present and within valid ranges.
    Returns cleaned list (invalid entries removed).
    """
    valid: List[Dict] = []
    for view in views:
        ticker = view.get("ticker", "")
        if not ticker or not isinstance(ticker, str):
            continue

        return_pct = view.get("return_pct", 0.0)
        if not isinstance(return_pct, (int, float)):
            continue
        if abs(return_pct) > 1.0:  # sanity check: no view > 100% annual
            continue

        confidence = view.get("confidence", 0.5)
        if not isinstance(confidence, (int, float)):
            continue
        confidence = max(0.0, min(1.0, confidence))

        valid.append({
            "ticker": ticker,
            "direction": view.get("direction", "absolute"),
            "return_pct": round(float(return_pct), 6),
            "confidence": round(float(confidence), 4),
        })

    return valid
