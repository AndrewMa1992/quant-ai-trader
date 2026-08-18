# 当前项目状态（模拟账号 + 训练管线）

**更新**: 2026-08-18  
**分支**: `cursor/fix-bugs-optimize-a75f`

---

## 模拟账号模式（已锁定）

- `QAT_EXECUTION_MODE=paper`（默认）
- `QAT_TRADING_SIMULATION_MODE=true`（默认强制 paper）
- 熔断平仓 / 空头修复：仅在 **live + 非 sim** 时调用 Tiger `place_order`
- 管线 `TigerExecutor` 默认 paper

切实盘需同时：
```bash
QAT_TRADING_SIMULATION_MODE=false
QAT_EXECUTION_MODE=live
```

---

## 模型训练管线

入口：
```bash
python scripts/run_paper_train.py --quick --models gbdt
python scripts/run_paper_train.py --models gbdt,transformer,tcn,tft,rl
python scripts/train_on_gpu.py   # 自动检测 CUDA，否则 CPU
```

已修复：
- 数据根目录统一为 `./data`（`data/daily/*.parquet`）
- 因子注册（instances，不再 `f_cls()`）
- RL 保存为 `.zip`；SAC 回退 PPO
- Hyperopt 支持 `device`
- TrainRequest schema 对齐 `gbdt|transformer|tcn|tft|rl`
- `train_on_gpu.py` 重写为纸面训练包装器

验证：`gbdt_v2.joblib` 已在 `--quick` 下成功产出。
