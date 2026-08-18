# 当前项目状态 & 待修复清单（更新于 Cloud Agent 修复后）

**检查时间**: 2026-08-18  
**分支**: `cursor/fix-bugs-optimize-a75f`

---

## 本次已修复

### P0 — 交易安全
1. ✅ 熔断平仓前同步持仓到 RiskManager，并 `apply_liquidation` 回写 PortfolioManager
2. ✅ RiskGate Barra/VaR/CVaR 端点与参数对齐；CVaR 改用 `/cvar`
3. ✅ 实盘模式下风控检查失败改为 **fail-closed**
4. ✅ 执行侧 CircuitBreaker 在管线周期内调用 `set_nav`
5. ✅ 极端回撤（≥90%）仅在未完成 Tiger 同步时跳过；同步后仍触发熔断
6. ✅ 默认 `EXECUTION_MODE=paper`（需显式 `QAT_EXECUTION_MODE=live`）

### P1 — 管线 / 前端
7. ✅ 从 `MARKET_ROTATION` 移除空转的 `CN`
8. ✅ 移除无效 `CyclePerformance` / `SessionLocal` 导入（保留 JSONL）
9. ✅ Tiger 首次同步传 `is_tiger_sync=True`
10. ✅ 前端 API 对齐网关真实路由（risk portfolio-history、execution orders、dashboard）
11. ✅ 网关增加 `analysis → risk` 别名
12. ✅ risk-service 补齐 circuit_breaker 状态/重置/切换接口
13. ✅ 移除前端 Darwin-only Rollup 依赖
14. ✅ 股票池去重 CAT、剔除已退市 PXD
15. ✅ train_gat 自动检测 CUDA/MPS/CPU

---

## 仍待后续（非本轮阻塞）

| 项 | 说明 |
|----|------|
| 模型权重过期 / 缺失 | `data/models/` 需重新训练后加载 |
| backend/ 与 services/ 双架构 | PRD P2，需独立重构 |
| RL 单票推理启发式 | 需专用单票路径 + 更多单测 |
| 实盘 Tiger 凭证与充值策略 | 需人工确认后再切 live |

---

## 验证建议

```bash
pytest tests/test_risk_gate_and_liquidation.py tests/test_circuit_breaker_fix.py -q
```
