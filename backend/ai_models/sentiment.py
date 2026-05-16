"""
FinBERT 市场情绪分析
"""
from typing import Dict, List
import numpy as np
from loguru import logger
from backend.config import model_config


class SentimentAnalyzer:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._use_simulation = True
        self._simulated_sentiment = 0.0
        logger.info("情绪分析器初始化 (模式: 模拟)")

    def _load_model(self):
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            self.tokenizer = AutoTokenizer.from_pretrained(model_config.SENTIMENT_MODEL)
            self.model = AutoModelForSequenceClassification.from_pretrained(model_config.SENTIMENT_MODEL)
            self._use_simulation = False
            logger.info("FinBERT 模型加载完成")
        except Exception as e:
            logger.warning(f"FinBERT 加载失败: {e}")
            self._use_simulation = True

    def analyze_text(self, text: str) -> Dict:
        if self._use_simulation:
            if self.model is None:
                self._load_model()
            if self._use_simulation:
                return self._simulate(text)
        inputs = self.tokenizer(text, return_tensors="pt", max_length=512, truncation=True, padding=True)
        outputs = self.model(**inputs)
        probs = outputs.logits.softmax(dim=-1).detach().numpy()[0]
        labels = ["negative", "neutral", "positive"]
        return {"label": labels[probs.argmax()], "positive": float(probs[2]),
                "negative": float(probs[0]), "neutral": float(probs[1]),
                "score": float(probs[2] - probs[0])}

    def get_signal(self, ticker: str) -> Dict:
        score = self._simulate_market_sentiment(ticker)
        if score > 0.3:
            return {"signal": "buy", "strength": min(abs(score), 1.0), "sentiment_score": score}
        elif score < -0.3:
            return {"signal": "sell", "strength": min(abs(score), 1.0), "sentiment_score": score}
        return {"signal": "neutral", "strength": 0.0, "sentiment_score": score}

    def _simulate(self, text: str) -> Dict:
        positive_words = ["profit","growth","beat","upgrade","bullish","surge","rally","positive","strong","record"]
        negative_words = ["loss","decline","downgrade","bearish","crash","drop","negative","weak","miss"]
        text_lower = text.lower()
        pos = sum(1 for w in positive_words if w in text_lower)
        neg = sum(1 for w in negative_words if w in text_lower)
        total = pos + neg + 1
        score = (pos - neg) / total
        if score > 0.2: label = "positive"
        elif score < -0.2: label = "negative"
        else: label = "neutral"
        return {"label": label, "positive": max(0, score), "negative": max(0, -score),
                "neutral": 1 - abs(score), "score": score}

    def _simulate_market_sentiment(self, ticker: str) -> float:
        import random
        self._simulated_sentiment += random.gauss(0, 0.05)
        self._simulated_sentiment *= 0.95
        self._simulated_sentiment = np.clip(self._simulated_sentiment, -1, 1)
        return self._simulated_sentiment
