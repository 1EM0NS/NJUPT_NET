# 🌐 南邮校园网 v3.0.0

> 南京邮电大学校园网登录工具，WPF + WPF-UI 原生界面，支持一键登录 / 退出、开机自启和自动更新。

从 v3.0.0 起，项目由 Python + Tkinter 重写为 **C# / .NET 8 + WPF**，并以 **Setup 安装包**形式分发，
不再需要把一个 `exe` 手动复制到某个目录。

> 图标为自制图形（蓝色圆角底 + 白色/浅蓝双环），不含任何校徽、校名或校方标识。

---

## 🆕 v3.0.0 更新

- 界面重写为 **WPF + WPF-UI**（Mica 背景、圆角、原生 Windows 控件），支持 125% / 150% 高 DPI 缩放。
- 提供 **安装包**：开始菜单快捷方式、可选桌面快捷方式、卸载项，安装范围可选「仅为我安装」或「为所有用户安装」。
- 密码改用 **Windows DPAPI（当前用户）** 加密保存在 `%APPDATA%\NJUPT_NET\config.json`，不再明文落盘。
- 首次运行会自动迁移旧版程序目录下的 `config.bin`。
- 网络请求强制 **直连认证网关**（`UseProxy = false`），并内置门户 IP 兜底，开启代理或 FlClash TUN 时也能登录。
- 自动检查 GitHub Release（API 限流时自动降级），有安装包时校验大小与 SHA256 后静默升级，没有安装包时引导到发布页。
- 后台操作超过 120 秒自动恢复，界面不会卡在「处理中」。
- 诊断日志位于 `%APPDATA%\NJUPT_NET\njupt_net.log`（不记录密码）。

---

## ✨ 功能特性

- ✅ 支持 **校园网 / 中国移动（@cmcc）/ 中国电信（@njxy）/ 中国联通（@lt）**
- ✅ 一键登录、一键退出（优先走门户「自服务」注销，失败回退网关 `logout`）
- ✅ 注销后轮询在线状态确认，不会「假成功」
- ✅ 启动时自动登录（可选）
- ✅ 开机自启（写入 `HKCU\...\CurrentVersion\Run`）
- ✅ 自动检查更新，下载校验后静默安装

---

## 🚀 使用方法

1. 前往 [Release 页面](https://github.com/1EM0NS/NJUPT_NET/releases) 下载最新的 `NJUPT_Net_Setup_v3.0.0.exe`
2. 双击安装，选择「仅为我安装」或「为所有用户安装」
3. 首次运行需要安装 **.NET 8 Desktop Runtime**（安装包会检测并给出下载入口）
4. 输入学号与密码，选择运营商，点击「立即登录」
5. 可选：
   - 打开 **启动时自动登录** → 下次启动自动完成登录
   - 点击 **开机自启** → 开机后自动运行程序

> 未签名的安装包首次运行会出现 SmartScreen 提示，点击「更多信息 → 仍要运行」即可。

---

## ⚙️ 技术细节

- 运行时：`.NET 8`（`net8.0-windows`，`win-x64`，**框架依赖**发布）
- 界面：`WPF` + [`WPF-UI`](https://github.com/lepoco/wpfui) 4.0.3
- 安装包：`Inno Setup 6`
- 认证接口：`https://p.njupt.edu.cn:804/eportal/portal/{loadConfig,login,logout,online_list,self}`（804 不可用时回退 802）
- 门户域名解析失败时回退到已知 IP `10.10.244.11`，TLS 仍按原域名握手
- 配置：`%APPDATA%\NJUPT_NET\config.json`，密码为 DPAPI 密文
- 日志：`%APPDATA%\NJUPT_NET\njupt_net.log`

---

## 📂 项目结构

```text
NJUPT_NET/
├─ NJUPT_NET.csproj         # .NET 8 WPF 工程
├─ App.xaml / App.xaml.cs
├─ MainWindow.xaml / MainWindow.xaml.cs
├─ Models/
│  ├─ AppConfig.cs
│  └─ PortalSession.cs
├─ Services/
│  ├─ PortalService.cs      # 门户协议：在线检测 / 登录 / 注销
│  ├─ ConfigService.cs      # 配置读写 + 旧版 config.bin 迁移
│  ├─ StartupService.cs     # 开机自启
│  ├─ UpdateService.cs      # GitHub Release 检查与升级
│  └─ Log.cs
├─ Resources/
│  ├─ app.ico               # 自制应用图标（16~256 多尺寸）
│  └─ app-icon-256.png      # 图标 256px 预览图
├─ tools/
│  ├─ icon-lib.ps1          # 图标绘制逻辑（大尺寸细弧线 / 小尺寸实心环）
│  ├─ make-icon.ps1         # 生成 app.ico 与 256px 预览
│  └─ icon-preview.ps1      # 把 ico 各尺寸渲染成对照图，便于检查
├─ installer/
│  ├─ NJUPT_NET.iss
│  └─ ChineseSimplified.isl
├─ legacy/                  # v2.5.0 Python + Tkinter 旧版（保留备查）
└─ publish/                 # dotnet publish 输出（构建生成，不入库）
```

### 应用图标

图标由 `tools/make-icon.ps1` 用 System.Drawing 生成，纯 PowerShell、无外部依赖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\make-icon.ps1
```

会输出 `Resources/app.ico`（16/24/32/48/64/128/256 七种尺寸）和 `Resources/app-icon-256.png`。
16/24/32 使用实心双环保证小尺寸清晰，48 以上使用带圆头的细弧线。
检查各尺寸效果：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\icon-preview.ps1
```

工程、安装包、标题栏统一引用 `Resources/app.ico`，不使用任何校方标识。
注意 `tools/*.ps1` 必须保持纯 ASCII：Windows PowerShell 5.1 会把无 BOM 文件按 ANSI 读取，
中文注释会吞掉下一行代码。

### 旧版 Python 程序

v2.5.0 及更早版本位于 `legacy/`：

- `legacy/web2.3.py`：Tkinter 主程序
- `legacy/README_v2.5.0.md`：旧版说明文档
- `legacy/NJUPT_Net.spec`：PyInstaller 打包配置

旧版仍可自行打包，但不再接收功能更新；新版本请使用 Setup 安装包。

---

## 🔧 本地构建

需要 [.NET 8 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)。

```powershell
# 还原依赖
dotnet restore .\NJUPT_NET.csproj

# 编译
dotnet build .\NJUPT_NET.csproj -c Release

# 发布（框架依赖）
dotnet publish .\NJUPT_NET.csproj -c Release -r win-x64 --self-contained false -o .\publish
```

### 生成安装包

安装 [Inno Setup 6](https://jrsoftware.org/isdl.php)，然后：

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" .\installer\NJUPT_NET.iss
```

产物：`dist\NJUPT_Net_Setup_v3.0.0.exe`

安装脚本特性：

- `PrivilegesRequired=lowest` + `PrivilegesRequiredOverridesAllowed=dialog`：安装时可选择安装范围
- `ArchitecturesAllowed=x64compatible`：仅 64 位
- 安装时检测 `.NET 8 Desktop Runtime`，缺失时给出官方下载入口
- 卸载时清理开机自启注册表项，并询问是否删除账号配置

---

## 🔒 注意事项

- 本工具仅供南京邮电大学校园网用户使用
- 账号和密码仅保存在本地，不会上传网络
- 登录接口依赖校园网认证网关，若校方更新认证系统，可能需要更新程序
- 若出现 `loadConfig 响应格式异常`，请先确认已连接校园网，再查看 `njupt_net.log`

---

## 📜 License

MIT License  
你可以自由使用、修改和分发本项目，但请保留原作者信息。

