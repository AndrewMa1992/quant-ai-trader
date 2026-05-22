"""
FinBERT 市场情绪分析 — 支持实时新闻API
数据源: yfinance news (免费) + FinBERT
"""
import time
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from loguru import logger
from backend.config import model_config, CACHE_DIR

NEWS_CACHE_FILE = CACHE_DIR / "news_cache.json"
NEWS_CACHE_TTL = 1800  # 30分钟缓存


class SentimentAnalyzer:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._use_simulation = False
        self._finbert_loaded = False
        self._news_cache: Dict[str, Dict] = {}
        self._load_news_cache()
        self._init_finbert()
        logger.info("情绪分析器初始化完成")

    # ============================================================
    # FinBERT 模型加载
    # ============================================================
    def _init_finbert(self):
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_config.SENTIMENT_MODEL, cache_dir=str(CACHE_DIR / "huggingface")
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                model_config.SENTIMENT_MODEL, cache_dir=str(CACHE_DIR / "huggingface")
            )
            self._finbert_loaded = True
            logger.info("✅ FinBERT 模型加载完成")
        except Exception as e:
            logger.warning(f"FinBERT 加载失败, 使用关键词模拟: {e}")
            self._finbert_loaded = False

    # ============================================================
    # 新闻获取 (yfinance)
    # ============================================================
    def _load_news_cache(self):
        if NEWS_CACHE_FILE.exists():
            try:
                self._news_cache = json.loads(NEWS_CACHE_FILE.read_text(encoding='utf-8'))
            except Exception:
                self._news_cache = {}

    def _save_news_cache(self):
        NEWS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        NEWS_CACHE_FILE.write_text(json.dumps(self._news_cache, ensure_ascii=False), encoding='utf-8')

    def fetch_news(self, ticker: str, max_items: int = 5) -> List[str]:
        """获取股票相关新闻标题"""
        cache_key = f"{ticker}_{int(time.time() // NEWS_CACHE_TTL)}"

        if cache_key in self._news_cache:
            return self._news_cache[cache_key]

        headlines = []
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            news = stock.news[:max_items] if stock.news else []

            for item in news:
                title = item.get("title", "")
                if title:
                    headlines.append(title)

            if not headlines:
                # fallback: 用公司名搜索
                info = stock.info or {}
                name = info.get("shortName", ticker)
                headlines.append(f"{name} stock trading activity update")

        except Exception as e:
            logger.debug(f"yfinance 新闻获取失败 {ticker}: {e}")
            # fallback: 生成一条中性标题
            headlines.append(f"{ticker} market activity")

        self._news_cache[cache_key] = headlines
        self._save_news_cache()
        return headlines

    # ============================================================
    # 情绪分析核心方法
    # ============================================================
    def analyze_text(self, text: str) -> Dict:
        """FinBERT 单条文本分析"""
        if not self._finbert_loaded:
            return self._keyword_sentiment(text)

        try:
            inputs = self.tokenizer(
                text, return_tensors="pt", max_length=512,
                truncation=True, padding=True
            )
            outputs = self.model(**inputs)
            probs = outputs.logits.softmax(dim=-1).detach().numpy()[0]
            labels = ["negative", "neutral", "positive"]
            return {
                "label": labels[probs.argmax()],
                "positive": float(probs[2]),
                "negative": float(probs[0]),
                "neutral": float(probs[1]),
                "score": float(probs[2] - probs[0]),
            }
        except Exception as e:
            logger.debug(f"FinBERT 推理失败: {e}")
            return self._keyword_sentiment(text)

    def analyze_headlines(self, headlines: List[str]) -> Dict:
        """批量分析新闻标题，返回聚合情绪"""
        if not headlines:
            return {"label": "neutral", "positive": 0.33, "negative": 0.33,
                    "neutral": 0.34, "score": 0.0, "headlines_analyzed": 0}

        scores = []
        for headline in headlines:
            result = self.analyze_text(headline)
            scores.append(result["score"])

        avg_score = float(np.mean(scores))
        return {
            "label": "positive" if avg_score > 0.15 else ("negative" if avg_score < -0.15 else "neutral"),
            "positive": float(np.clip(avg_score, 0, 1)),
            "negative": float(np.clip(-avg_score, 0, 1)),
            "neutral": float(1 - abs(np.clip(avg_score, -1, 1))),
            "score": avg_score,
            "headlines_analyzed": len(headlines),
            "individual_scores": scores,
        }

    def get_signal(self, ticker: str) -> Dict:
        """
        获取单只股票的情绪交易信号
        1. 获取最新新闻标题
        2. FinBERT 分析
        3. 返回信号
        """
        headlines = self.fetch_news(ticker)
        sentiment = self.analyze_headlines(headlines)
        score = sentiment["score"]

        if score > 0.15:
            return {
                "signal": "buy",
                "strength": min(abs(score) * 2, 1.0),
                "sentiment_score": score,
                "headlines": headlines,
                "source": "finbert_live" if self._finbert_loaded else "keyword",
            }
        elif score < -0.15:
            return {
                "signal": "sell",
                "strength": min(abs(score) * 2, 1.0),
                "sentiment_score": score,
                "headlines": headlines,
                "source": "finbert_live" if self._finbert_loaded else "keyword",
            }
        return {
            "signal": "neutral",
            "strength": 0.0,
            "sentiment_score": score,
            "headlines": headlines,
            "source": "finbert_live" if self._finbert_loaded else "keyword",
        }

    # ============================================================
    # Fallback: 关键词情绪（FinBERT 不可用时）
    # ============================================================
    def _keyword_sentiment(self, text: str) -> Dict:
        positive_words = ["profit", "growth", "beat", "upgrade", "bullish",
                         "surge", "rally", "positive", "strong", "record",
                         "gain", "boost", "outperform", "breakthrough"]
        negative_words = ["loss", "decline", "downgrade", "bearish",
                         "crash", "drop", "negative", "weak", "miss",
                         "plunge", "risk", "warning", "layoff", "investigation"]
        text_lower = text.lower()
        pos = sum(1 for w in positive_words if w in text_lower)
        neg = sum(1 for w in negative_words if w in text_lower)
        total = pos + neg + 1
        score = (pos - neg) / total
        if score > 0.15:
            label = "positive"
        elif score < -0.15:
            label = "negative"
        else:
            label = "neutral"
        return {
            "label": label,
            "positive": max(0, score),
            "negative": max(0, -score),
            "neutral": 1 - abs(score),
            "score": score,
        }

    # ============================================================
    # 工具方法
    # ============================================================
    def is_ready(self) -> bool:
        return self._finbert_loaded

    def clear_cache(self):
        self._news_cache = {}
        if NEWS_CACHE_FILE.exists():
            NEWS_CACHE_FILE.unlink()
        logger.info("新闻缓存已清除")
