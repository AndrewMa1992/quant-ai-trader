# 当前项目状态 & 待修复清单

**检查时间**: 2026-06-20 19:00 GMT+8
**GPU**: NVIDIA RTX 3060 Laptop (6.4GB VRAM, 30 SMs, CC 8.6, CUDA 12.4)

---

## 运行状态

| 服务 | 端口 | 状态 | 备注 |
|------|------|------|------|
| API Gateway | 8001 | ✅ degraded | 模型未训练，data-service symbols 404 导致管线空转 |
| Data Service | 8011 | ✅ healthy | /api/v2/data/universe 返回 264 股票 |
| Factor Service | 8012 | ? | 未检查 |
| Train Service | 8013 | ✅ cuda | DEVICE=cuda (通过 .env QAT_TRAIN_DEVICE) |
| Infer Service | 8014 | ? | 未检查 |
| Risk Service | 8015 | ? | 未检查 |
| Execution Service | 8016 | ? | 未检查 |
| Frontend | 5180 | ? | 未检查 |
| Pipeline | - | ⚠️ 空转 | data-service symbols 404 → 活跃股票池为空 |

---

## 已发现的 Bug/问题

### P0 — 阻塞运行
1. **Pipeline data-service 符号端点 404**
   - 管线调用 `/api/v2/data/symbols` 但实际端点可能是 `/api/v2/data/universe` 或 `/api/v2/data/stored-tickers`
   - 导致管线所有 cycle 空转，无法执行任何交易
   - 文件: `trading_pipeline.py` — `_get_active_universe()` 方法

2. **模型 19 天未更新**
   - transformer_latest.pt: 2025-06-01 (12.8MB)
   - ppo_trader.zip: 2025-06-01 (3.3MB)
   - API /health: "degraded" 状态

### P1 — 影响核心功能
3. **训练参数"快速验证"模式**
   - Transformer: d_model=256, layers=6, heads=8 (偏小)
   - RL: 30K timesteps (偏少)
   - Walk-forward: 仅 3 folds
   - 未利用 GPU 混合精度 (FP16)

4. **configs/ 与 backend/config.py 双配置**
   - backend/config.py 标记为 "DEPRECATED"
   - configs/ 是新的配置体系

---

## GPU 利用率分析

| 参数 | 当前值 | RTX 3060 可支持 | 提升空间 |
|------|--------|----------------|----------|
| Transformer d_model | 256 | 512-768 | 2-3x |
| Transformer layers | 6 | 8-12 | 1.3-2x |
| Transformer heads | 8 | 8-16 | 1-2x |
| Batch size | 128 | 256-512 | 2-4x |
| RL timesteps | 30K | 200K-500K | 6-16x |
| Mixed precision | ❌ | FP16 (Amp) | ~2x 速度 |
| Training epochs | 30 | 80-120 | 2-4x |
| Walk-forward folds | 3 | 5-8 | 可靠性↑ |

---

## 下一步计划

1. ✅ 等待 PM 差距分析
2. ⬜ 架构师设计调参方案 + 系统改进
3. ⬜ 工程师实施：
   - 修复 pipeline 404
   - 训练参数升级到 GPU 全量配置
   - 执行完整训练（Transformer + RL + Ensemble）
4. ⬜ QA 验证
