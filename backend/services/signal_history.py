from typing import Dict, List, Optional
from datetime import datetime
from loguru import logger


class SignalHistory:
    MAX_HISTORY = 20

    def __init__(self):
        self._store: Dict[str, List[Dict]] = {}  # ticker -> entries
        self._cycle = 0

    def append(self, ticker: str, signal: Dict) -> None:
        if ticker not in self._store:
            self._store[ticker] = []
        self._cycle += 1
        entry = {
            "cycle": self._cycle,
            "decision": signal.get("decision", "hold"),
            "strength": signal.get("strength", 0.0),
            "confidence": signal.get("confidence", 0.0),
            "timestamp": datetime.now().isoformat(),
        }
        self._store[ticker].append(entry)
        # Trim to MAX_HISTORY
        if len(self._store[ticker]) > self.MAX_HISTORY:
            self._store[ticker] = self._store[ticker][-self.MAX_HISTORY:]

    def get_history(self, ticker: str, limit: int = 20) -> List[Dict]:
        entries = self._store.get(ticker, [])
        return entries[-limit:]

    def get_all_latest(self) -> Dict[str, Dict]:
        return {t: entries[-1] for t, entries in self._store.items() if entries}

    def get_all_history(self, limit: int = 20) -> Dict[str, List[Dict]]:
        return {t: entries[-limit:] for t, entries in self._store.items() if entries}

    def clear(self) -> None:
        self._store.clear()
        self._cycle = 0

    def count(self) -> int:
        return sum(len(e) for e in self._store.values())
