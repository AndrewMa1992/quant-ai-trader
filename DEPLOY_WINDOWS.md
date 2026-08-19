# Windows Server / Lightsail 部署指南（原生 Paper 模式）

适用：Amazon Lightsail **Windows Server 2022**（例如 `Windows_Server_2022-1`，公网 IP `3.106.139.233`）。

> Lightsail Windows 通常**没有嵌套虚拟化**，Docker Linux 容器很难跑。  
> 本指南用 **Python + Node 原生进程**，不依赖 Docker。

---

## 0. 用 RDP 登录（不是 SSH）

1. 打开 Lightsail 控制台 → Instances → `Windows_Server_2022-1`
2. 点击 **Connect using RDP**（浏览器），或本机 `mstsc` 连 `3.106.139.233:3389`
3. 用户名：`Administrator`  
   密码：Connect 页 **Default password** 获取

### Lightsail Networking 放行端口

Networking → IPv4 Firewall 添加入站：

| 端口 | 用途 |
|------|------|
| 3389 | RDP |
| 8001 | API Gateway |
| 5180 | 前端 |

---

## 1. 安装依赖（首次）

在 RDP 桌面打开 **PowerShell（管理员）**：

```powershell
# Git
winget install --id Git.Git -e --accept-source-agreements --accept-package-agreements

# Python 3.12
winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements

# Node.js 20 LTS（前端）
winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
```

关闭并重新打开 PowerShell，确认：

```powershell
python --version
git --version
node --version
npm --version
```

---

## 2. 同步代码（唯一旁支）

新开的 PowerShell 经常找不到刚装的 `git`（PATH 未刷新）。先执行：

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
cd C:\quant-ai-trader
```

若仍提示 `git` 找不到，用完整路径：

```powershell
& "C:\Program Files\Git\cmd\git.exe" fetch origin
& "C:\Program Files\Git\cmd\git.exe" checkout cursor/quant-upgrade-a75f
& "C:\Program Files\Git\cmd\git.exe" reset --hard origin/cursor/quant-upgrade-a75f
```

或（拉到 Version 4 之后）用仓库自带脚本：

```powershell
.\scripts\windows_sync.ps1
```

确认脚本已是新版（应有 `DeployScriptVersion: 4`）：

```powershell
Get-Content .\scripts\windows_deploy.ps1 -TotalCount 3
```

若仍是 Version 3 / 出现 `string is missing the terminator`，说明还没同步成功，不要直接部署。

### 页面 502 Bad Gateway

前端 `:5180` 会把 `/api` 反代到 `127.0.0.1:8001`。出现 502 几乎总是 **网关没起来**。在服务器上检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8001/health -UseBasicParsing
Get-Content C:\quant-ai-trader\logs\api-gateway.err.log -Tail 50
```

私有仓库用 PAT 或配置 GitHub SSH key。

以后更新：

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
cd C:\quant-ai-trader
.\scripts\windows_sync.ps1
.\scripts\windows_stop.ps1
.\scripts\windows_deploy.ps1 -OpenFirewall
```

---

## 3. 一键启动

```powershell
cd C:\quant-ai-trader
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\windows_deploy.ps1 -OpenFirewall
```

参数说明：

| 参数 | 作用 |
|------|------|
| `-OpenFirewall` | 放行 Windows 防火墙 8001/5180 等（需管理员） |
| `-SkipInstall` | 跳过 pip/npm 安装（二次启动） |
| `-SkipFrontend` | 只起后端 |

---

## 4. 访问

本机 RDP 内：

- API：http://127.0.0.1:8001/health  
- 前端：http://127.0.0.1:5180  

外网浏览器：

- http://3.106.139.233:5180  
- http://3.106.139.233:8001/health  

默认 **paper / 模拟盘**，不会实盘下单。

---

## 5. 停止 / 看日志

```powershell
.\scripts\windows_stop.ps1
Get-Content C:\quant-ai-trader\logs\api-gateway.err.log -Tail 80
```

PID 文件：`cache\windows_pids\`

---

## 6. 自动运行 + 自动部署（推荐）

推荐用 **Windows 计划任务**（不依赖 GitHub Runner 服务，更稳）：

1. **开机自动启动** paper 服务
2. **每 10 分钟**检查 GitHub：有新提交或服务挂了 → 自动 pull + 重启

### 6.1 一次性安装（管理员 PowerShell）

```powershell
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
cd C:\quant-ai-trader
& "C:\Program Files\Git\cmd\git.exe" fetch origin
& "C:\Program Files\Git\cmd\git.exe" reset --hard origin/cursor/quant-upgrade-a75f

Set-ExecutionPolicy -Scope Process Bypass -Force
# 立刻部署一次，并注册开机 + 定时自动部署
.\scripts\windows_install_autostart.ps1 -Branch cursor/quant-upgrade-a75f -RunNow
```

合并进 `main` 后，把跟踪分支改成 main：

```powershell
.\scripts\windows_install_autostart.ps1 -Branch main -RunNow
```

查看任务：`taskschd.msc` → `QAT-Paper-Boot` / `QAT-Paper-AutoCD`  
日志：`C:\quant-ai-trader\logs\cd-deploy.log`

### 6.2 日常开发

1. 改代码 → PR → CI
2. 合并到跟踪分支（现在是 `cursor/quant-upgrade-a75f`，稳定后用 `main`）
3. 最多约 10 分钟内服务器自动拉取并重启
4. 验证：http://3.106.139.233:8001/health 与 http://3.106.139.233:5180

### 6.3 可选：GitHub Actions Runner

计划任务已足够实现自动部署自动运行。若仍要用 Actions：

1. https://github.com/AndrewMa1992/quant-ai-trader/settings/actions/runners/new 复制 token
2. `.\scripts\windows_install_runner.ps1 -Token "..."`（需 `--runasservice` 才有 svc.cmd）
3. 或 `cd C:\actions-runner` 后 `cmd /c "run.cmd"` 保持在线

---

## 故障排查

| 现象 | 处理 |
|------|------|
| `python` 找不到 | 重开终端；或用 `py -3.12` |
| 外网打不开 5180 | Lightsail Firewall + `-OpenFirewall` |
| 前端空白 | `cd frontend; npm install; npm run build` |
| Gateway 503 | 等 30s；看 `logs\*.err.log` |
| Redis 报错 | 可忽略（Windows 默认可不装 Redis） |
| pip 很慢 | 换清华源：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...` |

---

## 规格建议

Lightsail Windows 建议 **≥ 4 GB 内存**；首次 `pip`/`npm` 会占较多磁盘。
