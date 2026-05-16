#!/usr/bin/env python3
"""
预训练脚本 - 首次运行前执行
下载数据、训练 AI 模型
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from loguru import logger
from backend.ai_models.trainer import ModelTrainer


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🧠 Quant AI Trader - 预训练")
    logger.info("=" * 60)

    trainer = ModelTrainer()

    # 下载数据并训练模型
    trainer.train_all(tickers=["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"])

    logger.info("\n" + "=" * 60)
    logger.info("✅ 预训练完成！")
    logger.info(f"   Transformer: {'就绪' if trainer.transformer.is_ready() else '失败'}")
    logger.info(f"   PPO Agent:   {'就绪' if trainer.rl_agent.is_ready() else '失败'}")

    summary = trainer.get_training_summary()
    logger.info("\n📊 模型文件:")
    for k, v in summary.items():
        logger.info(f"   {k}: {v}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
