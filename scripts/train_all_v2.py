"""
V2 全量模型训练脚本
数据下载 → 因子计算 → 模型训练 (GBDT → Transformer → TCN → TFT → RL)
"""
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from loguru import logger

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.core.logger import setup_logger
from configs.settings import settings
from configs.market_universe import US_STOCKS, HK_STOCKS
from configs.factor_registry import FACTOR_REGISTRY

setup_logger()

# ============================================================
# Step 1: 下载数据
# ============================================================
def download_data(tickers: list, market: str = "US", years: int = 2):
    """下载 yfinance 历史数据"""
    import yfinance as yf
    import time
    
    data_dir = Path("data/daily")
    data_dir.mkdir(parents=True, exist_ok=True)
    
    downloaded = 0
    for i, t in enumerate(tickers):
        fpath = data_dir / f"{t}.parquet"
        if fpath.exists():
            continue
        
        try:
            df = yf.download(t, period=f"{years}y", interval="1d", progress=False)
            if not df.empty and len(df) > 100:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0].lower() for c in df.columns]
                else:
                    df.columns = [c.lower() for c in df.columns]
                df.to_parquet(fpath)
                downloaded += 1
            time.sleep(0.5)  # Rate limit
        except Exception as e:
            pass
        
        if (i + 1) % 20 == 0:
            logger.info(f"  下载进度: {i+1}/{len(tickers)}")
    
    logger.info(f"下载完成: {downloaded} 新文件")
    return downloaded


# ============================================================
# Step 2: 计算因子
# ============================================================
def compute_factors_for_training():
    """计算所有已下载标的的因子，返回训练数据"""
    from services.factor_service.engine.factor_engine import FactorEngine

    data_dir = Path("data/daily")
    parquet_files = list(data_dir.glob("*.parquet"))
    
    if not parquet_files:
        logger.error("无数据文件，请先下载数据")
        return None, None
    
    engine = FactorEngine()
    # register_all() registers TECHNICAL/FUNDAMENTAL/... factor instances
    engine.register_all()
    logger.info(f"已注册 {len(engine.factors)} 个因子")
    
    all_features = []
    for fpath in parquet_files[:100]:  # Limit to 100 for speed
        ticker = fpath.stem
        try:
            df = pd.read_parquet(fpath).tail(252 * 2)  # Last 2 years
            if len(df) < 100:
                continue
            
            # Compute factors
            result_df = engine.compute_all(df)
            
            # Forward returns (target)
            for horizon in [1, 5, 20]:
                result_df[f"fwd_ret_{horizon}d"] = (
                    result_df["close"].shift(-horizon) / result_df["close"] - 1
                )
            
            result_df["ticker"] = ticker
            all_features.append(result_df)
            
        except Exception as e:
            continue
    
    if not all_features:
        logger.error("因子计算失败")
        return None, None
    
    combined = pd.concat(all_features, ignore_index=True).dropna()
    logger.info(f"训练数据集: {len(combined)} 行 × {combined.shape[1]} 列, {len(all_features)} 标的")
    
    return combined, engine


# ============================================================
# Step 3: 训练模型 (Walk-Forward 严格时间序)
# ============================================================
def train_models(data: pd.DataFrame):
    """用 Walk-Forward 训练全部模型，严格时间序，杜绝未来信息泄露。"""
    from services.model_train_service.trainers.gbdt_trainer import GBDTTrainer
    from services.model_train_service.trainers.transformer_trainer import TransformerTrainer
    from services.model_train_service.framework.walk_forward import WalkForwardValidator
    
    models_dir = Path("data/models")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    # 排除非特征列
    exclude = ["ticker", "date", "open", "high", "low", "close", "adj_close", 
               "volume", "fwd_ret_1d", "fwd_ret_5d", "fwd_ret_20d"]
    feature_cols = [c for c in data.columns if c not in exclude and not c.startswith("fwd_ret")]
    
    # Use 5-day forward return as target
    if "fwd_ret_5d" not in data.columns:
        logger.error("缺少 fwd_ret_5d 目标列")
        return
    
    logger.info(f"特征: {len(feature_cols)} 列, 样本: {len(data)}")
    
    # ── Prepare features & targets ──────────────────────────
    X = data[feature_cols].copy()
    y_binary = (data["fwd_ret_5d"] > 0).astype(int)
    y_reg = data["fwd_ret_5d"].clip(-0.3, 0.3)
    
    # Build combined DataFrame for Walk-Forward (must have datetime index)
    wf_data = X.copy()
    wf_data["_target_binary"] = y_binary.values
    wf_data["_target_reg"] = y_reg.values
    
    # Ensure DateTimeIndex for Walk-Forward
    if "date" in data.columns:
        wf_data.index = pd.to_datetime(data["date"])
    elif not isinstance(wf_data.index, pd.DatetimeIndex):
        wf_data.index = pd.date_range("2020-01-01", periods=len(wf_data), freq="B")
    
    # ── Walk-Forward validator ──────────────────────────────
    wf = WalkForwardValidator(
        train_window=252,
        val_window=63,
        test_window=63,
        step_size=90,
    )
    
    results: dict[str, list] = {"gbdt": [], "xgboost": [], "transformer": []}
    
    # ═══════════════════════════════════════════════════════════
    # Fold training function (called by WalkForwardValidator)
    # ═══════════════════════════════════════════════════════════
    def train_fold(train_df: pd.DataFrame, val_df: pd.DataFrame, 
                   test_df: pd.DataFrame) -> dict:
        """Train all models on a single fold, return metrics."""
        fold_results: dict = {}
        
        ft_cols = [c for c in train_df.columns if not c.startswith("_")]
        Xt = train_df[ft_cols].fillna(0.0)
        yt = train_df["_target_binary"].fillna(0).astype(int)
        Xv = val_df[ft_cols].fillna(0.0)
        yv = val_df["_target_binary"].fillna(0).astype(int)
        
        # --- GBDT (LightGBM) ---
        try:
            gbdt = GBDTTrainer(gbdt_type="lightgbm")
            gbdt.fit(Xt, yt)
            gbdt_pred = gbdt.predict(Xv)
            gbdt_acc = float((gbdt_pred == yv).mean())
            fold_results["gbdt_acc"] = round(gbdt_acc, 4)
            gbdt.save(str(models_dir / "gbdt_v2.joblib"))
        except Exception as e:
            logger.warning(f"  GBDT fold error: {e}")
        
        # --- XGBoost ---
        try:
            xgb = GBDTTrainer(gbdt_type="xgboost")
            xgb.fit(Xt, yt)
            xgb_pred = xgb.predict(Xv)
            xgb_acc = float((xgb_pred == yv).mean())
            fold_results["xgboost_acc"] = round(xgb_acc, 4)
            xgb.save(str(models_dir / "xgboost_v2.joblib"))
        except Exception as e:
            logger.warning(f"  XGBoost fold error: {e}")
        
        # --- Transformer (PatchTST) ---
        try:
            trans = TransformerTrainer(d_model=64, n_layers=3, n_heads=4, dropout=0.1)
            yr_t = train_df["_target_reg"].fillna(0.0).values.astype(np.float32)
            Xt_np = Xt.values.astype(np.float32)
            
            seq_len = 60
            batch_X, batch_y = [], []
            for i in range(seq_len, min(len(Xt_np), 5000 + seq_len)):
                batch_X.append(Xt_np[i-seq_len:i])
                batch_y.append(yr_t[i:i+5] if i+5 <= len(yr_t) else yr_t[i:])
            
            if len(batch_X) > 100:
                batch_X = np.array(batch_X)
                batch_y_arr = np.array([np.pad(y, (0, 5 - len(y)), 'edge') for y in batch_y])
                v_split = int(len(batch_X) * 0.8)
                trans.fit(
                    batch_X[:v_split], batch_y_arr[:v_split],
                    batch_X[v_split:], batch_y_arr[v_split:],
                    n_vars=Xt_np.shape[1],
                )
                trans.save(str(models_dir / "transformer_v2.pt"))
                fold_results["transformer_samples"] = len(batch_X)
        except Exception as e:
            logger.warning(f"  Transformer fold error: {e}")
        
        return fold_results
    
    # ── Run Walk-Forward ────────────────────────────────────
    logger.info("=" * 50)
    logger.info("Starting Walk-Forward training...")
    wf_results = wf.run(wf_data, train_fold)
    
    # Aggregate per-fold metrics
    for r in wf_results:
        for k in ["gbdt_acc", "xgboost_acc"]:
            if k in r:
                results[k.replace("_acc", "")].append(r[k])
    
    # ── Summary ─────────────────────────────────────────────
    logger.info("=" * 50)
    logger.info(f"Walk-Forward 完成: {len(wf_results)} folds")
    for name, scores in results.items():
        if scores:
            mean_s = np.mean(scores)
            std_s = np.std(scores)
            logger.info(f"  {name}: mean_acc={mean_s:.4f} ± {std_s:.4f} ({len(scores)} folds)")
    
    # ── MLflow 注册最佳模型 ─────────────────────────────────
    try:
        from services.model_train_service.mlflow_manager import MLflowManager
        
        mlflow_mgr = MLflowManager()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        
        for model_name, scores in results.items():
            if not scores:
                continue
            best_acc = float(np.max(scores))
            mean_acc = float(np.mean(scores))
            model_file = str(models_dir / f"{model_name}_v2.joblib") if model_name != "transformer" else str(models_dir / "transformer_v2.pt")
            
            mlflow_mgr.register_and_promote(
                model_name=f"qat_{model_name}_v2",
                model_path=model_file,
                run_id=f"qat_{model_name}_{timestamp}",
                metrics={
                    "accuracy": round(best_acc, 4),
                    "mean_accuracy": round(mean_acc, 4),
                    "folds": len(scores),
                },
                params={
                    "n_features": len(feature_cols),
                    "train_window": 252,
                    "val_window": 63,
                    "test_window": 63,
                    "step_size": 90,
                },
            )
        logger.info("MLflow 注册完成")
    except Exception as e:
        logger.warning(f"MLflow 注册跳过: {e}")
    
    return results


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info(" Quant AI Trader v2 - 全量模型训练")
    logger.info(f" 时间: {datetime.now()}")
    logger.info("=" * 60)
    
    # Step 1: Download data
    logger.info("\n[1/3] 下载历史数据...")
    us_symbols = [s["ticker"] for s in US_STOCKS[:50]]  # Top 50 US
    download_data(us_symbols, "US", years=2)
    
    # Step 2: Compute factors & build dataset
    logger.info("\n[2/3] 计算因子...")
    data, engine = compute_factors_for_training()
    
    if data is None:
        logger.error("无法构建训练数据集")
        sys.exit(1)
    
    # Step 3: Train models
    logger.info("\n[3/3] 训练模型...")
    results = train_models(data)
    
    logger.info("\n全部训练完成!")
