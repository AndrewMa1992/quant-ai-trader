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

目录已存在时不要再 `git clone`（会报 destination path already exists），直接进入仓库强制对齐远端：

```powershell
cd C:\quant-ai-trader
git fetch origin
git checkout cursor/quant-upgrade-a75f
git reset --hard origin/cursor/quant-upgrade-a75f
```

确认脚本已是新版（第一行附近应有 `DeployScriptVersion: 3`）：

```powershell
Get-Content .\scripts\windows_deploy.ps1 -TotalCount 3
```

若仍出现 `The string is missing the terminator`，说明本地还是旧 UTF-8 脚本，必须先 `reset --hard` 再跑部署。

私有仓库用 PAT 或配置 GitHub SSH key。

以后更新：

```powershell
cd C:\quant-ai-trader
git fetch origin
git reset --hard origin/cursor/quant-upgrade-a75f
.\scripts\windows_stop.ps1
.\scripts\windows_deploy.ps1
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
