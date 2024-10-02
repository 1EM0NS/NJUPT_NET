import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
import threading
import time
import os
from pythonping import ping
import sys
import requests



# 全局变量来存储提前初始化的WebDriver实例
preloaded_driver = None

def get_driver():
    options = webdriver.EdgeOptions()
    options.add_argument('--headless=old')

    return webdriver.Edge(options=options)


def preload_driver():
    global preloaded_driver
    preloaded_driver = get_driver()
    preloaded_driver.get("http://p.njupt.edu.cn")

# 启动一个线程来提前初始化WebDriver
preload_thread = threading.Thread(target=preload_driver)
preload_thread.start()

def get_preloaded_driver():
    global preloaded_driver
    preload_thread.join()  # 确保预加载线程已经完成
    return preloaded_driver if preloaded_driver else get_driver()

def save_credentials(username, password):
    with open('./credentials.txt', 'w') as f:
        f.write(f"{username}\n{password}")

def load_credentials():
    if os.path.exists('./credentials.txt'):
        with open('./credentials.txt', 'r') as f:
            lines = f.readlines()
            if len(lines) == 2:
                return lines[0].strip(), lines[1].strip()
    return None, None




def check_login_status():
    def perform_check():
        try:
            # Ping Baidu to check network connectivity
            response = ping('www.baidu.com', count=1, timeout=0.3)
            if response.success():
                root.after(0, show_logout_screen)
            else:
                root.after(0, show_login_screen)
        except Exception as e:
            root.after(0, show_login_screen)

    threading.Thread(target=perform_check).start()

def logout():
    def perform_logout():
        driver = get_preloaded_driver()
        driver.maximize_window()
        driver.set_window_rect(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
        driver.get("http://p.njupt.edu.cn")
        try:
            logout_button = driver.find_element(By.CSS_SELECTOR, "input.edit_lobo_cell[name='logout']")
            logout_button.click()
            confirm_button = driver.find_element(By.CSS_SELECTOR, "a.layui-layer-btn0")
            confirm_button.click()
            root.after(0, show_login_screen)
        except Exception as e:
            messagebox.showerror("Error", f"注销失败: {e}")

    threading.Thread(target=perform_logout).start()

def login():
    def perform_login():
        username = username_entry.get()
        password = password_entry.get()
        isp = isp_var.get()
        remember = remember_var.get()

        if not username or not password:
            root.withdraw()
            messagebox.showerror("Error", "Please enter both username and password")
            root.deiconify()
            return

        driver = get_preloaded_driver()
        driver.maximize_window()
        driver.set_window_rect(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())
        driver.get("http://p.njupt.edu.cn")

        try:
            username_field = driver.find_element(By.CSS_SELECTOR, "input.edit_lobo_cell[name='DDDDD']")
            password_field = driver.find_element(By.CSS_SELECTOR, "input.edit_lobo_cell[name='upass']")
        except:
            root.withdraw()
            messagebox.showerror("Error", "无法找到用户名或密码输入框")
            root.deiconify()
            return

        username_field.send_keys(username)
        password_field.send_keys(password)

        sel = driver.find_element(By.CSS_SELECTOR, "select.edit_lobo_cell.edit_select[name='ISP_select']")
        Select(sel).select_by_value(isp)

        driver.find_element(By.CSS_SELECTOR, "input.edit_lobo_cell[name='0MKKey']").click()
        # Check connectivity to Baidu
        try:
            response = ping('www.baidu.com', count=5, timeout=0.5)
            if response.success():
                if remember:
                    save_credentials(username, password)
                root.after(0, show_logout_screen)
            else:
                root.withdraw()
                messagebox.showerror("Error", "登陆失败")
                root.deiconify()
        except Exception as e:
            root.withdraw()
            messagebox.showerror("Error", "登陆失败")
            root.deiconify()

    threading.Thread(target=perform_login).start()

def show_login_screen():
    for widget in root.winfo_children():
        widget.destroy()

    frame = ttk.Frame(root)
    frame.grid(row=0, column=0, padx=10, pady=10)

    ttk.Label(frame, text="账号:").grid(row=0, column=0, padx=10, pady=5, sticky='e')
    global username_entry
    username_entry = ttk.Entry(frame)
    username_entry.grid(row=0, column=1, padx=10, pady=5, sticky='w')

    ttk.Label(frame, text="密码:").grid(row=1, column=0, padx=10, pady=5, sticky='e')
    global password_entry
    password_entry = ttk.Entry(frame, show="*")
    password_entry.grid(row=1, column=1, padx=10, pady=5, sticky='w')

    ttk.Label(frame, text="运营商:").grid(row=2, column=0, padx=10, pady=5, sticky='e')
    global isp_var
    isp_var = tk.StringVar(value="@cmcc")
    isp_menu = ttk.OptionMenu(frame, isp_var, "@cmcc", "@cmcc", "@njxy", "mobile.16848084816491")
    isp_menu.grid(row=2, column=1, padx=10, pady=5, sticky='w')

    global remember_var
    remember_var = tk.BooleanVar()
    remember_check = ttk.Checkbutton(frame, text="记住我", variable=remember_var)
    remember_check.grid(row=3, columnspan=2, pady=5)

    login_button = ttk.Button(frame, text="登录", command=login)
    login_button.grid(row=4, columnspan=2, pady=10)

    saved_username, saved_password = load_credentials()
    if saved_username and saved_password:
        username_entry.insert(0, saved_username)
        password_entry.insert(0, saved_password)
        remember_var.set(True)

    # Add GitHub link
    github_link = ttk.Label(frame, text="项目地址：1EM0NS/NJUPT_NET/", foreground="blue", cursor="hand2")
    github_link.grid(row=5, columnspan=2, pady=10)
    github_link.bind("<Button-1>", lambda e: os.system("start https://github.com/1EM0NS/NJUPT_NET/"))

    # Center the frame in the root window
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    frame.grid(row=0, column=0, padx=10, pady=10)

def show_logout_screen():
    for widget in root.winfo_children():
        widget.destroy()

    frame = ttk.Frame(root)
    frame.grid(row=0, column=0, padx=10, pady=10)

    ttk.Label(frame, text="你已登录").grid(row=0, column=0, padx=10, pady=10, sticky='n')

    logout_button = ttk.Button(frame, text="注销", command=logout)
    logout_button.grid(row=1, column=0, padx=10, pady=20, sticky='n')

    # Add GitHub link
    github_link = ttk.Label(frame, text="项目地址：1EM0NS/NJUPT_NET/", foreground="blue", cursor="hand2")
    github_link.grid(row=2, column=0, pady=10)
    github_link.bind("<Button-1>", lambda e: os.system("start https://github.com/1EM0NS/NJUPT_NET/"))

    # Center the frame in the root window
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    frame.grid(row=0, column=0, padx=10, pady=10)

def get_resource_path(relative_path):
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def center_window(root, width=400, height=300):
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)-100
    y = (screen_height // 2) - (height // 2)-200
    root.geometry(f'{width}x{height}+{x}+{y}')

root = tk.Tk()
root.title("NJUPT校园网登录")
center_window(root)  # Center the window on the screen
root.iconphoto(False, tk.PhotoImage(file=get_resource_path('t.png')))

style = ttk.Style()
style.configure('TLabel', font=('Arial', 12))
style.configure('TButton', font=('Arial', 12))
style.configure('TCheckbutton', font=('Arial', 12))

check_login_status()

root.mainloop()