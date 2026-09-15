import os
import sys
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
import requests
import time
import ast
import json
import re
import random
import base64
import ipaddress
import html as html_module
import urllib.parse
import winreg
from win32gui import *
from win32con import *

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

# ===== 南邮校园网 2026 新认证协议（eportal 804 动态流程）=====
PORTAL_URL = "https://p.njupt.edu.cn/"
PORTAL_CONFIG_URL = "https://p.njupt.edu.cn:804/eportal/portal/page/loadConfig"
PORTAL_LOGIN_URL = "https://p.njupt.edu.cn:804/eportal/portal/login"
PORTAL_LOGOUT_URL = "https://p.njupt.edu.cn:804/eportal/portal/logout"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _read_js_string(page, name, default=""):
    match = re.search(r"\b{}\s*=\s*(['\"])(.*?)\1".format(re.escape(name)), page)
    return match.group(2).strip() if match else default


def _b64(value):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _xor_key(client_ip):
    key = 0
    for ch in client_ip:
        key ^= ord(ch)
    return key


def _xor_hex(value, key):
    if value is None or value == "":
        return ""
    return "".join("{:02x}".format(ord(ch) ^ key) for ch in str(value))


def portal_login_flow(account, password):
    """执行 2026 新版动态登录流程，返回 (result, msg)。
    result=1 成功；'AC999' 表示已在线；其他为业务错误信息。"""
    session = requests.Session()
    session.verify = False
    session.trust_env = False  # 忽略系统代理，直连认证网关
    headers = {"User-Agent": USER_AGENT}

    # 1. 访问门户首页，提取客户端 IP/MAC/VLAN 与 a41.js 地址
    r = session.get(PORTAL_URL, headers=headers, timeout=10)
    page = r.text
    client_ip = _read_js_string(page, "ss5") or _read_js_string(page, "v46ip")
    try:
        if ipaddress.ip_address(client_ip).version != 4:
            raise ValueError
    except ValueError:
        raise RuntimeError("门户页面未提供有效的客户端 IP（请先连接校园网）")
    terminal = {
        "ip": client_ip,
        "ipv6": _read_js_string(page, "myv6ip"),
        "mac": re.sub(r"[:-]", "", _read_js_string(page, "ss4", "000000000000")) or "000000000000",
        "vlan": _read_js_string(page, "vlanid", "0") or "0",
    }

    # 2. 下载 a41.js，读取加密开关 page_data_encrypt
    script_url = None
    for m in re.finditer(r"<script\b[^>]*\bsrc\s*=\s*(['\"])(.*?)\1", page, re.IGNORECASE | re.DOTALL):
        src = html_module.unescape(m.group(2).strip())
        if re.search(r"(?:^|/)a41\.js(?:[?#]|$)", src, re.IGNORECASE):
            script_url = urllib.parse.urljoin(PORTAL_URL, src)
            break
    page_data_encrypt = False
    if script_url:
        js = session.get(script_url, headers={"Referer": PORTAL_URL, "User-Agent": USER_AGENT},
                         timeout=10).text
        m = re.search(r"\bpage_data_encrypt\s*=\s*(['\"])([01])\1", js)
        if m:
            page_data_encrypt = m.group(2) == "1"

    # 3. 调 loadConfig 获取动态登录配置
    callback = "dr{}".format(time.time_ns() % 1000000000)
    cfg_params = [
        ("program_index", ""), ("wlan_vlan_id", terminal["vlan"]),
        ("wlan_user_ip", _b64(terminal["ip"])), ("wlan_user_ipv6", _b64(terminal["ipv6"])),
        ("wlan_user_ssid", ""), ("wlan_user_areaid", ""), ("wlan_ac_ip", _b64("")),
        ("wlan_ap_mac", "000000000000"), ("gw_id", ""), ("page_index", ""),
        ("callback", callback), ("jsVersion", "4.5"),
        ("v", str(random.randrange(500, 10500))), ("lang", "zh"),
    ]
    r = session.get(PORTAL_CONFIG_URL, params=cfg_params,
                    headers={"Referer": PORTAL_URL, "User-Agent": USER_AGENT}, timeout=10)
    text = r.text.strip()
    m = re.fullmatch(r"{}\((.*)\);?".format(re.escape(callback)), text, re.DOTALL)
    try:
        payload = json.loads(m.group(1) if m else text)
    except json.JSONDecodeError:
        raise RuntimeError("loadConfig 响应格式异常：{}".format(text[:200]))
    if str(payload.get("code", "0")) == "0" or not isinstance(payload.get("data"), dict):
        raise RuntimeError("loadConfig 被拒绝：{}".format(text[:200]))
    config = payload["data"]

    # 4. 按动态配置构造登录参数
    account_prefix = ",0," if str(config.get("account_prefix", "0")) == "1" else ""
    no_filter = str(config.get("no_filter_accandpwd", "0"))
    portal_account = account_prefix + account
    portal_password = password
    if no_filter == "1":
        portal_account = _b64(portal_account)
        portal_password = _b64(portal_password)

    data = [
        ("login_method", str(config.get("login_method", ""))),
        ("is_base64encode", no_filter),
        ("user_account", portal_account),
        ("user_password", portal_password),
        ("wlan_user_ip", terminal["ip"]),
        ("wlan_user_ipv6", terminal["ipv6"]),
        ("wlan_user_mac", terminal["mac"]),
        ("wlan_vlan_id", terminal["vlan"]),
        ("wlan_ac_ip", ""), ("wlan_ac_name", ""),
        ("authex_enable", ""), ("jsVersion", "4.5"),
        ("terminal_type", "1"), ("lang", "zh-cn"),
        ("user_agent", USER_AGENT),
        ("enable_r3", str(config.get("enable_r3", "0"))),
        ("mac_type", "0"),
        ("rcn", str(config.get("rcn", ""))),
        ("operate", "portal_login"), ("business_type", "1"),
        ("program_index", str(config.get("program_index", ""))),
        ("page_index", str(config.get("page_index", ""))),
        ("callback", callback),
    ]
    if page_data_encrypt:
        key = _xor_key(terminal["ip"])
        params = [(name, _xor_hex(value, key)) for name, value in data]
        params.append(("encrypt", "1"))
    else:
        params = list(data)
    params.extend([("v", str(random.randrange(500, 10500))), ("lang", "zh")])

    # 5. 提交登录
    r = session.get(PORTAL_LOGIN_URL, params=params,
                    headers={"Accept": "*/*", "Referer": PORTAL_URL, "User-Agent": USER_AGENT},
                    timeout=15)
    text = r.text.strip()
    m = re.search(r"{}\((.*)\);?".format(re.escape(callback)), text, re.DOTALL)
    try:
        result = json.loads(m.group(1) if m else text)
    except json.JSONDecodeError:
        raise RuntimeError("登录响应格式异常：{}".format(text[:300]))
    return result.get("result", 0), str(result.get("msg", "未知错误"))


def portal_logout_flow():
    """新版注销：直接请求 804 logout（带上从门户页拿到的参数即可）"""
    session = requests.Session()
    session.verify = False
    session.trust_env = False
    try:
        session.get(PORTAL_LOGOUT_URL, timeout=8,
                    headers={"User-Agent": USER_AGENT, "Referer": PORTAL_URL})
    except requests.exceptions.RequestException:
        pass

auto_flag = False

# 添加窗口拖拽功能的变量
drag_start_x = 0
drag_start_y = 0

def start_drag(event):
    global drag_start_x, drag_start_y
    drag_start_x = event.x
    drag_start_y = event.y

def do_drag(event):
    x = root.winfo_x() + event.x - drag_start_x
    y = root.winfo_y() + event.y - drag_start_y
    root.geometry(f"+{x}+{y}")

def close_window():
    root.quit()

def minimize_window():
    root.iconify()

def open_url(event):
    webbrowser.open_new("https://github.com/1EM0NS/NJUPT_NET/")

def set_startup(enable):
    """设置开机自启动"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_SET_VALUE)

        if enable:
            # 获取当前程序路径
            if getattr(sys, 'frozen', False):
                # 如果是打包后的exe
                app_path = sys.executable
            else:
                # 如果是python脚本
                app_path = os.path.abspath(__file__)

            winreg.SetValueEx(key, "NJUPT_NET", 0, winreg.REG_SZ, app_path)
            messagebox.showinfo("成功", "开机自启动已启用！")
        else:
            try:
                winreg.DeleteValue(key, "NJUPT_NET")
                messagebox.showinfo("成功", "开机自启动已禁用！")
            except FileNotFoundError:
                pass  # 注册表项不存在，无需删除

        winreg.CloseKey(key)
    except Exception as e:
        messagebox.showerror("错误", f"设置开机自启动失败：{str(e)}")

def check_startup():
    """检查是否已设置开机自启动"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run",
                            0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, "NJUPT_NET")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False

def toggle_startup():
    """切换开机自启动状态"""
    current_status = check_startup()
    set_startup(not current_status)
    # 更新按钮显示状态
    update_startup_button()

def update_startup_button():
    """更新开机自启动按钮的显示状态"""
    if check_startup():
        startup_btn.config(text="✅ 开机自启", bg='#27ae60')
    else:
        startup_btn.config(text="⭕ 开机自启", bg='#95a5a6')

def get_config_path():
    """获取 config.bin 的绝对路径（程序目录），兼容 exe 和脚本"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "config.bin")

def ensure_config_exists():
    """如 config.bin 不存在则自动生成一个默认配置文件"""
    config_path = get_config_path()
    if not os.path.exists(config_path):
        default_config = ["", None, "", False]
        with open(config_path, "wb") as f:
            f.write(str(default_config).encode("utf-8"))

def load_info():
    global auto_flag
    auto_flag  = True
    config_path = get_config_path()
    ensure_config_exists()
    try:
        with open(config_path, "rb") as f:
            config = ast.literal_eval(f.read().decode("utf-8"))
            entry_id.insert(0, config[0])
            # 兼容旧版后缀：dx 自动映射回 njxy（当前电信格式）
            if config[1] == "dx":
                config[1] = "njxy"
            if config[1] == None:
                var_server.set("校园网")
            elif config[1] == "cmcc":
                var_server.set("中国移动")
            elif config[1] == "njxy":
                var_server.set("中国电信")
            elif config[1] == "lt":
                var_server.set("中国联通")
            entry_password.insert(0, config[2])
            auto_login.set(config[3])
            if config[3]:
                login(config)
    except FileNotFoundError:
        pass

def load_info_without_auto():
    config_path = get_config_path()
    ensure_config_exists()
    try:
        with open(config_path, "rb") as f:
            config = ast.literal_eval(f.read().decode("utf-8"))
            entry_id.insert(0, config[0])
            # 兼容旧版后缀：dx 自动映射回 njxy（当前电信格式）
            if config[1] == "dx":
                config[1] = "njxy"
            if config[1] == None:
                var_server.set("校园网")
            elif config[1] == "cmcc":
                var_server.set("中国移动")
            elif config[1] == "njxy":
                var_server.set("中国电信")
            elif config[1] == "lt":
                var_server.set("中国联通")
            entry_password.insert(0, config[2])
            auto_login.set(config[3])
    except FileNotFoundError:
        pass

def save_info():
    Bid = entry_id.get()
    server = var_server.get()
    password = entry_password.get()
    auto_login_status = auto_login.get()

    if server == "校园网":
        server = None
    elif server == "中国移动":
        server = "cmcc"
    elif server == "中国电信":
        server = "njxy"
    elif server == "中国联通":
        server = "lt"

    config = [Bid, server, password, auto_login_status]
    config_path = get_config_path()
    with open(config_path, "wb") as f:
        f.write(str(config).encode("utf-8"))
    time.sleep(0.1)

    login(config)

def login(config):
    """2026 新版动态登录流程"""
    # 拼接运营商后缀（当前南邮格式：@cmcc 移动 / @njxy 电信）
    if config[1] is None:
        account = config[0]
    else:
        account = "{}@{}".format(config[0], config[1])

    try:
        result, msg = portal_login_flow(account, config[2])
    except RuntimeError as e:
        messagebox.showerror("登录失败", str(e))
        return
    except requests.exceptions.RequestException as e:
        messagebox.showerror("登录失败", "网络请求失败：{}".format(e))
        return

    if result == 1:
        messagebox.showinfo("登录成功", msg)
        show_logout_interface()
    elif "AC999" in msg:
        messagebox.showinfo("提示", "您已经登录到校园网！")
        show_logout_interface()
    else:
        messagebox.showerror("登录失败", msg)

def logout():
    """新版注销流程"""
    portal_logout_flow()
    show_login_interface()

def center_window(root, width=400, height=350):
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    root.geometry(f'{width}x{height}+{x}+{y}')

def setup_styles():
    style = ttk.Style()
    style.theme_use('clam')

    # 标题栏样式
    style.configure('TitleBar.TFrame',
                   background='#2c3e50')

    style.configure('TitleBar.TLabel',
                   font=('Microsoft YaHei UI', 10, 'bold'),
                   foreground='white',
                   background='#2c3e50')

    style.configure('CloseBtn.TButton',
                   font=('Microsoft YaHei UI', 10, 'bold'),
                   background='#e74c3c',
                   foreground='white',
                   borderwidth=0,
                   focuscolor='none',
                   relief='flat')

    style.map('CloseBtn.TButton',
              background=[('active', '#c0392b')])

    style.configure('MinBtn.TButton',
                   font=('Microsoft YaHei UI', 10, 'bold'),
                   background='#34495e',
                   foreground='white',
                   borderwidth=0,
                   focuscolor='none',
                   relief='flat')

    style.map('MinBtn.TButton',
              background=[('active', '#2c3e50')])

    # 配置样式
    style.configure('Title.TLabel',
                   font=('Microsoft YaHei UI', 16, 'bold'),
                   foreground='#2c3e50',
                   background='#ecf0f1')

    style.configure('Custom.TLabel',
                   font=('Microsoft YaHei UI', 10),
                   foreground='#34495e',
                   background='#ecf0f1')

    style.configure('Custom.TEntry',
                   font=('Microsoft YaHei UI', 10),
                   fieldbackground='white',
                   borderwidth=1,
                   relief='solid')

    style.configure('Custom.TCombobox',
                   font=('Microsoft YaHei UI', 10),
                   fieldbackground='white',
                   borderwidth=1,
                   relief='solid')

    style.configure('Custom.TCheckbutton',
                   font=('Microsoft YaHei UI', 10),
                   foreground='#34495e',
                   background='#ecf0f1',
                   focuscolor='none')

    style.configure('Login.TButton',
                   font=('Microsoft YaHei UI', 11, 'bold'),
                   background='#3498db',
                   foreground='white',
                   borderwidth=0,
                   focuscolor='none')

    style.map('Login.TButton',
              background=[('active', '#2980b9'),
                         ('pressed', '#21618c')])

    style.configure('Logout.TButton',
                   font=('Microsoft YaHei UI', 11, 'bold'),
                   background='#e74c3c',
                   foreground='white',
                   borderwidth=0,
                   focuscolor='none')

    style.map('Logout.TButton',
              background=[('active', '#c0392b'),
                         ('pressed', '#922b21')])

def create_title_bar(parent):
    """创建自定义标题栏"""
    title_frame = tk.Frame(parent, bg='#2c3e50', height=35)
    title_frame.pack(fill='x', side='top')
    title_frame.pack_propagate(False)

    # 标题文字
    title_label = tk.Label(title_frame, text="🌐 NJUPT 校园网助手",
                          font=('Microsoft YaHei UI', 10, 'bold'),
                          fg='white', bg='#2c3e50')
    title_label.pack(side='left', padx=15, pady=8)

    # 窗口控制按钮容器
    controls_frame = tk.Frame(title_frame, bg='#2c3e50')
    controls_frame.pack(side='right', padx=5, pady=2)

    # 最小化按钮
    min_btn = tk.Button(controls_frame, text="-", command=minimize_window,
                       bg='#34495e', fg='white', font=('Arial', 12, 'bold'),
                       relief='flat', bd=0, width=3, height=1)
    min_btn.pack(side='left', padx=1)
    min_btn.bind("<Enter>", lambda e: min_btn.config(bg='#2c3e50'))
    min_btn.bind("<Leave>", lambda e: min_btn.config(bg='#34495e'))

    # 关闭按钮
    close_btn = tk.Button(controls_frame, text="×", command=close_window,
                         bg='#e74c3c', fg='white', font=('Arial', 12, 'bold'),
                         relief='flat', bd=0, width=3, height=1)
    close_btn.pack(side='left', padx=1)
    close_btn.bind("<Enter>", lambda e: close_btn.config(bg='#c0392b'))
    close_btn.bind("<Leave>", lambda e: close_btn.config(bg='#e74c3c'))

    # 绑定拖拽事件到标题栏
    title_frame.bind("<Button-1>", start_drag)
    title_frame.bind("<B1-Motion>", do_drag)
    title_label.bind("<Button-1>", start_drag)
    title_label.bind("<B1-Motion>", do_drag)

    return title_frame

def show_login_interface():
    for widget in root.winfo_children():
        widget.destroy()

    # 创建自定义标题栏
    title_bar = create_title_bar(root)

    # 主容器 - 添加圆角效果的容器
    main_container = tk.Frame(root, bg='#ecf0f1')
    main_container.pack(fill='both', expand=True)

    # 主内容区域
    main_frame = tk.Frame(main_container, bg='#ecf0f1')
    main_frame.pack(fill='both', expand=True, padx=15, pady=15)

    # 应用标题
    title_label = tk.Label(main_frame, text="校园网登录",
                          font=('Microsoft YaHei UI', 18, 'bold'),
                          fg='#2c3e50', bg='#ecf0f1')
    title_label.pack(pady=(10, 30))

    # 登录表单容器 - 添加阴影效果
    form_container = tk.Frame(main_frame, bg='#ecf0f1')
    form_container.pack(pady=10, padx=15, fill='x')

    # 阴影效果
    shadow_frame = tk.Frame(form_container, bg='#bdc3c7', height=2)
    shadow_frame.pack(fill='x', padx=2, pady=2)

    form_frame = tk.Frame(form_container, bg='white', relief='flat', bd=0)
    form_frame.pack(fill='x')

    # 内部填充
    inner_frame = tk.Frame(form_frame, bg='white')
    inner_frame.pack(padx=35, pady=35)

    # 学号输入
    ttk.Label(inner_frame, text="学号", style='Custom.TLabel').grid(row=0, column=0, padx=(0, 15), pady=15, sticky='e')
    global entry_id
    entry_id = ttk.Entry(inner_frame, style='Custom.TEntry', width=20)
    entry_id.grid(row=0, column=1, padx=(0, 10), pady=15, sticky='w')

    # 密码输入
    ttk.Label(inner_frame, text="🔐 密码", style='Custom.TLabel').grid(row=1, column=0, padx=(0, 15), pady=15, sticky='e')
    global entry_password
    entry_password = ttk.Entry(inner_frame, show="*", style='Custom.TEntry', width=20)
    entry_password.grid(row=1, column=1, padx=(0, 10), pady=15, sticky='w')

    # 运营商选择
    ttk.Label(inner_frame, text="📡 运营商", style='Custom.TLabel').grid(row=2, column=0, padx=(0, 15), pady=15, sticky='e')
    global var_server
    var_server = tk.StringVar()
    server_combo = ttk.Combobox(inner_frame, textvariable=var_server,
                               values=["校园网", "中国移动", "中国电信", "中国联通"],
                               style='Custom.TCombobox', width=17, state='readonly')
    server_combo.grid(row=2, column=1, padx=(0, 10), pady=15, sticky='w')

    # 自动登录和开机自启动选项容器
    options_frame = tk.Frame(inner_frame, bg='white')
    options_frame.grid(row=3, column=0, columnspan=2, pady=20)

    # 自动登录选项
    global auto_login
    auto_login = tk.BooleanVar()
    auto_check = ttk.Checkbutton(options_frame, text="🔄 自动登录", variable=auto_login, style='Custom.TCheckbutton')
    auto_check.pack(side='left', padx=(0, 20))

    # 开机自启动按钮
    global startup_btn
    startup_btn = tk.Button(options_frame, text="⭕ 开机自启", command=toggle_startup,
                           bg='#95a5a6', fg='white', font=('Microsoft YaHei UI', 9, 'bold'),
                           relief='flat', bd=0, padx=12, pady=6,
                           cursor='hand2')
    startup_btn.pack(side='left')

    # 更新开机自启动按钮状态
    update_startup_button()

    # 按钮悬停效果
    def on_startup_enter(e):
        if check_startup():
            startup_btn.config(bg='#2ecc71')
        else:
            startup_btn.config(bg='#7f8c8d')

    def on_startup_leave(e):
        if check_startup():
            startup_btn.config(bg='#27ae60')
        else:
            startup_btn.config(bg='#95a5a6')

    startup_btn.bind("<Enter>", on_startup_enter)
    startup_btn.bind("<Leave>", on_startup_leave)

    # 登录按钮容器
    btn_frame = tk.Frame(inner_frame, bg='white')
    btn_frame.grid(row=4, column=0, columnspan=2, pady=(15, 0))

    login_btn = tk.Button(btn_frame, text="🚀 保存并登录", command=save_info,
                         bg='#3498db', fg='white', font=('Microsoft YaHei UI', 11, 'bold'),
                         relief='flat', bd=0, padx=25, pady=10,
                         cursor='hand2')
    login_btn.pack()

    # 按钮悬停效果
    login_btn.bind("<Enter>", lambda e: login_btn.config(bg='#2980b9'))
    login_btn.bind("<Leave>", lambda e: login_btn.config(bg='#3498db'))

    if auto_flag:
        load_info_without_auto()

    # 底部链接
    link_frame = tk.Frame(main_frame, bg='#ecf0f1')
    link_frame.pack(side='bottom', pady=(25, 10))

    link = tk.Label(link_frame, text="📚 项目地址", fg="#3498db", cursor="hand2",
                   bg='#ecf0f1', font=('Microsoft YaHei UI', 9, 'underline'))
    link.pack()
    link.bind("<Button-1>", open_url)

def show_logout_interface():
    for widget in root.winfo_children():
        widget.destroy()

    # 创建自定义标题栏
    title_bar = create_title_bar(root)

    # 主容器
    main_container = tk.Frame(root, bg='#ecf0f1')
    main_container.pack(fill='both', expand=True)

    main_frame = tk.Frame(main_container, bg='#ecf0f1')
    main_frame.pack(fill='both', expand=True, padx=15, pady=15)

    # 状态容器
    status_container = tk.Frame(main_frame, bg='#ecf0f1')
    status_container.pack(pady=50, padx=15, fill='x')

    # 阴影效果
    shadow_frame = tk.Frame(status_container, bg='#bdc3c7', height=2)
    shadow_frame.pack(fill='x', padx=2, pady=2)

    status_frame = tk.Frame(status_container, bg='white', relief='flat', bd=0)
    status_frame.pack(fill='x')

    # 内部填充
    inner_frame = tk.Frame(status_frame, bg='white')
    inner_frame.pack(padx=40, pady=40)

    # 状态图标和文字
    status_label = tk.Label(inner_frame, text="✅ 网络连接成功",
                           font=('Microsoft YaHei UI', 16, 'bold'),
                           fg='#27ae60', bg='white')
    status_label.pack(pady=(0, 30))

    # 登出按钮
    logout_btn = tk.Button(inner_frame, text="退出登录", command=logout,
                          bg='#e74c3c', fg='white', font=('Microsoft YaHei UI', 11, 'bold'),
                          relief='flat', bd=0, padx=30, pady=12,
                          cursor='hand2')
    logout_btn.pack()

    # 按钮悬停效果
    logout_btn.bind("<Enter>", lambda e: logout_btn.config(bg='#c0392b'))
    logout_btn.bind("<Leave>", lambda e: logout_btn.config(bg='#e74c3c'))

    # 底部链接
    link_frame = tk.Frame(main_frame, bg='#ecf0f1')
    link_frame.pack(side='bottom', pady=(30, 10))

    link = tk.Label(link_frame, text="📚 项目地址", fg="#3498db", cursor="hand2",
                   bg='#ecf0f1', font=('Microsoft YaHei UI', 9, 'underline'))
    link.pack()
    link.bind("<Button-1>", open_url)

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def force_taskbar_icon():
    """强制在任务栏显示图标"""
    root.update()  # 先更新一下窗口
    hwnd = GetForegroundWindow()  # 获取当时聚焦的窗口的句柄
    ShowWindow(hwnd, SW_HIDE)  # 隐藏窗口
    SetWindowLong(hwnd, GWL_EXSTYLE, GetWindowLong(hwnd, GWL_EXSTYLE) | WS_EX_APPWINDOW)  # 将窗口放在任务栏内
    ShowWindow(hwnd, SW_SHOW)  # 显示窗口

root = tk.Tk()
root.title("NJUPT 校园网助手")

# 移除系统标题栏和边框
root.overrideredirect(True)
root.configure(bg='#2c3e50')
root.resizable(False, False)

try:
    root.iconphoto(False, tk.PhotoImage(file=get_resource_path('njupt.png')))
except:
    pass

center_window(root, 420, 550)
setup_styles()

# 延迟执行强制任务栏图标显示
root.after(100, force_taskbar_icon)

# 在主程序入口处确保 config.bin 存在
ensure_config_exists()
show_login_interface()
load_info()
root.mainloop()