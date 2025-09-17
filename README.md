# 🌐 NJUPT 校园网助手

> 一个基于 Python + Tkinter 编写的南京邮电大学校园网登录小工具，解决校园网登录繁琐的问题。  
> 打包为 `exe` 文件后，双击即可使用，无需每次打开浏览器手动输入账号密码。

---

## ✨ 功能特性

- ✅ 支持 **校园网 / 中国移动 / 中国电信** 登录
- ✅ 支持 **自动登录**（保存账号密码，下次自动一键登录）
- ✅ 支持 **开机自启**（自动启动并完成登录）
- ✅ 支持 **一键登出**
- ✅ 配置文件本地保存（`config.bin`），简单安全
- ✅ 打包为 **Windows 可执行文件**，无需额外安装 Python 环境

---

## 📸 软件截图

### 登录界面

<img src="https://github.com/1EM0NS/NJUPT_NET/blob/main/login.png" width="250" height="500">

### 登陆成功界面

<img src="https://github.com/1EM0NS/NJUPT_NET/blob/main/success.png" width="250" height="500">



---

## 🚀 使用方法

1. 前往 [Release 页面](https://github.com/1EM0NS/NJUPT_NET/releases) 下载最新的 `NJUPT_NET.exe`
2. 双击运行程序，输入账号和密码
3. 选择运营商（默认校园网）
4. 可选：
   - 勾选 **自动登录** → 下次自动完成登录
   - 点击 **开机自启** → 开机后自动运行程序并登录
5. 点击 `保存并登录` 即可

---

## ⚙️ 技术细节

- 界面使用 **Tkinter** 自定义标题栏 & 样式
- 网络请求使用 `requests`，直连校园网认证网关 IP `10.10.244.11`
- 用户配置信息保存于本地 `config.bin` 文件
- 使用 `winreg` 操作注册表实现开机自启
- 支持打包为单个 `exe` 文件（推荐使用 [PyInstaller](https://pyinstaller.org/)）

---

## 📂 项目结构

```bash
NJUPT_NET/
├─ njupt.png        # 程序图标
├─ web2.2.py          # 主程序源码
├─ config.bin       # 本地保存的用户配置（运行后生成）
└─ njupt.ico.exe   #程序图标
```

---

## 🔧 打包方法

本项目推荐使用 **PyInstaller** 打包成单个可执行文件。  

### 安装依赖
```bash
pip install pyinstaller
```

### 打包命令
在项目根目录下执行：
```bash
pyinstaller --name=NJUPT_Net --onefile -w main.py -i njupt.ico --add-data njupt.png:./
```

参数说明：
- `-F` → 打包为单文件
- `-w` → 去掉命令行窗口（GUI 程序推荐加）
- `-i njupt.png` → 指定程序图标（可选）
- `main.py` → 主程序入口

打包完成后，生成的 `exe` 文件会在 `dist/` 目录下。

---

## 🔒 注意事项

- 本工具仅供南京邮电大学校园网用户使用  
- 账号和密码仅保存在本地，不会上传网络  
- 如遇到登录失败，请检查账号/密码/网络环境是否正确  
- 登录接口依赖校园网认证网关，若校方更新认证系统，可能需要更新程序  

---

## 📚 项目地址

GitHub: [NJUPT_NET](https://github.com/1EM0NS/NJUPT_NET)

---


## 📜 License

MIT License  
你可以自由使用、修改和分发本项目，但请保留原作者信息。
