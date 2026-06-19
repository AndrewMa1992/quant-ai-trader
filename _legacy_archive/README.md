# _legacy_archive — 历史遗留文件归档

> 归档日期：2026-06-19  
> 这些文件已被当前活跃代码替代或不再需要，保留作为历史参考。

---

## 归档清单

### 📁 boot_scripts_v1/ — 第一代启动脚本
> 引用已废弃路径 `G:\workbuddyspace\...`，已被 `start_all.bat` + `daemon_win.ps1` 取代

| 文件 | 原因 |
|------|------|
| `boot_startup.cmd` | 旧启动入口，路径指向 G:\ |
| `boot_launcher.ps1` | 旧启动编排，路径指向 G:\ |
| `boot_start.bat` | 旧手动启动，路径指向 G:\ |
| `boot_guard.bat` | 旧 watchdog，路径指向 G:\ |
| `install_startup.vbs` | 上古 VBS 安装器 |

### 📁 daemon_scripts_legacy/ — 旧守护/控制脚本
> 引用已废弃路径 `D:\workbuddyspace\...` 或已被 v3.0 取代

| 文件 | 原因 |
|------|------|
| `daemon_guard.ps1` | v1.0 守护，已被 `daemon_win.ps1` v3.0 取代 |
| `ctl_win.ps1` | 路径指向 D:\（已过时） |
| `install_daemon_win.ps1` | 路径指向 D:\（已过时） |

### 📁 push_scripts_legacy/ — 旧推送脚本
> 指向 main 分支或与当前 dev-20260522 工作流不一致

| 文件 | 原因 |
|------|------|
| `git_push.bat` | 旧首次配置脚本（指向 main 分支） |
| `push_to_github.py` | 强制推送 main（非当前工作分支） |
| `tmp_push.bat` | `do_push.bat` 的完全重复副本 |
| `PUSH_GUIDE.md` | 首次配置指南 |

### 📁 report_generators/ — 一次性报告生成器
> 已完成使命的独立报告脚本，非系统运行组件

| 文件 | 产出 |
|------|------|
| `generate_report.py` | REPORT.md（账户/持仓/交易摘要） |
| `generate_audit_pdf.py` | docs/system_audit_report_20260522.pdf |
| `generate_nn_report.py` | docs/nn_stock_selection_research.pdf |
| `generate_readiness_report.py` | docs/live_trading_readiness_report.pdf |

### 📁 workbuddy_sessions/ — 残留 WorkBuddy 会话
> AI 助手历史会话的工作区残留

| 目录 | 内容 |
|------|------|
| `2026-06-10-23-24-07/` | 仅含 .workbuddy/memory/2026-06-10.md |
| `2026-06-14-16-32-14/` | 完全空目录 |
| `Claw/` | 仅含 .workbuddy/memory/2026-06-10.md |

### 📁 logs_macos/ — macOS 残留日志
> macOS launchd 相关日志，Windows 环境下无用

| 文件 | 说明 |
|------|------|
| `launchd-stdout.log` | macOS launchd 标准输出 |
| `launchd-stderr.log` | macOS launchd 错误输出 |
| `launchd_stdout.log` | 同上（命名变体） |
| `launchd_stderr.log` | 同上（命名变体） |
| `health_report_20260515_224137.json` | 旧健康报告 |

### 📁 misc/ — 杂项

#### misc/cache_logs/
> HuggingFace FinBERT 模型下载日志（2026-05-22），5 个 xet 日志文件

#### misc/db_backup/
> `quant_trader.db.bak` — SQLite 数据库备份（2026-05-22，737 KB）

---

## 当前活跃的运维文件（已保留在项目根目录）

| 文件 | 用途 |
|------|------|
| `start_all.bat` | 一键全栈启动 |
| `start_daemon.bat` | 守护进程启动包装器 |
| `daemon_win.ps1` | **主守护进程 v3.0**（健康检查 + git pull/push + 自动重启） |
| `daemon_forever.bat` | 备用守护进程 v2.3 |
| `install_boot.ps1` | 注册 Windows 计划任务 |
| `do_push.bat` / `git_push.sh` | 主动 Git 推送 |
| `ctl.sh` / `daemon.sh` | macOS 服务控制 |
| `monitor.bat` | 监控面板 |
