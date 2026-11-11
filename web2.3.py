import os
import sys
import socket
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

# ===== 南邮校园网 2026 新认证协议（eportal 802 动态流程）=====
PORTAL_URL = "https://p.njupt.edu.cn/"
# 2026-11 起认证接口端口由 804 改为 802（801 为同服务的 HTTP 端口）
PORTAL_API_PORT = 802
PORTAL_CONFIG_URL = "https://p.njupt.edu.cn:{}/eportal/portal/page/loadConfig".format(PORTAL_API_PORT)
PORTAL_LOGIN_URL = "https://p.njupt.edu.cn:{}/eportal/portal/login".format(PORTAL_API_PORT)
PORTAL_LOGOUT_URL = "https://p.njupt.edu.cn:{}/eportal/portal/logout".format(PORTAL_API_PORT)
CANDIDATE_API_PORTS = (802, 804)


def _ensure_api_port():
    """探测认证接口可用端口，兼容校方后续调整端口。"""
    global PORTAL_API_PORT, PORTAL_CONFIG_URL, PORTAL_LOGIN_URL, PORTAL_LOGOUT_URL
    for port in CANDIDATE_API_PORTS:
        try:
            with socket.create_connection(("p.njupt.edu.cn", port), timeout=2):
                pass
        except OSError:
            continue
        PORTAL_API_PORT = port
        PORTAL_CONFIG_URL = "https://p.njupt.edu.cn:{}/eportal/portal/page/loadConfig".format(port)
        PORTAL_LOGIN_URL = "https://p.njupt.edu.cn:{}/eportal/portal/login".format(port)
        PORTAL_LOGOUT_URL = "https://p.njupt.edu.cn:{}/eportal/portal/logout".format(port)
        return port
    return PORTAL_API_PORT
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
    _ensure_api_port()
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
    """新版注销：直接请求 802 logout（带上从门户页拿到的参数即可）"""
    _ensure_api_port()
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

    _set_busy(True)
    try:
        login(config)
    finally:
        _set_busy(False)

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
        show_logout_interface()
    elif "AC999" in msg:
        show_logout_interface()
    else:
        messagebox.showerror("登录失败", msg)

def logout():
    """新版注销流程"""
    portal_logout_flow()
    show_login_interface()

# ===== UI（v2.3 单页状态驱动）=====
APP_VERSION = "2.3"

import threading
import queue

BG = "#F3F6FC"
CARD = "#FFFFFF"
SOFT = "#F1F4FA"
FIELD_BG = "#F8FAFE"
LINE = "#DCE3EF"
TEXT = "#16202F"
MUTED = "#5C6779"
ACCENT = "#2F6BFF"
ACCENT_H = "#1E55E0"
ACCENT_P = "#1846BF"
ACCENT_SOFT = "#E7EEFF"
GREEN = "#12B76A"
RED = "#E5484D"
FONT = "Microsoft YaHei UI"

WIN_W = 440
WIN_H = 636

SCALE = 1.0

try:
    from PIL import Image, ImageDraw, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

_IMG_CACHE = {}
_UI_QUEUE = queue.Queue()
STATE = {"online": None, "busy": False}


def S(value):
    return int(round(value * SCALE))


def _cache(key, builder):
    photo = _IMG_CACHE.get(key)
    if photo is None:
        photo = builder()
        _IMG_CACHE[key] = photo
    return photo


def _photo_round_rect(w, h, r, fill, bg):
    if not _HAS_PIL or w <= 0 or h <= 0:
        return None

    def build():
        ss = 4
        big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        ImageDraw.Draw(big).rounded_rectangle(
            [0, 0, w * ss - 1, h * ss - 1], radius=max(0, int(round(r * ss))), fill=fill)
        small = big.resize((w, h), Image.LANCZOS)
        base = Image.new("RGBA", (w, h), bg)
        base.alpha_composite(small)
        return ImageTk.PhotoImage(base.convert("RGB"))

    return _cache(("rr", w, h, r, fill, bg), build)


def _photo_ellipse(w, h, fill, bg):
    if not _HAS_PIL or w <= 0 or h <= 0:
        return None

    def build():
        ss = 4
        big = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
        ImageDraw.Draw(big).ellipse([0, 0, w * ss - 1, h * ss - 1], fill=fill)
        small = big.resize((w, h), Image.LANCZOS)
        base = Image.new("RGBA", (w, h), bg)
        base.alpha_composite(small)
        return ImageTk.PhotoImage(base.convert("RGB"))

    return _cache(("el", w, h, fill, bg), build)


def _photo_gradient(w, h, c1, c2):
    if not _HAS_PIL or w <= 0 or h <= 0:
        return None

    def build():
        a = _hex_rgb(c1)
        b = _hex_rgb(c2)
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for y in range(h):
            t = y / max(1, h - 1)
            draw.line([(0, y), (w, y)],
                      fill=tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
        return ImageTk.PhotoImage(img)

    return _cache(("grad", w, h, c1, c2), build)


def _photo_badge(size, bg=CARD):
    if not _HAS_PIL or size <= 0:
        return None

    def build():
        ss = 4
        n = size * ss
        big = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        draw = ImageDraw.Draw(big)
        draw.ellipse([0, 0, n - 1, n - 1], fill="#E8F9F1")
        draw.line([(0.32 * n, 0.52 * n), (0.45 * n, 0.66 * n), (0.71 * n, 0.35 * n)],
                  fill=GREEN, width=max(2, int(round(size * 0.055 * ss))), joint="curve")
        small = big.resize((size, size), Image.LANCZOS)
        base = Image.new("RGBA", (size, size), bg)
        base.alpha_composite(small)
        return ImageTk.PhotoImage(base.convert("RGB"))

    return _cache(("badge", size, bg), build)


def _round_rect_points(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r, x2, y1 + r, x2, y2 - r,
        x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
        x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r,
        x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1,
        x1, y1, x1 + r, y1,
    ]


def _hex_rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def _shade(color, delta):
    r, g, b = _hex_rgb(color)
    return "#%02x%02x%02x" % tuple(max(0, min(255, c + delta)) for c in (r, g, b))


def _luma(color):
    r, g, b = _hex_rgb(color)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _text_on(fill):
    return "#FFFFFF" if _luma(fill) < 0.68 else TEXT


class RoundButton(tk.Canvas):
    def __init__(self, master, text="", command=None, width=300, height=46,
                 radius=12, fill=ACCENT, hover=None, press=None,
                 text_color=None, font=(FONT, 12, "bold"), bg=CARD, **kw):
        super().__init__(master, width=S(width), height=S(height), bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self._w0 = S(width)
        self._h = S(height)
        self._r = S(radius)
        self._bg = bg
        self._font = font
        self._command = command
        self._text = text
        self._state = 0
        self._enabled = True
        self._apply(fill, hover, press, text_color)
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._set_state(1))
        self.bind("<Leave>", lambda e: self._set_state(0))
        self.bind("<Button-1>", lambda e: self._set_state(2))
        self.bind("<ButtonRelease-1>", self._release)
        self._draw()

    def _apply(self, fill, hover=None, press=None, text_color=None):
        self._colors = (fill, hover or _shade(fill, -14), press or _shade(fill, -30))
        self._text_color = text_color or _text_on(fill)

    def _draw(self):
        w = self.winfo_width() or self._w0
        self.delete("all")
        photo = _photo_round_rect(w, self._h, self._r, self._colors[self._state], self._bg)
        if photo is not None:
            self.create_image(0, 0, anchor="nw", image=photo)
        else:
            self.create_polygon(_round_rect_points(0.5, 0.5, w - 0.5, self._h - 0.5, self._r),
                                smooth=True, splinesteps=24,
                                fill=self._colors[self._state], outline="")
        self.create_text(w / 2, self._h / 2 + 1, text=self._text,
                         fill=self._text_color, font=self._font)

    def _set_state(self, state):
        if not self._enabled:
            return
        self._state = state
        self._draw()

    def _release(self, event):
        if not self._enabled:
            return
        self._state = 1
        self._draw()
        if self._command and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self._h:
            self._command()

    def set_look(self, text=None, fill=None, text_color=None, enabled=None):
        if text is not None:
            self._text = text
        if fill is not None:
            self._apply(fill, None, None, text_color)
        elif text_color is not None:
            self._text_color = text_color
        if enabled is not None:
            self._enabled = enabled
            self.configure(cursor="hand2" if enabled else "arrow")
            self._state = 0
        self._draw()

    def config(self, **kw):
        text = kw.pop("text", None)
        fill = kw.pop("bg", None) or kw.pop("background", None)
        text_color = kw.pop("fg", None) or kw.pop("foreground", None)
        enabled = kw.pop("state", None)
        if enabled is not None:
            enabled = (enabled != "disabled")
        if kw:
            super().config(**kw)
        if text is not None or fill is not None or text_color is not None or enabled is not None:
            self.set_look(text=text, fill=fill, text_color=text_color, enabled=enabled)

    configure = config


class Segmented(tk.Canvas):
    def __init__(self, master, options, variable, height=42, radius=11, bg=CARD):
        super().__init__(master, height=S(height), bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2")
        self._opts = list(options)
        self._var = variable
        self._h = S(height)
        self._r = S(radius)
        self._pad = S(4)
        self._var.trace_add("write", lambda *a: self._draw())
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_click)
        self._draw()

    def _draw(self):
        w = self.winfo_width() or S(352)
        self.delete("all")
        track = _photo_round_rect(w, self._h, self._r, SOFT, CARD)
        if track is not None:
            self.create_image(0, 0, anchor="nw", image=track)
        else:
            self.create_polygon(_round_rect_points(0.5, 0.5, w - 0.5, self._h - 0.5, self._r),
                                smooth=True, splinesteps=20, fill=SOFT, outline="")
        n = len(self._opts)
        seg = (w - 2 * self._pad) / n
        for i, opt in enumerate(self._opts):
            x1 = int(round(self._pad + i * seg + S(2)))
            x2 = int(round(self._pad + (i + 1) * seg - S(2)))
            selected = (self._var.get() == opt)
            if selected:
                pill = _photo_round_rect(max(1, x2 - x1), self._h - 2 * self._pad,
                                         self._r - self._pad, ACCENT, SOFT)
                if pill is not None:
                    self.create_image(x1, self._pad, anchor="nw", image=pill)
                else:
                    self.create_polygon(_round_rect_points(x1, self._pad, x2, self._h - self._pad,
                                                           self._r - self._pad),
                                        smooth=True, splinesteps=20, fill=ACCENT, outline="")
            self.create_text((x1 + x2) / 2, self._h / 2 + 1, text=opt,
                             fill="#FFFFFF" if selected else MUTED,
                             font=(FONT, 10, "bold" if selected else "normal"))

    def _on_click(self, event):
        w = self.winfo_width() or S(352)
        n = len(self._opts)
        seg = (w - 2 * self._pad) / n
        idx = int((event.x - self._pad) // seg)
        if 0 <= idx < n:
            self._var.set(self._opts[idx])


class Switch(tk.Canvas):
    def __init__(self, master, variable, width=44, height=24, bg=CARD):
        super().__init__(master, width=S(width), height=S(height), bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._var = variable
        self._bw = S(width)
        self._bh = S(height)
        self._var.trace_add("write", lambda *a: self._draw())
        self.bind("<Button-1>", lambda e: self._var.set(not self._var.get()))
        self._draw()

    def _draw(self):
        on = bool(self._var.get())
        self.delete("all")
        track_color = ACCENT if on else "#CBD4E1"
        track = _photo_round_rect(self._bw, self._bh, self._bh // 2, track_color, CARD)
        if track is not None:
            self.create_image(0, 0, anchor="nw", image=track)
        else:
            self.create_polygon(_round_rect_points(0.5, 0.5, self._bw - 0.5,
                                                   self._bh - 0.5, self._bh / 2),
                                smooth=True, splinesteps=24,
                                fill=track_color, outline="")
        d = self._bh - S(6)
        cx = (self._bw - d - S(3)) if on else S(3)
        knob = _photo_ellipse(d, d, "#FFFFFF", track_color)
        if knob is not None:
            self.create_image(cx, S(3), anchor="nw", image=knob)
        else:
            self.create_oval(cx, S(3), cx + d, S(3) + d, fill="#FFFFFF", outline="")


class Field(tk.Frame):
    def __init__(self, master, caption, secret=False, bg=CARD):
        super().__init__(master, bg=bg)
        tk.Label(self, text=caption, bg=bg, fg=MUTED,
                 font=(FONT, 10)).pack(anchor="w", pady=(0, S(7)))
        box = tk.Frame(self, bg=FIELD_BG, highlightbackground=LINE,
                       highlightcolor=ACCENT, highlightthickness=1)
        box.pack(fill="x")
        self._box = box
        self.entry = tk.Entry(box, bd=0, relief="flat", bg=FIELD_BG, fg=TEXT,
                              insertbackground=ACCENT, highlightthickness=0,
                              font=(FONT, 12), show="*" if secret else "")
        if secret:
            self._eye = tk.Label(box, text="显示", bg=FIELD_BG, fg=MUTED,
                                 font=(FONT, 10), cursor="hand2")
            self._eye.pack(side="right", padx=(0, S(12)))
            self._eye.bind("<Button-1>", self._toggle_secret)
            self.entry.pack(side="left", fill="x", expand=True,
                            padx=(S(14), S(4)), ipady=S(8))
        else:
            self.entry.pack(fill="x", padx=S(14), ipady=S(8))
        self.entry.bind("<FocusIn>", lambda e: box.configure(highlightbackground=ACCENT))
        self.entry.bind("<FocusOut>", lambda e: box.configure(highlightbackground=LINE))

    def _toggle_secret(self, event=None):
        hidden = self.entry.cget("show") != ""
        self.entry.configure(show="" if hidden else "*")
        self._eye.configure(text="隐藏" if hidden else "显示")

    def get(self):
        return self.entry.get()

    def insert(self, index, value):
        self.entry.insert(index, "" if value is None else str(value))

    def focus_set(self):
        self.entry.focus_set()


def center_window(win, width=None, height=None):
    width = width or S(WIN_W)
    height = height or S(WIN_H)
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    win.geometry("{}x{}+{}+{}".format(width, height, x, y))


def create_title_bar(parent, height=100):
    h = S(height)
    width = S(WIN_W)
    bar = tk.Canvas(parent, width=width, height=h, highlightthickness=0, bd=0, bg=ACCENT)
    bar.pack(fill="x", side="top")
    grad = _photo_gradient(width, h, "#2F6BFF", "#6C4CF1")
    if grad is not None:
        bar.create_image(0, 0, anchor="nw", image=grad)
    else:
        for y in range(h):
            t = y / max(1, h - 1)
            color = "#%02x%02x%02x" % tuple(
                int(a + (b - a) * t) for a, b in zip((47, 107, 255), (108, 76, 241)))
            bar.create_line(0, y, width, y, fill=color)

    logo = _photo_ellipse(S(42), S(42), "#FFFFFF", ACCENT)
    if logo is not None:
        bar.create_image(S(22), S(32), anchor="nw", image=logo)
    else:
        bar.create_oval(S(22), S(32), S(64), S(74), fill="#FFFFFF", outline="")
    bar.create_text(S(43), S(53), text="N", fill=ACCENT, font=(FONT, 17, "bold"))
    bar.create_text(S(80), S(41), anchor="w", text="南邮校园网助手",
                    fill="#FFFFFF", font=(FONT, 15, "bold"))
    bar.create_text(S(80), S(66), anchor="w", text="NJUPT NET · v{}".format(APP_VERSION),
                    fill="#D6E1FF", font=(FONT, 9))

    bar.create_text(S(376), S(26), text="—", fill="#FFFFFF", font=(FONT, 13), tags="min")
    bar.create_text(S(406), S(24), text="✕", fill="#FFFFFF", font=(FONT, 12), tags="close")
    bar.tag_bind("min", "<Button-1>", lambda e: minimize_window())
    bar.tag_bind("close", "<Button-1>", lambda e: close_window())
    for tag in ("min", "close"):
        bar.tag_bind(tag, "<Enter>", lambda e: bar.configure(cursor="hand2"))
        bar.tag_bind(tag, "<Leave>", lambda e: bar.configure(cursor=""))

    bar.bind("<Button-1>", start_drag)
    bar.bind("<B1-Motion>", do_drag)
    return bar


def _outlined_card(parent, bg=CARD):
    return tk.Frame(parent, bg=bg, highlightbackground=LINE, highlightthickness=1)


def _link_row(parent, bg=BG):
    row = tk.Frame(parent, bg=bg)
    tk.Label(row, text="v{}".format(APP_VERSION), bg=bg, fg=MUTED,
             font=(FONT, 9)).pack(side="left")
    link = tk.Label(row, text="项目地址", bg=bg, fg=ACCENT, cursor="hand2",
                    font=(FONT, 9, "underline"))
    link.pack(side="right")
    link.bind("<Button-1>", open_url)
    return row


PROBE_URLS = ("http://connect.rom.miui.com/generate_204",
              "http://wifi.vivo.com.cn/generate_204")


def check_online():
    """能拿到 204 说明已经通过认证、可以正常上网。"""
    for url in PROBE_URLS:
        session = requests.Session()
        session.trust_env = False
        session.verify = False
        try:
            r = session.get(url, timeout=5, allow_redirects=False,
                            headers={"User-Agent": USER_AGENT})
            if r.status_code == 204:
                return True
        except requests.exceptions.RequestException:
            continue
    return False


def _post(fn, *args):
    _UI_QUEUE.put((fn, args))


def _poll_queue():
    try:
        while True:
            fn, args = _UI_QUEUE.get_nowait()
            fn(*args)
    except queue.Empty:
        pass
    root.after(80, _poll_queue)


def _set_status(kind, text, sub=""):
    """kind: checking / online / offline / error"""
    colors = {"checking": ACCENT, "online": GREEN, "offline": "#B6BFCD", "error": RED}
    color = colors.get(kind, "#B6BFCD")
    if status_dot is not None:
        status_dot.delete("all")
        img = _photo_ellipse(S(9), S(9), color, CARD)
        if img is not None:
            status_dot.create_image(0, 0, anchor="nw", image=img)
        else:
            status_dot.create_oval(0, 0, S(9), S(9), fill=color, outline="")
    if status_label is not None:
        status_label.configure(text=text, fg=TEXT if kind in ("online", "offline") else color)
    if status_sub is not None:
        status_sub.configure(text=sub)


def _render_button():
    if primary_btn is None:
        return
    if STATE["busy"]:
        primary_btn.set_look(text=STATE.get("busy_text", "处理中…"),
                             fill="#9DB8F5", text_color="#FFFFFF", enabled=False)
        return
    if STATE["online"] is True:
        primary_btn.set_look(text="退出登录", fill="#FDECEC",
                             text_color=RED, enabled=True)
    elif STATE["online"] is False:
        primary_btn.set_look(text="立即登录", fill=ACCENT,
                             text_color="#FFFFFF", enabled=True)
    else:
        primary_btn.set_look(text="正在检测…", fill="#9DB8F5",
                             text_color="#FFFFFF", enabled=False)


def _apply_status(online):
    global _AUTO_TRIED
    STATE["online"] = online
    if online:
        _set_status("online", "已连接 · 校园网可正常使用", "如需切换账号，请先退出登录")
    else:
        _set_status("offline", "未连接 · 请输入账号登录", "")
        if not _AUTO_TRIED and auto_login is not None and auto_login.get():
            _AUTO_TRIED = True
            if entry_id is not None and entry_id.get().strip():
                root.after(300, do_login)
    _render_button()


def _status_worker():
    _post(_apply_status, check_online())


def refresh_status():
    if STATE["busy"]:
        return
    STATE["online"] = None
    _set_status("checking", "正在检测网络状态…", "")
    _render_button()
    threading.Thread(target=_status_worker, daemon=True).start()


def _login_worker(account, password):
    try:
        result, msg = portal_login_flow(account, password)
    except RuntimeError as e:
        _post(_after_login, False, str(e))
        return
    except requests.exceptions.RequestException as e:
        _post(_after_login, False, "网络请求失败：{}: {}".format(type(e).__name__, e))
        return
    except Exception as e:
        _post(_after_login, False, "程序异常：{}: {}".format(type(e).__name__, e))
        return
    if result == 1:
        _post(_after_login, True, msg)
    elif "AC999" in msg:
        _post(_after_login, True, "当前账号已在线")
    else:
        _post(_after_login, False, msg)


def _after_login(ok, msg):
    STATE["busy"] = False
    STATE["online"] = True if ok else False
    if ok:
        _set_status("online", "已连接 · 校园网可正常使用", "如需切换账号，请先退出登录")
        _render_button()
        root.after(800, _verify_after_login)
    else:
        _set_status("error", "登录失败", msg)
        _render_button()


def _verify_after_login():
    threading.Thread(target=lambda: _post(_apply_status, check_online()), daemon=True).start()


def _logout_worker(account):
    try:
        result, msg = portal_logout_flow(account)
    except requests.exceptions.RequestException as e:
        _post(_after_logout, False, "网络请求失败：{}: {}".format(type(e).__name__, e))
        return
    except Exception as e:
        _post(_after_logout, False, "程序异常：{}: {}".format(type(e).__name__, e))
        return
    if result == 1:
        _post(_after_logout, True, msg)
    else:
        _post(_after_logout, False, msg)


def _after_logout(ok, msg):
    STATE["busy"] = False
    if ok:
        _set_status("offline", "已退出登录", msg)
        STATE["online"] = False
        _render_button()
        threading.Thread(target=_confirm_logout, daemon=True).start()
    else:
        _set_status("error", "退出失败", msg)
        _render_button()


def _confirm_logout():
    online = check_online()
    _post(_finish_logout_check, online)


def _finish_logout_check(online):
    if online:
        _apply_status(True)
        _set_status("error", "仍处于在线状态", "退出请求未被网关接受，可稍后重试")
    else:
        _apply_status(False)


def _start_busy(text):
    STATE["busy"] = True
    STATE["busy_text"] = text
    _render_button()


def on_primary():
    if STATE["busy"]:
        return
    if STATE["online"] is True:
        do_logout()
    elif STATE["online"] is False:
        do_login()


def do_login():
    account = entry_id.get().strip()
    password = entry_password.get()
    if not account:
        _set_status("error", "请填写学号", "账号不能为空")
        entry_id.focus_set()
        return
    if not password:
        _set_status("error", "请填写密码", "密码不能为空")
        entry_password.focus_set()
        return
    suffix = {"校园网": None, "中国移动": "cmcc",
              "中国电信": "njxy", "中国联通": "lt"}.get(var_server.get())
    save_config(account, suffix, password, auto_login.get())
    full = account if suffix is None else "{}@{}".format(account, suffix)
    _start_busy("正在登录…")
    _set_status("checking", "正在登录…", "")
    threading.Thread(target=_login_worker, args=(full, password), daemon=True).start()


def do_logout():
    account = entry_id.get().strip()
    if not account:
        load_config_into_ui()
        account = entry_id.get().strip()
    _start_busy("正在退出…")
    _set_status("checking", "正在退出登录…", "")
    threading.Thread(target=_logout_worker, args=(account,), daemon=True).start()


def save_config(account, suffix, password, auto):
    config = [account, suffix, password, auto]
    try:
        with open(get_config_path(), "wb") as f:
            f.write(str(config).encode("utf-8"))
    except OSError:
        pass


def load_config_into_ui():
    """把 config.bin 读进界面（不触发登录）。"""
    try:
        with open(get_config_path(), "rb") as f:
            config = ast.literal_eval(f.read().decode("utf-8"))
    except Exception:
        return
    if config[0]:
        entry_id.entry.delete(0, "end")
        entry_id.insert(0, config[0])
    if config[1] == "dx":
        config[1] = "njxy"
    mapping = {None: "校园网", "cmcc": "中国移动", "njxy": "中国电信", "lt": "中国联通"}
    var_server.set(mapping.get(config[1], "校园网"))
    if len(config) > 2 and config[2]:
        entry_password.entry.delete(0, "end")
        entry_password.insert(0, config[2])
    if len(config) > 3:
        auto_login.set(bool(config[3]))


def portal_logout_flow(account):
    """新版注销：必须带上本机 IP 等参数，否则网关回“注销操作非本机终端”。"""
    session = requests.Session()
    session.verify = False
    session.trust_env = False
    headers = {"User-Agent": USER_AGENT}
    client_ip = ""
    mac = "000000000000"
    vlan = "0"
    try:
        page = session.get(PORTAL_URL, headers=headers, timeout=10).text
        client_ip = _read_js_string(page, "ss5")
        mac = re.sub(r"[^0-9a-fA-F]", "", _read_js_string(page, "ss4", "")) or mac
        vlan = _read_js_string(page, "vlanid", "0") or "0"
    except requests.exceptions.RequestException:
        pass
    callback = "dr{}".format(time.time_ns() % 1000000000)
    params = {
        "user_account": account or "",
        "wlan_user_ip": client_ip,
        "wlan_user_mac": mac,
        "wlan_vlan_id": vlan,
        "wlan_ac_ip": "",
        "wlan_ac_name": "",
        "callback": callback,
        "jsVersion": "4.5",
        "lang": "zh",
    }
    r = session.get(PORTAL_LOGOUT_URL, params=params,
                    headers={"Referer": PORTAL_URL, **headers}, timeout=15)
    text = r.text.strip()
    m = re.search(r"{}\((.*)\);?".format(re.escape(callback)), text, re.DOTALL)
    try:
        payload = json.loads(m.group(1) if m else text)
    except json.JSONDecodeError:
        raise RuntimeError("注销响应格式异常：{}".format(text[:200]))
    return payload.get("result", 0), str(payload.get("msg", "未知错误"))


def update_startup_button():
    if startup_btn is None:
        return
    if check_startup():
        startup_btn.set_look(text="开机自启：开", fill=ACCENT_SOFT, text_color=ACCENT)
    else:
        startup_btn.set_look(text="开机自启：关", fill=SOFT, text_color=MUTED)


def set_startup(enable):
    """写入/删除开机自启注册表项（不弹窗，结果走状态栏）。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, 'frozen', False):
                app_path = sys.executable
            else:
                app_path = os.path.abspath(__file__)
            winreg.SetValueEx(key, "NJUPT_NET", 0, winreg.REG_SZ, app_path)
        else:
            try:
                winreg.DeleteValue(key, "NJUPT_NET")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        _set_status("error", "设置开机自启失败", str(e))


def toggle_startup():
    set_startup(not check_startup())
    update_startup_button()
    _set_hint("开机自启已开启，下次开机自动登录" if check_startup() else "开机自启已关闭")


def _set_hint(text):
    if status_sub is not None:
        status_sub.configure(text=text)


def show_main_interface():
    global entry_id, entry_password, var_server, auto_login
    global startup_btn, primary_btn, status_dot, status_label, status_sub

    for widget in root.winfo_children():
        widget.destroy()

    center_window(root, S(WIN_W), S(WIN_H))
    create_title_bar(root)

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)

    card = _outlined_card(body)
    card.pack(fill="x", padx=S(24), pady=(S(16), 0))

    inner = tk.Frame(card, bg=CARD)
    inner.pack(fill="x", padx=S(26), pady=S(20))

    status_row = tk.Frame(inner, bg=CARD)
    status_row.pack(fill="x")
    status_dot = tk.Canvas(status_row, width=S(9), height=S(9), bg=CARD, highlightthickness=0)
    status_dot.pack(side="left", pady=S(5))
    status_label = tk.Label(status_row, text="正在检测网络状态…", bg=CARD, fg=MUTED,
                            font=(FONT, 11, "bold"))
    status_label.pack(side="left", padx=(S(8), 0))
    refresh_link = tk.Label(status_row, text="刷新", bg=CARD, fg=ACCENT, cursor="hand2",
                            font=(FONT, 9))
    refresh_link.pack(side="right")
    refresh_link.bind("<Button-1>", lambda e: refresh_status())

    status_sub = tk.Label(inner, text="", bg=CARD, fg=MUTED,
                          font=(FONT, 9), anchor="w", justify="left")
    status_sub.pack(fill="x", pady=(S(6), S(18)))

    entry_id = Field(inner, "学号 / 账号")
    entry_id.pack(fill="x", pady=(0, S(14)))

    entry_password = Field(inner, "密码", secret=True)
    entry_password.pack(fill="x", pady=(0, S(14)))

    tk.Label(inner, text="运营商", bg=CARD, fg=MUTED,
             font=(FONT, 10)).pack(anchor="w")
    var_server = tk.StringVar(value="校园网")
    Segmented(inner, ["校园网", "中国移动", "中国电信", "中国联通"], var_server
              ).pack(fill="x", pady=(S(7), S(16)))

    options_frame = tk.Frame(inner, bg=CARD)
    options_frame.pack(fill="x", pady=(0, S(18)))

    auto_login = tk.BooleanVar(value=False)
    Switch(options_frame, auto_login).pack(side="left")
    tk.Label(options_frame, text="自动登录", bg=CARD, fg=TEXT,
             font=(FONT, 10)).pack(side="left", padx=(S(10), 0))

    startup_btn = RoundButton(options_frame, text="开机自启：关", command=toggle_startup,
                              width=114, height=30, radius=15, fill=SOFT,
                              text_color=MUTED, font=(FONT, 9), bg=CARD)
    startup_btn.pack(side="right")
    update_startup_button()

    primary_btn = RoundButton(inner, text="正在检测…", command=on_primary,
                              width=330, height=48, radius=13,
                              fill="#9DB8F5", text_color="#FFFFFF",
                              font=(FONT, 12, "bold"))
    primary_btn.pack(fill="x")

    _link_row(body).pack(side="bottom", fill="x", padx=S(26), pady=S(14))

    load_config_into_ui()
    _render_button()
    refresh_status()


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def force_taskbar_icon():
    try:
        root.update()
        hwnd = root.winfo_id()
        SetWindowLong(hwnd, GWL_EXSTYLE, GetWindowLong(hwnd, GWL_EXSTYLE) | WS_EX_APPWINDOW)
    except Exception:
        pass


def _enable_dpi_awareness():
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _apply_scale(win):
    global SCALE
    try:
        dpi = float(win.winfo_fpixels("1i"))
    except Exception:
        dpi = 96.0
    SCALE = max(1.0, dpi / 96.0)
    try:
        win.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


def _round_window_corners():
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
        value = ctypes.c_int(2)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 33, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


entry_id = None
entry_password = None
var_server = None
auto_login = None
startup_btn = None
primary_btn = None
status_dot = None
status_label = None
status_sub = None
_AUTO_TRIED = False

_enable_dpi_awareness()

root = tk.Tk()
root.title("南邮校园网助手 v{}".format(APP_VERSION))

_apply_scale(root)

root.overrideredirect(True)
root.configure(bg=BG)
root.resizable(False, False)

try:
    root.iconphoto(False, tk.PhotoImage(file=get_resource_path('njupt.png')))
except Exception:
    pass

center_window(root, S(WIN_W), S(WIN_H))
root.after(120, force_taskbar_icon)
root.after(300, _round_window_corners)

ensure_config_exists()
show_main_interface()
root.after(80, _poll_queue)
root.mainloop()
