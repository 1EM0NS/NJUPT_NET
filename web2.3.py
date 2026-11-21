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
import ctypes
from ctypes import wintypes
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
# 门户当前 a41.js: epHTTPPort=803, enHTTPSPort=804
PORTAL_API_PORT = 804
PORTAL_CONFIG_URL = "https://p.njupt.edu.cn:{}/eportal/portal/page/loadConfig".format(PORTAL_API_PORT)
PORTAL_LOGIN_URL = "https://p.njupt.edu.cn:{}/eportal/portal/login".format(PORTAL_API_PORT)
PORTAL_LOGOUT_URL = "https://p.njupt.edu.cn:{}/eportal/portal/logout".format(PORTAL_API_PORT)
PORTAL_ONLINE_URL = "https://p.njupt.edu.cn:{}/eportal/portal/online_list".format(PORTAL_API_PORT)
CANDIDATE_API_PORTS = (804, 802)
JS_VERSION = "4.5.1"
UPDATE_API_URL = "https://api.github.com/repos/1EM0NS/NJUPT_NET/releases/latest"
RELEASES_URL = "https://github.com/1EM0NS/NJUPT_NET/releases/latest"


def _ensure_api_port():
    """探测认证接口可用端口，兼容校方后续调整端口。"""
    global PORTAL_API_PORT, PORTAL_CONFIG_URL, PORTAL_LOGIN_URL, PORTAL_LOGOUT_URL, PORTAL_ONLINE_URL
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
        PORTAL_ONLINE_URL = "https://p.njupt.edu.cn:{}/eportal/portal/online_list".format(port)
        return port
    return PORTAL_API_PORT
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _read_js_string(page, name, default=""):
    match = re.search(r"\b{}\s*=\s*(['\"])(.*?)\1".format(re.escape(name)), page)
    return match.group(2).strip() if match else default


def _b64(value):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _log(message):
    try:
        path = os.path.join(os.path.dirname(get_config_path()), "njupt_net.log")
        line = "{} {}\n".format(time.strftime("%Y-%m-%d %H:%M:%S"), message)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _parse_jsonp(text):
    """解析 Dr.COM 响应；JSONP 回调名以服务器实际返回的为准。"""
    body = text.strip()
    if body.startswith("{"):
        return json.loads(body)
    m = re.fullmatch(r"(?:/\*\*/\s*)?[A-Za-z_$][\w$.]*\s*\((.*)\)\s*;?", body, re.DOTALL)
    if not m:
        raise ValueError("响应不是 JSON 或 JSONP")
    return json.loads(m.group(1))


def _version_key(value):
    match = re.search(r"\d+(?:\.\d+)*", str(value or ""))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(0).split("."))


def _is_newer_version(remote, local):
    remote_key = _version_key(remote)
    local_key = _version_key(local)
    if not remote_key:
        return False
    size = max(len(remote_key), len(local_key))
    remote_key += (0,) * (size - len(remote_key))
    local_key += (0,) * (size - len(local_key))
    return remote_key > local_key


def _latest_release():
    """读取 GitHub 最新正式 Release；API 限流时退回 releases/latest 跳转。"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "NJUPT_Net-update-check",
        "Accept": "application/vnd.github+json",
    })
    try:
        r = session.get(UPDATE_API_URL, timeout=(3.05, 6))
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict):
                tag = str(data.get("tag_name") or "").strip()
                if tag:
                    return {
                        "tag": tag,
                        "url": data.get("html_url") or RELEASES_URL,
                        "name": data.get("name") or tag,
                    }
        _log("update api status={} body={}".format(r.status_code, r.text[:200]))
    except (requests.exceptions.RequestException, ValueError) as exc:
        _log("update api failed: {!r}".format(exc))

    try:
        r = session.get(RELEASES_URL, allow_redirects=False, timeout=(3.05, 6))
        location = r.headers.get("Location", "")
        if location:
            url = urllib.parse.urljoin(RELEASES_URL, location)
            tag = urllib.parse.unquote(url.rstrip("/").rsplit("/", 1)[-1])
            if tag:
                return {"tag": tag, "url": url, "name": tag}
        _log("update redirect status={} location={}".format(r.status_code, location))
    except requests.exceptions.RequestException as exc:
        _log("update redirect failed: {!r}".format(exc))
    raise RuntimeError("无法获取最新版本信息")


def _portal_online_session(session):
    """查询本机当前在线会话；离线或查询失败返回 None。"""
    headers = {"User-Agent": USER_AGENT, "Referer": PORTAL_URL}
    try:
        page = session.get(PORTAL_URL, headers=headers, timeout=8).text
        ip = _read_js_string(page, "ss5") or _read_js_string(page, "v46ip")
        ipaddress.IPv4Address(ip)
    except (requests.exceptions.RequestException, ValueError) as exc:
        _log("online session: portal page failed: {!r}".format(exc))
        return None
    params = [
        ("callback", "dr1002"), ("user_account", ""), ("user_password", ""),
        ("wlan_user_mac", "000000000000"),
        ("wlan_user_ip", str(int(ipaddress.IPv4Address(ip)))),
        ("curr_user_ip", ""), ("jsVersion", JS_VERSION),
        ("v", "10081"), ("lang", "zh"),
    ]
    try:
        r = session.get(PORTAL_ONLINE_URL, params=params, headers=headers, timeout=8)
        payload = _parse_jsonp(r.text)
    except (requests.exceptions.RequestException, ValueError) as exc:
        _log("online_list failed: {!r}".format(exc))
        return None
    _log("online_list port={} ip={} result={} msg={}".format(
        PORTAL_API_PORT, ip, payload.get("result"), payload.get("msg")))
    if str(payload.get("result")) != "1":
        return None
    items = payload.get("list") or []
    if not items:
        return None
    first = items[0]
    return {
        "ip": first.get("online_ip") or ip,
        "account": str(first.get("user_account", "")),
        "mac": str(first.get("online_mac", "")) or "000000000000",
        "vlan": _read_js_string(page, "vlanid", "0") or "0",
        "session": str(first.get("online_session", "")),
    }


def _self_service_offline(session, account, info):
    """通过 Dr.COM 自服务踢掉本机当前会话，绕开失效的 AC 注销接口。"""
    headers = {"User-Agent": USER_AGENT, "Referer": PORTAL_URL}
    try:
        ip = str(info.get("ip") or "")
        ip_int = str(int(ipaddress.IPv4Address(ip)))
    except (TypeError, ValueError):
        return False, "无法识别本机 IP"
    mac = (info.get("mac") or "000000000000").upper()
    params = {
        "callback": "dr{}".format(time.time_ns() % 1000000000),
        "self_type": "1",
        "user_account": account or info.get("account", ""),
        "user_password": "",
        "wlan_user_mac": mac,
        "wlan_user_ip": ip_int,
        "jsVersion": JS_VERSION,
        "v": str(random.randrange(500, 10500)),
        "lang": "zh",
    }
    submitted = False
    try:
        self_url = "https://p.njupt.edu.cn:{}/eportal/portal/self".format(PORTAL_API_PORT)
        r = session.get(self_url, params=params, headers=headers, timeout=10)
        payload = _parse_jsonp(r.text)
        auth_url = payload.get("self_auth_url") or ""
        if str(payload.get("result")) != "1" or not auth_url:
            return False, str(payload.get("msg", "自服务入口获取失败"))

        # 打开门户签发的免密链接，建立自服务登录态。
        r = session.get(auth_url, headers=headers, timeout=12)
        parts = urllib.parse.urlsplit(r.url)
        base = "{}://{}".format(parts.scheme, parts.netloc)
        self_headers = {
            "User-Agent": USER_AGENT,
            "Referer": "{}/Self/dashboard".format(base),
            "X-Requested-With": "XMLHttpRequest",
        }
        r = session.get(base + "/Self/dashboard/getOnlineList",
                        params={"order": "asc", "_": str(int(time.time() * 1000))},
                        headers=self_headers, timeout=10)
        items = r.json()
        if isinstance(items, dict):
            items = items.get("rows") or items.get("data") or []
        target = None
        for item in items or []:
            if str(item.get("ip", "")) == ip:
                target = item
                break
        if target is None:
            return True, "本机会话已不在线"
        session_id = target.get("sessionId")
        if session_id in (None, ""):
            return False, "自服务未返回会话编号"

        submitted = True
        r = session.get(base + "/Self/dashboard/tooffline",
                        params={"sessionid": str(session_id)},
                        headers=self_headers, timeout=10)
        payload = r.json()
        if payload.get("success"):
            _log("self-service offline ok ip={} sid={}".format(ip, session_id))
            return True, "已通过自服务注销"
        return False, "自服务注销失败"
    except (requests.exceptions.RequestException, ValueError) as exc:
        if submitted:
            _log("self-service offline submitted, response lost: {!r}".format(exc))
            return True, "已提交注销，网络已断开"
        _log("self-service offline failed: {!r}".format(exc))
        return False, "自服务注销失败：{}".format(exc)


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
        ("callback", callback), ("jsVersion", JS_VERSION),
        ("v", str(random.randrange(500, 10500))), ("lang", "zh"),
    ]
    r = session.get(PORTAL_CONFIG_URL, params=cfg_params,
                    headers={"Referer": PORTAL_URL, "User-Agent": USER_AGENT}, timeout=10)
    text = r.text.strip()
    _log("loadConfig status={} body={}".format(r.status_code, text[:300]))
    try:
        payload = _parse_jsonp(text)
    except ValueError:
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
        ("authex_enable", ""), ("jsVersion", JS_VERSION),
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
    _log("login status={} body={}".format(r.status_code, text[:300]))
    try:
        result = _parse_jsonp(text)
    except ValueError:
        raise RuntimeError("登录响应格式异常：{}".format(text[:300]))
    code = result.get("result", 0)
    try:
        code = int(code)
    except (TypeError, ValueError):
        pass
    return code, str(result.get("msg", "未知错误"))


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
    try:
        root.destroy()
    except tk.TclError:
        pass
    os._exit(0)

def minimize_window():
    """无边框窗口不能用 Tk 的 iconify，直接走 Win32 最小化。"""
    try:
        import ctypes
        hwnd = root.winfo_id()
        hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd
        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
    except Exception:
        try:
            root.iconify()
        except tk.TclError:
            pass

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
APP_VERSION = "2.4.0"

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
WIN_H = 670

SCALE = 1.0

try:
    from PIL import Image, ImageDraw, ImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

_IMG_CACHE = {}
_UI_QUEUE = queue.Queue()
STATE = {"online": None, "busy": False}
_UPDATE_CHECKED = False
_UPDATE_CHECKING = False
UPDATE_AVAILABLE = False
UPDATE_URL = RELEASES_URL
UPDATE_TAG = ""
_UPDATE_BANNER_TOKEN = 0


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
    check = tk.Label(row, text="检查更新", bg=bg, fg=ACCENT, cursor="hand2",
                     font=(FONT, 9, "underline"))
    check.pack(side="left", padx=(S(10), 0))
    check.bind("<Button-1>", lambda e: _start_update_check(True))
    link = tk.Label(row, text="项目地址", bg=bg, fg=ACCENT, cursor="hand2",
                    font=(FONT, 9, "underline"))
    link.pack(side="right")
    link.bind("<Button-1>", open_url)
    return row


def check_online():
    """以认证网关的在线列表为准，避免代理环境下的 204 误判。"""
    _ensure_api_port()
    session = requests.Session()
    session.trust_env = False
    session.verify = False
    return _portal_online_session(session) is not None


def _post(fn, *args):
    _UI_QUEUE.put((fn, args))


def _poll_queue():
    try:
        while True:
            fn, args = _UI_QUEUE.get_nowait()
            try:
                fn(*args)
            except Exception as exc:
                _log("UI callback {} failed: {!r}".format(
                    getattr(fn, "__name__", fn), exc))
    except queue.Empty:
        pass
    if STATE.get("busy") and time.time() - STATE.get("busy_since", 0) > 120:
        STATE["busy"] = False
        _set_status("error", "操作超时", "已自动恢复，请重试")
        _render_button()
        _log("busy state auto-reset after timeout")
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
        root.after(1500, lambda: _start_update_check(False))
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
    STATE["busy_since"] = 0
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
    if result == 1 or "没有在线会话" in msg:
        _post(_after_logout, True, msg)
    else:
        _post(_after_logout, False, msg)


def _wait_until_offline(seconds):
    """在限定时间内轮询；一旦确认离线就返回 False，超时仍在线返回 True。"""
    deadline = time.time() + seconds
    while True:
        if not check_online():
            return False
        if time.time() >= deadline:
            return True
        time.sleep(1.0)


def _after_logout(ok, msg):
    """网关的返回不可靠，最终以“探测是否还能上网”为准。"""
    _start_busy("正在确认退出结果…")
    _set_status("checking", "正在确认退出结果…", "")
    threading.Thread(target=_confirm_logout,
                     args=(ok, msg, STATE.get("account", "")), daemon=True).start()


def _confirm_logout(ok, msg, account):
    """注销生效有延迟，先等几秒；仍在线就再发一次注销请求。"""
    online = _wait_until_offline(5)
    if online and ok:
        try:
            portal_logout_flow(account)
        except Exception:
            pass
        online = _wait_until_offline(5)
    _post(_finish_logout_check, online, ok, msg)


def _finish_logout_check(online, ok, msg):
    global _AUTO_TRIED
    STATE["busy"] = False
    STATE["busy_since"] = 0
    STATE["online"] = bool(online)
    if not online:
        _AUTO_TRIED = True
        sub = "网络已断开，可随时重新登录" if ok else "网关未返回成功标识，但已确认离线"
        _set_status("offline", "已退出登录", sub)
    else:
        if "数据为空" in msg:
            sub = "自动注销未成功，可到门户“自服务”手动注销"
        else:
            sub = msg if not ok else "网关返回成功但仍能上网，注销可能未生效"
        _set_status("error", "退出失败", sub)
    _render_button()


def _start_busy(text):
    STATE["busy"] = True
    STATE["busy_since"] = time.time()
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
    suffix = SERVER_SUFFIX.get(var_server.get())
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
    suffix = SERVER_SUFFIX.get(var_server.get())
    full = account if suffix is None else "{}@{}".format(account, suffix)
    STATE["account"] = full
    _start_busy("正在退出…")
    _set_status("checking", "正在退出登录…", "")
    threading.Thread(target=_logout_worker, args=(full,), daemon=True).start()


def save_config(account, suffix, password, auto):
    config = [account, suffix, password, auto]
    try:
        with open(get_config_path(), "wb") as f:
            f.write(str(config).encode("utf-8"))
    except OSError:
        pass


SERVER_SUFFIX = {"校园网": None, "中国移动": "cmcc",
                 "中国电信": "njxy", "中国联通": "lt"}


def _persist_toggle():
    """开关一变动就写盘，不必等到点登录。"""
    try:
        if entry_id is None or entry_password is None or var_server is None:
            return
        account = entry_id.get().strip()
        password = entry_password.get()
        if not account or not password:
            return
        save_config(account, SERVER_SUFFIX.get(var_server.get()), password,
                    bool(auto_login.get()))
    except Exception:
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
    """按门户自身的注销方式调用：优先不传账号/IP，由网关按源 IP 识别。"""
    _ensure_api_port()
    session = requests.Session()
    session.verify = False
    session.trust_env = False
    headers = {"User-Agent": USER_AGENT, "Referer": PORTAL_URL}
    info = _portal_online_session(session)
    if not info:
        _log("logout skipped: no online session for this IP")
        return 0, "当前没有在线会话，请直接登录"

    ok, self_msg = _self_service_offline(session, account, info)
    if ok:
        return 1, self_msg
    _log("self-service logout unavailable: {}".format(self_msg))

    callback = "dr{}".format(time.time_ns() % 1000000000)

    # 1. 官方 logout_portal()：ac_logout>0 时的固定参数
    params = {
        "callback": callback,
        "login_method": "1",
        "user_account": "drcom",
        "user_password": "123",
        "ac_logout": "1",
        "register_mode": "1",
        "wlan_user_ip": info["ip"],
        "wlan_user_ipv6": "",
        "wlan_vlan_id": info["vlan"],
        "wlan_user_mac": "000000000000",
        "wlan_ac_ip": "",
        "wlan_ac_name": "",
        "jsVersion": JS_VERSION,
        "v": str(random.randrange(500, 10500)),
        "lang": "zh",
    }
    r = session.get(PORTAL_LOGOUT_URL, params=params,
                    headers=headers, timeout=15)
    text = r.text.strip()
    _log("logout portal status={} body={}".format(r.status_code, text[:300]))
    try:
        payload = _parse_jsonp(text)
    except ValueError:
        payload = {}
    code = payload.get("result", payload.get("code", 0))
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = 0
    if code == 1:
        return code, str(payload.get("msg", "注销成功"))

    # 2. 本地认证旧页面：空参数注销
    r = session.get(PORTAL_LOGOUT_URL,
                    params={"callback": callback, "jsVersion": JS_VERSION},
                    headers=headers, timeout=15)
    text = r.text.strip()
    _log("logout default status={} body={}".format(r.status_code, text[:300]))
    try:
        payload = _parse_jsonp(text)
    except ValueError:
        raise RuntimeError("注销响应格式异常：{}".format(text[:200]))
    code = payload.get("result", payload.get("code", 0))
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = 0
    return code, str(payload.get("msg", "未知错误"))


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


def _hide_update_banner(token=None):
    if token is not None and token != _UPDATE_BANNER_TOKEN:
        return
    if update_banner is not None:
        update_banner.pack_forget()


def _show_update_banner(text, color=ACCENT, clickable=False, hide_after=0):
    global _UPDATE_BANNER_TOKEN
    if update_banner is None:
        return
    _UPDATE_BANNER_TOKEN += 1
    token = _UPDATE_BANNER_TOKEN
    update_banner.configure(
        text=text,
        fg=color,
        cursor="hand2" if clickable else "",
        font=(FONT, 9, "underline") if clickable else (FONT, 9),
    )
    update_banner.pack_forget()
    update_banner.pack(side="bottom", fill="x", padx=S(26), pady=(0, S(2)))
    if hide_after:
        root.after(hide_after, lambda: _hide_update_banner(token))


def _on_update_banner(event=None):
    if UPDATE_AVAILABLE and UPDATE_URL:
        webbrowser.open_new(UPDATE_URL)
    else:
        _start_update_check(True)


def _start_update_check(manual=False):
    global _UPDATE_CHECKED, _UPDATE_CHECKING
    if _UPDATE_CHECKING:
        return
    if not manual and _UPDATE_CHECKED:
        return
    _UPDATE_CHECKED = True
    _UPDATE_CHECKING = True
    if manual:
        _show_update_banner("正在检查更新…", MUTED, False)
    threading.Thread(target=_update_check_worker, args=(manual,), daemon=True).start()


def _update_check_worker(manual):
    try:
        result = _latest_release()
    except Exception as exc:
        _post(_update_check_done, manual, None, str(exc) or type(exc).__name__)
        return
    _post(_update_check_done, manual, result, "")


def _update_check_done(manual, result, error):
    global _UPDATE_CHECKING, UPDATE_AVAILABLE, UPDATE_URL, UPDATE_TAG
    _UPDATE_CHECKING = False
    if error or not result:
        _log("update check failed: {}".format(error))
        if manual:
            _show_update_banner("检查更新失败，点击重试", RED, True)
        return
    tag = str(result.get("tag") or "")
    url = result.get("url") or RELEASES_URL
    UPDATE_TAG = tag
    if _is_newer_version(tag, APP_VERSION):
        UPDATE_AVAILABLE = True
        UPDATE_URL = url
        _show_update_banner("发现新版本 {} · 点击下载".format(tag), ACCENT, True)
        _log("update available local={} remote={}".format(APP_VERSION, tag))
    else:
        UPDATE_AVAILABLE = False
        UPDATE_URL = RELEASES_URL
        if manual:
            _show_update_banner("已是最新版本 v{}".format(APP_VERSION), MUTED,
                                False, hide_after=4500)


def show_main_interface():
    global entry_id, entry_password, var_server, auto_login
    global startup_btn, primary_btn, status_dot, status_label, status_sub, update_banner

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
    tk.Label(options_frame, text="启动时自动登录", bg=CARD, fg=TEXT,
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
    update_banner = tk.Label(body, text="", bg=BG, fg=ACCENT,
                             font=(FONT, 9), anchor="center")
    update_banner.bind("<Button-1>", _on_update_banner)

    load_config_into_ui()
    auto_login.trace_add("write", lambda *a: _persist_toggle())
    _render_button()
    refresh_status()


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def _taskbar_toplevel():
    """返回真正被外壳认作顶层的窗口（Tk 的根窗口外面还套了一层）。"""
    from ctypes import windll
    return windll.user32.GetParent(root.winfo_id()) or root.winfo_id()


def _taskbar_add_tab(hwnd):
    """用 ITaskbarList.AddTab 让外壳立刻建出任务栏按钮。"""
    try:
        import ctypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                        ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)
        clsid = GUID(0x56FDF344, 0xFD6D, 0x11D0,
                     (ctypes.c_ubyte * 8)(0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90))
        iid = GUID(0x56FDF342, 0xFD6D, 0x11D0,
                   (ctypes.c_ubyte * 8)(0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90))
        ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                    ctypes.byref(iid), ctypes.byref(ptr))
        if hr != 0 or not ptr.value:
            return False
        vtable = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        hr_init = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[3])
        hr_init(ptr)
        add_tab = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(vtable[4])
        ok = add_tab(ptr, ctypes.c_void_p(hwnd)) == 0
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
        release(ptr)
        return ok
    except Exception:
        return False


_nc_proc_ref = None
_nc_orig_proc = None
_fixed_win_size = (0, 0)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MINMAXINFO(ctypes.Structure):
    _fields_ = [("ptReserved", _POINT), ("ptMaxSize", _POINT),
                ("ptMaxPosition", _POINT), ("ptMinTrackSize", _POINT),
                ("ptMaxTrackSize", _POINT)]


def _install_borderless_nc_handler(hwnd):
    """让客户区铺满整个窗口：DWM 的关键帧动画要求窗口有 caption 位。"""
    global _nc_proc_ref, _nc_orig_proc
    if _nc_proc_ref is not None:
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        result_t = ctypes.c_ssize_t
        wndproc_t = ctypes.WINFUNCTYPE(result_t, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_size_t, ctypes.c_ssize_t)

        def _proc(h, msg, wparam, lparam):
            try:
                if msg == 0x0083 and wparam:      # WM_NCCALCSIZE：客户区 = 整窗
                    return 0
                if msg == 0x0084:                 # WM_NCHITTEST：一律算客户区
                    return 1                      # HTCLIENT
                if msg == 0x0024 and _fixed_win_size[0]:   # WM_GETMINMAXINFO
                    mmi = ctypes.cast(lparam, ctypes.POINTER(_MINMAXINFO)).contents
                    w, hh = _fixed_win_size
                    mmi.ptMinTrackSize.x = w
                    mmi.ptMinTrackSize.y = hh
                    mmi.ptMaxTrackSize.x = w
                    mmi.ptMaxTrackSize.y = hh
                    return 0
            except Exception:
                pass
            try:
                return user32.CallWindowProcW(_nc_orig_proc, h, msg, wparam, lparam)
            except Exception:
                return 0

        _nc_proc_ref = wndproc_t(_proc)
        setter = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        setter.restype = ctypes.c_void_p
        setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        user32.CallWindowProcW.restype = result_t
        user32.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_uint, ctypes.c_size_t,
                                           ctypes.c_ssize_t]
        old = setter(ctypes.c_void_p(hwnd), -4, ctypes.cast(_nc_proc_ref, ctypes.c_void_p))
        _nc_orig_proc = old
        if not old:
            _nc_proc_ref = None
    except Exception:
        _nc_proc_ref = None


def apply_aero_borderless(width=None, height=None):
    """补回 caption/thickframe 样式以获得 DWM 最小化动画，边框由 NC 处理抹掉。"""
    global _fixed_win_size
    try:
        hwnd = _taskbar_toplevel()
        _install_borderless_nc_handler(hwnd)
        if width and height:
            _fixed_win_size = (int(width), int(height))
        elif not _fixed_win_size[0]:
            rect = wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
            if rect.right > rect.left and rect.bottom > rect.top:
                _fixed_win_size = (rect.right - rect.left, rect.bottom - rect.top)
        style = GetWindowLong(hwnd, GWL_STYLE)
        wanted = style | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX
        if wanted != style:
            SetWindowLong(hwnd, GWL_STYLE, wanted)
            SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
    except Exception:
        pass


def force_taskbar_icon():
    """无边框窗口要显式挂到任务栏：样式改在顶层，并让外壳立刻登记按钮。"""
    try:
        root.update()
        apply_aero_borderless()
        hwnd = _taskbar_toplevel()
        ex = GetWindowLong(hwnd, GWL_EXSTYLE)
        wanted = (ex | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
        if wanted != ex:
            SetWindowLong(hwnd, GWL_EXSTYLE, wanted)
            SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
        if not _taskbar_add_tab(hwnd):
            ShowWindow(hwnd, 0)   # 兜底：隐藏再显示一次，迫使外壳重新登记按钮
            ShowWindow(hwnd, 5)
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
update_banner = None
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
apply_aero_borderless(S(WIN_W), S(WIN_H))
root.after(120, force_taskbar_icon)
root.after(300, _round_window_corners)

ensure_config_exists()
show_main_interface()
root.after(80, _poll_queue)
root.mainloop()
