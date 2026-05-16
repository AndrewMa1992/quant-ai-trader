"""
全球市场数据源
支持美国、中国、香港、日本、欧洲等主要市场
"""

import requests
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import asyncio
import aiohttp
from backend.config import global_config, DEVICE


class GlobalMarketDataSource:
    """
    全球市场数据源管理器
    统一接口获取全球股票数据
    """
    
    def __init__(self):
        self.config = global_config
        
        # 数据缓存
        self.cache = {}
        self.cache_ttl = 60  # 秒
        
        # 市场时区映射
        self.market_timezones = {
            "US": "America/New_York",
            "CN": "Asia/Shanghai", 
            "HK": "Asia/Hong_Kong",
            "JP": "Asia/Tokyo",
            "EU": "Europe/London"
        }
    
    def get_all_stocks(self) -> Dict[str, List[str]]:
        """获取所有关注的股票"""
        return {
            "US": self.config.US_STOCKS,
            "CN": self.config.CN_STOCKS,
            "HK": self.config.HK_STOCKS,
            "JP": self.config.JP_STOCKS,
            "EU": self.config.EU_STOCKS
        }
    
    def get_realtime_quote(self, symbol: str, market: str = "US") -> Dict:
        """获取实时行情"""
        if market == "US" or market == "HK":
            return self._get_tiger_quote(symbol)
        elif market == "CN":
            return self._get_sina_quote(symbol)
        else:
            return self._get_yahoo_quote(symbol)
    
    def _get_tiger_quote(self, symbol: str) -> Dict:
        """老虎证券行情"""
        try:
            from backend.data_engine.tiger_client import TigerClient
            client = TigerClient()
            return client.get_realtime_quote(symbol)
        except Exception as e:
            return {"error": str(e)}
    
    def _get_sina_quote(self, symbol: str) -> Dict:
        """新浪财经行情 (A股)"""
        try:
            url = f"http://hq.sinajs.cn/list={symbol}"
            headers = {"Referer": "http://finance.sina.com.cn"}
            resp = requests.get(url, headers=headers, timeout=5)
            
            if resp.status_code == 200:
                content = resp.content.decode('gbk')
                data = content.split('"')[1].split(',')
                
                return {
                    "symbol": symbol,
                    "name": data[0] if len(data) > 0 else symbol,
                    "open": float(data[1]) if len(data) > 1 else 0,
                    "high": float(data[4]) if len(data) > 4 else 0,
                    "low": float(data[5]) if len(data) > 5 else 0,
                    "price": float(data[3]) if len(data) > 3 else 0,
                    "volume": int(data[8]) if len(data) > 8 else 0,
                    "pctChg": 0,  # 需要计算
                    "last": float(data[3]) if len(data) > 3 else 0
                }
        except Exception as e:
            return {"error": str(e)}
        return {"error": "Unknown error"}
    
    def _get_yahoo_quote(self, symbol: str) -> Dict:
        """Yahoo Finance行情"""
        try:
            import yfinance as yf
            
            # 转换symbol格式
            if ".T" in symbol:  # 日本
                ticker = symbol
            elif "." not in symbol and symbol.isupper():  # 美国
                ticker = symbol
            else:
                ticker = symbol
            
            stock = yf.Ticker(ticker)
            info = stock.info
            
            return {
                "symbol": symbol,
                "name": info.get("shortName", symbol),
                "price": info.get("currentPrice", 0),
                "open": info.get("open", 0),
                "high": info.get("dayHigh", 0),
                "low": info.get("dayLow", 0),
                "volume": info.get("volume", 0),
                "pctChg": info.get("regularMarketChangePercent", 0),
                "marketCap": info.get("marketCap", 0),
                "last": info.get("currentPrice", 0)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_historical_data(
        self, 
        symbol: str, 
        market: str = "US",
        days: int = 365
    ) -> pd.DataFrame:
        """获取历史数据"""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        if market == "CN":
            return self._get_cn_history(symbol, start_date, end_date)
        else:
            return self._get_yahoo_history(symbol, start_date, end_date)
    
    def _get_cn_history(self, symbol: str, start, end) -> pd.DataFrame:
        """获取A股历史数据"""
        try:
            import baostock as bs
            
            bs.login()
            
            # 转换symbol格式
            if symbol.startswith("6"):
                bs_code = f"sh.{symbol}"
            else:
                bs_code = f"sz.{symbol}"
            
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=start.strftime("%Y-%m-%d"),
                end_date=end.strftime("%Y-%m-%d"),
                frequency="d"
            )
            
            data_list = []
            while rs.error_code == '0' and rs.next():
                data_list.append(rs.get_row_data())
            
            bs.logout()
            
            if data_list:
                df = pd.DataFrame(data_list, columns=[
                    "date", "open", "high", "low", "close", "volume", "amount"
                ])
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df
            
        except Exception as e:
            print(f"获取A股数据失败: {e}")
        
        return pd.DataFrame()
    
    def _get_yahoo_history(self, symbol: str, start, end) -> pd.DataFrame:
        """获取Yahoo历史数据"""
        try:
            import yfinance as yf
            stock = yf.Ticker(symbol)
            df = stock.history(start=start, end=end)
            return df
        except Exception as e:
            print(f"获取历史数据失败: {e}")
            return pd.DataFrame()
    
    def get_market_summary(self) -> Dict:
        """获取市场概览"""
        summary = {}
        
        for market, stocks in self.get_all_stocks().items():
            market_data = []
            for stock in stocks[:5]:  # 每市场取5只
                quote = self.get_realtime_quote(stock, market)
                if "error" not in quote:
                    market_data.append({
                        "symbol": stock,
                        "price": quote.get("price", quote.get("last", 0)),
                        "change": quote.get("pctChg", 0)
                    })
            
            if market_data:
                summary[market] = {
                    "stocks": market_data,
                    "avg_change": np.mean([s["change"] for s in market_data])
                }
        
        return summary
    
    def get_correlation_matrix(self, stocks: List[str], market: str = "US") -> np.ndarray:
        """计算股票相关性矩阵"""
        prices = []
        valid_stocks = []
        
        for stock in stocks:
            df = self.get_historical_data(stock, market, days=120)
            if len(df) > 60:
                prices.append(df["close"].pct_change().dropna())
                valid_stocks.append(stock)
        
        if len(prices) > 1:
            price_df = pd.concat(prices, axis=1)
            price_df.columns = valid_stocks
            return price_df.corr().values
        
        return np.array([])


class FeatureEngineering:
    """特征工程"""
    
    @staticmethod
    def compute_features(df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标和特征"""
        result = df.copy()
        
        # 价格变化
        result["returns_1d"] = result["close"].pct_change(1)
        result["returns_5d"] = result["close"].pct_change(5)
        result["returns_20d"] = result["close"].pct_change(20)
        
        # 波动率
        result["volatility_20d"] = result["returns_1d"].rolling(20).std()
        
        # 移动平均
        result["ma_5"] = result["close"].rolling(5).mean()
        result["ma_20"] = result["close"].rolling(20).mean()
        result["ma_60"] = result["close"].rolling(60).mean()
        
        # RSI
        delta = result["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        result["rsi_14"] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = result["close"].ewm(span=12, adjust=False).mean()
        exp2 = result["close"].ewm(span=26, adjust=False).mean()
        result["macd"] = exp1 - exp2
        result["macd_signal"] = result["macd"].ewm(span=9, adjust=False).mean()
        
        # 布林带
        result["bb_mid"] = result["close"].rolling(20).mean()
        bb_std = result["close"].rolling(20).std()
        result["bb_upper"] = result["bb_mid"] + 2 * bb_std
        result["bb_lower"] = result["bb_mid"] - 2 * bb_std
        result["bb_position"] = (result["close"] - result["bb_lower"]) / (
            result["bb_upper"] - result["bb_lower"] + 1e-8
        )
        
        # 成交量特征
        result["volume_ratio"] = result["volume"] / result["volume"].rolling(20).mean()
        
        # 动量
        result["momentum"] = result["close"] / result["close"].shift(20) - 1
        
        return result.dropna()
    
    @staticmethod
    def prepare_model_input(df: pd.DataFrame) -> np.ndarray:
        """准备模型输入"""
        features = [
            "returns_1d", "returns_5d", "returns_20d",
            "volatility_20d", "rsi_14", "macd", "macd_signal",
            "bb_position", "volume_ratio", "momentum"
        ]
        
        feature_df = df[features].values
        return (feature_df - feature_df.mean(axis=0)) / (feature_df.std(axis=0) + 1e-8)


# 创建全局实例
market_data_source = GlobalMarketDataSource()


if __name__ == "__main__":
    # 测试
    source = GlobalMarketDataSource()
    
    print("=== 全球市场概览 ===")
    summary = source.get_market_summary()
    
    for market, data in summary.items():
        print(f"\n{market} 市场:")
        print(f"  平均涨跌: {data['avg_change']:.2f}%")
        for stock in data["stocks"][:3]:
            print(f"    {stock['symbol']}: ${stock['price']:.2f} ({stock['change']:+.2f}%)")
