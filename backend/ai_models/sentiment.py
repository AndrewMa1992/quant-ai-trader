"""
FinBERT → FinGPT upgraded market-sentiment analysis.
Model: yiyanghkust/finbert-tone (SOTA financial-text sentiment)
      + multi-source ensemble (VADER + finance keywords)
Sources: East Money / Sina News + FinBERT-tone
"""
import time
import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
from loguru import logger
from configs.settings import settings

NEWS_CACHE_FILE = Path(settings.CACHE_DIR) / "news_cache.json"
NEWS_CACHE_TTL = 1800  # 30-minute cache

# Upgraded model: ProsusAI/finbert → yiyanghkust/finbert-tone
# finbert-tone is tuned for financial sentiment (10-Ks + earnings calls)
PRIMARY_MODEL = settings.MODEL_SENTIMENT_MODEL  # Default: yiyanghkust/finbert-tone
FALLBACK_MODEL = "ProsusAI/finbert"  # Fall back to the original


class SentimentAnalyzer:
    """Upgraded sentiment analyzer — FinBERT-tone + multi-source ensemble."""

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.vader = None  # VADER sentiment (lightweight)
        self._finbert_loaded = False
        self._vader_loaded = False
        self._news_cache: Dict[str, Dict] = {}
        self._load_news_cache()
        self._init_models()
        logger.info(f"Sentiment analyzer ready (FinBERT-tone={'✅' if self._finbert_loaded else '❌ keyword'}, "
                    f"VADER={'✅' if self._vader_loaded else '❌'})")

    # ============================================================
    # Model load — multi-level fallback
    # ============================================================
    def _init_models(self):
        """Initialize sentiment models (multi-level fallback; skip quickly if offline)."""
        import os
        import socket

        # Check network connectivity
        has_network = False
        try:
            socket.setdefaulttimeout(3)
            socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("huggingface.co", 443))
            has_network = True
        except Exception:
            pass

        skip_flag = os.environ.get("SKIP_FINBERT_DOWNLOAD", "").lower() in ("1", "true", "yes")

        if not has_network or skip_flag:
            reason = "SKIP_FINBERT_DOWNLOAD" if skip_flag else "no network"
            logger.info(f"🌐 {reason} — skipping Transformer model download")
            self._init_vader()
            return

        # 1. Try FinBERT-tone (upgraded)
        loaded = self._try_load_model(PRIMARY_MODEL, "FinBERT-tone")
        if loaded:
            self._init_vader()
            return

        # 2. Fall back to original FinBERT
        loaded = self._try_load_model(FALLBACK_MODEL, "FinBERT")
        if loaded:
            self._init_vader()
            return

        # 3. VADER + keywords only
        logger.warning("All Transformer models failed to load; using VADER + keywords")
        self._init_vader()

    def _try_load_model(self, model_name: str, label: str) -> bool:
        """Attempt to load a Transformer model."""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            logger.info(f"📥 Loading {label} ({model_name})...")
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_name, cache_dir=str(settings.HF_CACHE)
            )
            self.model = AutoModelForSequenceClassification.from_pretrained(
                model_name, cache_dir=str(settings.HF_CACHE)
            )
            self._finbert_loaded = True
            logger.info(f"✅ {label} loaded")
            return True
        except Exception as e:
            logger.warning(f"⚠️ {label} failed to load: {e}")
            return False

    def _init_vader(self):
        """Initialize VADER sentiment (lightweight fallback + ensemble boost)."""
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            self.vader = SentimentIntensityAnalyzer()

            # Add finance-domain lexicon to VADER
            finance_lexicon = {
                "beat": 2.0, "beats": 2.0, "upgrade": 2.5, "upgraded": 2.5,
                "downgrade": -2.5, "downgraded": -2.5, "miss": -2.0, "misses": -2.0,
                "surge": 3.0, "surged": 3.0, "plunge": -3.0, "plunged": -3.0,
                "rally": 2.0, "rallied": 2.0, "selloff": -2.5, "sell-off": -2.5,
                "bullish": 2.5, "bearish": -2.5, "outperform": 2.0, "underperform": -2.0,
                "guidance raised": 3.0, "guidance cut": -3.0, "revenue beat": 2.5,
                "earnings beat": 2.5, "earnings miss": -2.5, "profit warning": -3.0,
                "buyback": 1.5, "dividend increase": 2.0, "dividend cut": -2.5,
                "layoff": -1.5, "restructuring": -0.5, "acquisition": 1.0,
                "merger": 0.5, "bankruptcy": -4.0, "default": -3.5,
                "lawsuit": -2.0, "investigation": -2.0, "fine": -1.5,
                "blockbuster": 3.0, "breakthrough": 2.5, "record high": 3.0,
                "record low": -3.0, "all-time high": 3.0, "all-time low": -3.0,
            }
            self.vader.lexicon.update(finance_lexicon)
            self._vader_loaded = True
            logger.info("✅ VADER loaded (finance lexicon enhanced)")
        except ImportError:
            logger.debug("VADER not installed; using keyword fallback only")
            self._vader_loaded = False

    # ============================================================
    # News fetch (yfinance)
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
        """Fetch ticker-related headlines (China onshore sources first)."""
        cache_key = f"{ticker}_{int(time.time() // NEWS_CACHE_TTL)}"

        if cache_key in self._news_cache:
            return self._news_cache[cache_key]

        headlines = []

        # 1. Try East Money news API
        try:
            import requests
            if ticker.endswith(".HK"):
                # HK news
                code = ticker.replace(".HK", "")
                url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=cb&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{code}%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%7D"
            else:
                # US news
                url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=cb&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{ticker}%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%7D"
            r = requests.get(url, timeout=10, headers={"Referer": "https://so.eastmoney.com/"})
            if r.status_code == 200:
                import re
                json_str = re.sub(r'^cb\(', '', r.text).rstrip(')')
                data = json.loads(json_str)
                articles = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
                for art in articles[:max_items]:
                    title = art.get("title", "").replace("<em>", "").replace("</em>", "")
                    if title:
                        headlines.append(title)
        except Exception as e:
            logger.debug(f"East Money news fetch failed {ticker}: {e}")

        # 2. Try yfinance (may work on overseas networks)
        if not headlines:
            try:
                import yfinance as yf
                stock = yf.Ticker(ticker)
                news = stock.news[:max_items] if stock.news else []
                for item in news:
                    title = item.get("title", "")
                    if title:
                        headlines.append(title)
            except Exception as e:
                logger.debug(f"yfinance news fetch failed {ticker}: {e}")

        # 3. Fallback
        if not headlines:
            headlines.append(f"{ticker} market activity")

        self._news_cache[cache_key] = headlines
        self._save_news_cache()
        return headlines

    # ============================================================
    # Core sentiment methods
    # ============================================================
    def analyze_text(self, text: str) -> Dict:
        """
        Multi-source sentiment ensemble:
        1. FinBERT-tone (primary) — financial-domain SOTA
        2. VADER (auxiliary) — lightweight rule engine
        3. Keywords (fallback) — last resort when no model is available

        Final score = 0.6 * finbert + 0.3 * vader + 0.1 * keyword
        """
        finbert_result = None
        vader_result = None
        keyword_result = self._keyword_sentiment(text)

        # Primary: Transformer
        if self._finbert_loaded:
            finbert_result = self._finbert_predict(text)

        # Auxiliary: VADER
        if self._vader_loaded:
            vader_result = self._vader_predict(text)

        # === Ensemble fusion ===
        if finbert_result and vader_result:
            # Three-source blend
            score = 0.6 * finbert_result["score"] + 0.3 * vader_result["score"] + 0.1 * keyword_result["score"]
            return {
                "label": "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral"),
                "positive": float(np.clip(score, 0, 1)),
                "negative": float(np.clip(-score, 0, 1)),
                "neutral": float(1 - abs(np.clip(score, -1, 1))),
                "score": float(score),
                "source": "finbert-tone+vader",
                "finbert_score": finbert_result["score"],
                "vader_score": vader_result["score"],
            }
        elif finbert_result:
            score = 0.7 * finbert_result["score"] + 0.3 * keyword_result["score"]
            return {
                "label": "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral"),
                "positive": float(np.clip(score, 0, 1)),
                "negative": float(np.clip(-score, 0, 1)),
                "neutral": float(1 - abs(np.clip(score, -1, 1))),
                "score": float(score),
                "source": "finbert-tone+keyword",
            }
        elif vader_result:
            score = 0.5 * vader_result["score"] + 0.5 * keyword_result["score"]
            return {
                "label": "positive" if score > 0.15 else ("negative" if score < -0.15 else "neutral"),
                "positive": float(np.clip(score, 0, 1)),
                "negative": float(np.clip(-score, 0, 1)),
                "neutral": float(1 - abs(np.clip(score, -1, 1))),
                "score": float(score),
                "source": "vader+keyword",
            }
        else:
            return keyword_result

    def _finbert_predict(self, text: str) -> Optional[Dict]:
        """FinBERT-tone inference."""
        try:
            inputs = self.tokenizer(
                text, return_tensors="pt", max_length=512,
                truncation=True, padding=True
            )
            outputs = self.model(**inputs)
            probs = outputs.logits.softmax(dim=-1).detach().numpy()[0]
            labels = ["negative", "neutral", "positive"]
            score = float(probs[2] - probs[0])
            return {
                "label": labels[probs.argmax()],
                "score": score,
                "probs": {l: float(p) for l, p in zip(labels, probs)},
            }
        except Exception as e:
            logger.debug(f"Transformer inference failed: {e}")
            return None

    def _vader_predict(self, text: str) -> Optional[Dict]:
        """VADER inference."""
        try:
            scores = self.vader.polarity_scores(text)
            return {
                "label": "positive" if scores["compound"] > 0.05 else (
                    "negative" if scores["compound"] < -0.05 else "neutral"),
                "score": float(scores["compound"]),
                "vader_detail": scores,
            }
        except Exception:
            return None

    def analyze_headlines(self, headlines: List[str]) -> Dict:
        """Batch-analyze headlines and return aggregated sentiment."""
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
        Sentiment trading signal for a single ticker.
        1. Fetch latest headlines
        2. FinBERT analysis
        3. Return a signal
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
                "source": sentiment.get("source", "finbert-tone"),
            }
        elif score < -0.15:
            return {
                "signal": "sell",
                "strength": min(abs(score) * 2, 1.0),
                "sentiment_score": score,
                "headlines": headlines,
                "source": sentiment.get("source", "finbert-tone"),
            }
        return {
            "signal": "neutral",
            "strength": 0.0,
            "sentiment_score": score,
            "headlines": headlines,
            "source": sentiment.get("source", "finbert-tone"),
        }

    # ============================================================
    # Fallback: keyword sentiment (when FinBERT is unavailable)
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
    # Helpers
    # ============================================================
    def is_ready(self) -> bool:
        return self._finbert_loaded

    def clear_cache(self):
        self._news_cache = {}
        if NEWS_CACHE_FILE.exists():
            NEWS_CACHE_FILE.unlink()
        logger.info("News cache cleared")
