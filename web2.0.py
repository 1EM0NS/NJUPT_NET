import os
import sys
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
import requests
import time
import ast


auto_flag = False

def open_url(event):
    webbrowser.open_new("https://github.com/1EM0NS/NJUPT_NET/")



def load_info():
    global auto_flag
    auto_flag  = True
    try:
        with open("config.bin", "rb") as f:
            config = ast.literal_eval(f.read().decode("utf-8"))
            entry_id.insert(0, config[0])
            if config[1] == None:
                var_server.set("校园网")
            elif config[1] == "cmcc":
                var_server.set("中国移动")
            elif config[1] == "njxy":
                var_server.set("中国电信")
            entry_password.insert(0, config[2])
            auto_login.set(config[3])
            if config[3]:
                login(config)
    except FileNotFoundError:
        pass

def load_info_without_auto():
    try:
        with open("config.bin", "rb") as f:
            config = ast.literal_eval(f.read().decode("utf-8"))
            entry_id.insert(0, config[0])
            if config[1] == None:
                var_server.set("校园网")
            elif config[1] == "cmcc":
                var_server.set("中国移动")
            elif config[1] == "njxy":
                var_server.set("中国电信")
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

    config = [Bid, server, password, auto_login_status]
    with open("config.bin", "wb") as f:
        f.write(str(config).encode("utf-8"))
    time.sleep(0.1)

    # messagebox.showinfo("信息", "您的信息已保存！准备登录...")
    login(config)

def login(config):
    if config[1] == None:
        url = ("https://p.njupt.edu.cn:802/eportal/portal/login?callback=dr1003&"
               "login_method=1&"
               "user_account=%2C0%2C{}&"
               "user_password={}&".format(config[0], config[2]))
    else:
        url = ("https://p.njupt.edu.cn:802/eportal/portal/login?callback=dr1003&"
               "login_method=1&"
               "user_account=%2C0%2C{}%40{}&"
               "user_password={}&".format(config[0], config[1], config[2]))

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36 Edg/118.0.2088.46",
        "Accept": "*/*"}

    while True:
        try:
            req = requests.get(url, headers=headers)
            if req.text == 'dr1003({"result":0,"msg":"AC999","ret_code":2});':
                messagebox.showerror("登录失败", "您已经登录到校园网！")
                show_logout_interface()
                break
            elif req.text == 'dr1003({"result":0,"msg":"运营商账号在线数超出限制，请联系运营商处理(Rad:Limit Users Err)","ret_code":1});':
                messagebox.showerror("登录失败", "您已经达到最大设备数，请至自助服务平台登出一个设备！")
            elif req.text == 'dr1003({"result":0,"msg":"账号或密码错误(ldap校验)","ret_code":1});':
                messagebox.showerror("登录失败", "用户名或密码错误！")
                messagebox.showinfo("提示", "请重新设置您的信息！")
                return
            elif req.text == 'dr1003({"result":0,"msg":"账号错误(运营商登录请检查输入的账号和绑定的运营商账号是否有误)","ret_code":1});':
                messagebox.showerror("登录失败", "您输入的运营商错误！")
                messagebox.showinfo("提示", "请重新设置您的信息！")
                return
            elif req.text == 'dr1003({"result":0,"msg":"本账号费用超支，禁止使用","ret_code":1});':
                messagebox.showerror("登录失败", "您的校园网账户费用超支，请至自助服务平台重设消费保护！")
            elif req.text == 'dr1003({"result":0,"msg":"运营商账号欠费或停机(Rad:Status_Err)","ret_code":1});':
                messagebox.showerror("登录失败", "您的校园卡欠费或停机，请充值您的校���卡！")
            elif req.text == 'dr1003({"result":1,"msg":"Portal协议认证成功！"});':
                messagebox.showinfo("登录成功", "登录成功！")
                show_logout_interface()
                break
            else:
                messagebox.showerror("登录失败", "未知错误！原始请求信息：\n" + req.text)
        except requests.exceptions.SSLError:
            messagebox.showerror("登录失败", "请检查您的网络连接！")

def logout():
    url = 'https://p.njupt.edu.cn:802/eportal/portal/logout'
    params = {
        'callback': 'dr1003',
        'login_method': '1',
        'user_account': 'drcom',
        'user_password': '123',
        'ac_logout': '1',
        'register_mode': '1',
        'wlan_user_ip': '10.136.160.206',
        'wlan_user_ipv6': '',
        'wlan_vlan_id': '0',
        'wlan_user_mac': '000000000000',
        'wlan_ac_ip': '',
        'wlan_ac_name': '',
        'jsVersion': '4.1.3',
        'v': '7267',
        'lang': 'zh'
    }

    headers = {
        'Accept': '*/*',
        'Accept-Encoding': 'gzip, deflate, br, zstd',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,zh-TW;q=0.5,en-IE;q=0.4',
        'Cookie': '_ga=GA1.1.148507178.1701333449; _ga_J6LT8812GZ=GS1.1.1701333448.1.1.1701334038.0.0.0',
        'Referer': 'https://p.njupt.edu.cn/',
        'Sec-Fetch-Dest': 'script',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'same-site',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0'
    }

    requests.get(url, params=params, headers=headers)
    show_login_interface()

def center_window(root, width=300, height=250):
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)-100
    y = (screen_height // 2) - (height // 2)-200
    root.geometry(f'{width}x{height}+{x}+{y}')

def show_login_interface():
    for widget in root.winfo_children():
        widget.destroy()
    frame = tk.Frame(root)
    frame.grid(row=0, column=0, padx=10, pady=10)

    ttk.Label(frame, text="学号").grid(row=0, column=0,padx=10, pady=5, sticky='e')
    global entry_id
    entry_id = ttk.Entry(frame)
    entry_id.grid(row=0, column=1, padx=10, pady=5, sticky='w')

    ttk.Label(frame, text="密码").grid(row=1, column=0,padx=10, pady=5, sticky='e')
    global entry_password
    entry_password = ttk.Entry(frame, show="*")
    entry_password.grid(row=1, column=1, padx=10, pady=5, sticky='w')

    ttk.Label(frame, text="运营商").grid(row=2, column=0, padx=10, pady=5, sticky='e')
    global var_server
    var_server = tk.StringVar()
    ttk.Combobox(frame, textvariable=var_server, values=["校园网", "中国移动", "中国电信"]).grid(row=2, column=1, padx=10, pady=5, sticky='e')

    global auto_login
    auto_login = tk.BooleanVar()
    ttk.Checkbutton(frame, text="自动登录", variable=auto_login).grid(row=3, column=0, columnspan=2, pady=5)

    tk.Button(frame, text="保存并登录", command=save_info).grid(row=4, column=0, columnspan=2, pady=10)
    if auto_flag:
        load_info_without_auto()

    link = tk.Label(root, text="项目地址", fg="blue", cursor="hand2")
    link.grid(row=5, column=0, pady=10)
    link.bind("<Button-1>", open_url)




def show_logout_interface():
    for widget in root.winfo_children():
        widget.destroy()

    tk.Label(root, text="你已登录").pack(pady=10)
    tk.Button(root, text="登出", command=logout, width=20, height=2).pack(pady=10)
    link = tk.Label(root, text="项目地址", fg="blue", cursor="hand2")
    link.pack(pady=10)
    link.bind("<Button-1>", open_url)


def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

root = tk.Tk()
root.title("NJUPT_NET")

root.iconphoto(False, tk.PhotoImage(file=get_resource_path('t.png')))
center_window(root)
style = ttk.Style()
style.configure('TLabel', font=('Arial', 12))
style.configure('TButton', font=('Arial', 12))
style.configure('TCheckbutton', font=('Arial', 12))
show_login_interface()
load_info()
root.mainloop()
