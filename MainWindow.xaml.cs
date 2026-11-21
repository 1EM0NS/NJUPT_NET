using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;
using NjuptNet.Models;
using NjuptNet.Services;
using Wpf.Ui.Controls;

namespace NjuptNet;

public partial class MainWindow : FluentWindow
{
    private readonly ConfigService _configService = new();
    private readonly StartupService _startupService = new();
    private readonly PortalService _portal = new();
    private readonly DispatcherTimer _busyTimer;
    private readonly DispatcherTimer _toastTimer;

    private AppConfig _config = new();
    private bool? _online;
    private bool _busy;
    private bool _autoTried;
    private bool _loading = true;
    private bool _checkingUpdate;
    private bool _downloadingUpdate;
    private UpdateInfo? _update;
    private CancellationTokenSource? _operation;

    public MainWindow()
    {
        InitializeComponent();

        _busyTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(120) };
        _busyTimer.Tick += (_, _) =>
        {
            _busyTimer.Stop();
            if (_busy)
            {
                Log.Write("busy state auto-reset after timeout");
                EndBusy();
                SetStatus(StatusKind.Error, "操作超时", "已自动恢复，请重试");
            }
        };

        _toastTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2.6) };
        _toastTimer.Tick += (_, _) =>
        {
            _toastTimer.Stop();
            HideToast();
        };

        VersionText.Text = $"v{UpdateService.CurrentVersion}";
        Loaded += OnLoaded;
        Closed += (_, _) =>
        {
            _operation?.Cancel();
            _portal.Dispose();
        };
    }

    private async void OnLoaded(object sender, RoutedEventArgs e)
    {
        _loading = true;
        _config = _configService.Load();
        AccountBox.Text = _config.Account;
        PasswordBox.Password = _config.Password;
        SelectCarrier(_config.Suffix);
        AutoLoginSwitch.IsChecked = _config.AutoLogin;
        StartupSwitch.IsChecked = _startupService.IsEnabled;
        UpdateAccountPreview();
        _loading = false;

        var preview = Environment.GetEnvironmentVariable("NJUPT_NET_PREVIEW");
        if (!string.IsNullOrEmpty(preview))
        {
            // 预览/截图模式：只渲染界面，不访问网络，也不改动任何配置
            switch (preview)
            {
                case "offline":
                    _online = false;
                    SetStatus(StatusKind.Offline, "未连接", "填写账号后点击下方按钮登录");
                    break;
                case "error":
                    _online = false;
                    SetStatus(StatusKind.Error, "无法连接认证网关",
                        "连接认证服务器超时，请检查网络后重试");
                    break;
                case "checking":
                    _online = null;
                    SetStatus(StatusKind.Checking, "正在检测网络状态…", "");
                    break;
                default:
                    _online = true;
                    SetStatus(StatusKind.Online, "已连接", "校园网可正常使用 · 切换账号需先退出登录");
                    break;
            }
            RenderPrimaryButton();
            return;
        }

        await RefreshStatusAsync();
    }

    // ===== 状态 =====

    private enum StatusKind
    {
        Checking,
        Online,
        Offline,
        Error,
    }

    private void SetStatus(StatusKind kind, string text, string sub)
    {
        var (from, to) = kind switch
        {
            StatusKind.Online => (Color.FromRgb(0x0B, 0x8F, 0x62), Color.FromRgb(0x2B, 0xC4, 0x8A)),
            StatusKind.Offline => (Color.FromRgb(0x46, 0x55, 0x6E), Color.FromRgb(0x7A, 0x8A, 0xA5)),
            StatusKind.Error => (Color.FromRgb(0xB4, 0x23, 0x1E), Color.FromRgb(0xE5, 0x48, 0x4D)),
            _ => (Color.FromRgb(0x2F, 0x6B, 0xFF), Color.FromRgb(0x7C, 0x5C, 0xFF)),
        };

        StatusCard.Background = new LinearGradientBrush(from, to, new Point(0, 0), new Point(1, 1));
        StatusIcon.Symbol = kind switch
        {
            StatusKind.Online => SymbolRegular.Wifi124,
            StatusKind.Offline => SymbolRegular.WifiOff24,
            StatusKind.Error => SymbolRegular.ErrorCircle24,
            _ => SymbolRegular.ArrowSyncCircle24,
        };

        StatusText.Text = text;
        StatusSub.Text = sub;
        StatusSub.Visibility = string.IsNullOrWhiteSpace(sub) ? Visibility.Collapsed : Visibility.Visible;

        ActionHint.Text = kind switch
        {
            StatusKind.Online => "已认证上网，关闭窗口不会断开连接",
            StatusKind.Offline => "登录后即可正常访问校内外网络",
            StatusKind.Error => "请检查网络连接后点击刷新重试",
            _ => "正在与认证网关通信…",
        };
    }

    private void RenderPrimaryButton()
    {
        if (_busy)
        {
            PrimaryButton.Content = "处理中…";
            PrimaryButton.IsEnabled = false;
            SetActionColor("#8FA6D8");
            return;
        }

        PrimaryButton.IsEnabled = _online is not null;
        switch (_online)
        {
            case true:
                PrimaryButton.Content = "退出登录";
                SetActionColor("#E5484D");
                break;
            case false:
                PrimaryButton.Content = "立即登录";
                SetActionColor("#2F6BFF");
                break;
            default:
                PrimaryButton.Content = "正在检测…";
                SetActionColor("#8FA6D8");
                break;
        }
    }

    private void SetActionColor(string hex)
    {
        var color = (Color)ColorConverter.ConvertFromString(hex);
        PrimaryButton.Background = new SolidColorBrush(color);
        PrimaryButton.Foreground = new SolidColorBrush(Colors.White);
    }

    private void BeginBusy(string text)
    {
        _busy = true;
        _busyTimer.Stop();
        _busyTimer.Start();
        BusyRing.Visibility = Visibility.Visible;
        PrimaryButton.Content = text;
        PrimaryButton.IsEnabled = false;
        SetActionColor("#8FA6D8");
    }

    private void EndBusy()
    {
        _busy = false;
        _busyTimer.Stop();
        BusyRing.Visibility = Visibility.Collapsed;
        RenderPrimaryButton();
    }

    private async Task RefreshStatusAsync(bool allowAutoLogin = true)
    {
        if (_busy)
        {
            return;
        }

        _online = null;
        SetStatus(StatusKind.Checking, "正在检测网络状态…", "");
        RenderPrimaryButton();

        bool online;
        try
        {
            online = await _portal.IsOnlineAsync();
        }
        catch (Exception ex)
        {
            Log.Write($"status check failed: {ex.GetType().Name}: {ex.Message}");
            _online = false;
            SetStatus(StatusKind.Error, "无法连接认证网关", ex.Message);
            RenderPrimaryButton();
            return;
        }

        ApplyOnline(online, allowAutoLogin);
        if (online)
        {
            _ = CheckUpdateAsync(false);
        }
    }

    private void ApplyOnline(bool online, bool allowAutoLogin)
    {
        _online = online;
        if (online)
        {
            SetStatus(StatusKind.Online, "已连接", "校园网可正常使用 · 切换账号需先退出登录");
        }
        else
        {
            SetStatus(StatusKind.Offline, "未连接", "填写账号后点击下方按钮登录");
            if (allowAutoLogin && !_autoTried && AutoLoginSwitch.IsChecked == true &&
                !string.IsNullOrWhiteSpace(AccountBox.Text))
            {
                _autoTried = true;
                _ = Task.Delay(300).ContinueWith(
                    _ => Dispatcher.InvokeAsync(() => _ = LoginAsync()),
                    TaskScheduler.Default);
            }
        }
        RenderPrimaryButton();
    }

    // ===== 登录 / 注销 =====

    private async void OnPrimaryClick(object sender, RoutedEventArgs e)
    {
        if (_busy)
        {
            return;
        }

        if (_online is true)
        {
            await LogoutAsync();
        }
        else
        {
            await LoginAsync();
        }
    }

    private async Task LoginAsync()
    {
        var account = AccountBox.Text.Trim();
        var password = PasswordBox.Password;
        if (string.IsNullOrEmpty(account))
        {
            SetStatus(StatusKind.Error, "请填写学号", "账号不能为空");
            AccountBox.Focus();
            return;
        }
        if (string.IsNullOrEmpty(password))
        {
            SetStatus(StatusKind.Error, "请填写密码", "密码不能为空");
            PasswordBox.Focus();
            return;
        }

        PersistConfig();
        var full = BuildFullAccount(account);

        _operation?.Cancel();
        _operation = new CancellationTokenSource();
        BeginBusy("正在登录…");
        SetStatus(StatusKind.Checking, "正在登录…", "");

        try
        {
            var (ok, message) = await _portal.LoginAsync(full, password, _operation.Token);
            if (ok)
            {
                ApplyOnline(true, false);
                ShowToast("登录成功，网络已连接");
                _ = VerifyAsync();
            }
            else
            {
                _online = false;
                SetStatus(StatusKind.Error, "登录失败", message);
            }
        }
        catch (Exception ex)
        {
            _online = false;
            SetStatus(StatusKind.Error, "登录失败", ex.Message);
            Log.Write($"login failed: {ex.GetType().Name}: {ex.Message}");
        }
        finally
        {
            EndBusy();
        }
    }

    private async Task VerifyAsync()
    {
        await Task.Delay(800);
        try
        {
            var online = await _portal.IsOnlineAsync();
            ApplyOnline(online, false);
        }
        catch (Exception ex)
        {
            Log.Write($"verify failed: {ex.Message}");
        }
    }

    private async Task LogoutAsync()
    {
        var account = BuildFullAccount(AccountBox.Text.Trim());

        _operation?.Cancel();
        _operation = new CancellationTokenSource();
        BeginBusy("正在退出…");
        SetStatus(StatusKind.Checking, "正在退出登录…", "");

        var ok = false;
        var message = "";
        try
        {
            (ok, message) = await _portal.LogoutAsync(account, _operation.Token);
        }
        catch (Exception ex)
        {
            message = ex.Message;
            Log.Write($"logout failed: {ex.GetType().Name}: {ex.Message}");
        }

        BeginBusy("正在确认退出结果…");
        SetStatus(StatusKind.Checking, "正在确认退出结果…", "");
        var stillOnline = await WaitUntilOfflineAsync(5);
        if (stillOnline && ok)
        {
            try
            {
                await _portal.LogoutAsync(account, _operation.Token);
            }
            catch
            {
                // 已提交过，忽略重试异常
            }
            stillOnline = await WaitUntilOfflineAsync(5);
        }

        _online = stillOnline;
        if (!stillOnline)
        {
            _autoTried = true;
            SetStatus(StatusKind.Offline, "已退出登录",
                ok ? "网络已断开，可随时重新登录" : "网关未返回成功标识，但已确认离线");
        }
        else
        {
            var sub = message.Contains("数据为空", StringComparison.Ordinal)
                ? "自动注销未成功，可到门户「自服务」手动注销"
                : string.IsNullOrEmpty(message) ? "注销未生效，请重试" : message;
            SetStatus(StatusKind.Error, "退出失败", sub);
        }

        EndBusy();
    }

    private async Task<bool> WaitUntilOfflineAsync(int seconds)
    {
        var deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (true)
        {
            try
            {
                if (!await _portal.IsOnlineAsync())
                {
                    return false;
                }
            }
            catch (Exception ex)
            {
                Log.Write($"offline poll failed: {ex.Message}");
            }

            if (DateTime.UtcNow >= deadline)
            {
                return true;
            }
            await Task.Delay(1000);
        }
    }

    // ===== 配置 =====

    private string SelectedSuffix =>
        CarrierCmcc.IsChecked == true ? "cmcc"
        : CarrierNjxy.IsChecked == true ? "njxy"
        : CarrierLt.IsChecked == true ? "lt"
        : "";

    private string BuildFullAccount(string account)
    {
        var suffix = SelectedSuffix;
        return string.IsNullOrEmpty(suffix) ? account : $"{account}@{suffix}";
    }

    private void SelectCarrier(string suffix)
    {
        CarrierCampus.IsChecked = suffix is not ("cmcc" or "njxy" or "lt");
        CarrierCmcc.IsChecked = suffix == "cmcc";
        CarrierNjxy.IsChecked = suffix == "njxy";
        CarrierLt.IsChecked = suffix == "lt";
    }

    private void UpdateAccountPreview()
    {
        // XAML 加载期（IsChecked="True" 触发 Checked）控件可能尚未创建
        if (AccountPreview is null || AccountBox is null)
        {
            return;
        }

        var account = AccountBox.Text.Trim();
        if (string.IsNullOrEmpty(account))
        {
            AccountPreview.Text = "未填写账号，登录时会提示";
            return;
        }

        AccountPreview.Text = $"登录账号：{BuildFullAccount(account)}";
    }

    private void PersistConfig()
    {
        _config.Account = AccountBox.Text.Trim();
        _config.Suffix = SelectedSuffix;
        _config.Password = PasswordBox.Password;
        _config.AutoLogin = AutoLoginSwitch.IsChecked == true;
        _configService.Save(_config);
    }

    private void OnAccountChanged(object sender, TextChangedEventArgs e)
    {
        UpdateAccountPreview();
        if (!_loading)
        {
            PersistConfig();
        }
    }

    private void OnPasswordChanged(object sender, RoutedEventArgs e)
    {
        if (!_loading)
        {
            PersistConfig();
        }
    }

    private void OnCarrierChanged(object sender, RoutedEventArgs e)
    {
        UpdateAccountPreview();
        if (!_loading)
        {
            PersistConfig();
        }
    }

    private void OnAutoLoginChanged(object sender, RoutedEventArgs e)
    {
        if (!_loading)
        {
            PersistConfig();
        }
    }

    private async void OnRefreshClick(object sender, RoutedEventArgs e)
        => await RefreshStatusAsync(false);

    // ===== 开机自启 =====

    private void OnStartupToggled(object sender, RoutedEventArgs e)
    {
        if (_loading)
        {
            return;
        }

        var enable = StartupSwitch.IsChecked == true;
        var (ok, message) = _startupService.Set(enable);
        if (!ok)
        {
            _loading = true;
            StartupSwitch.IsChecked = !enable;
            _loading = false;
            ShowToast(message, true);
            return;
        }

        ShowToast(message);
    }

    // ===== 轻提示 =====

    private void ShowToast(string text, bool error = false)
    {
        ToastText.Text = text;
        ToastBorder.Background = new SolidColorBrush(
            error ? Color.FromRgb(0xFD, 0xEC, 0xEC) : Color.FromRgb(0xEA, 0xF7, 0xF1));
        ToastText.Foreground = new SolidColorBrush(
            error ? Color.FromRgb(0xB4, 0x23, 0x1E) : Color.FromRgb(0x0E, 0x7A, 0x55));

        ToastBorder.Visibility = Visibility.Visible;
        var fade = new DoubleAnimation(0, 1, TimeSpan.FromMilliseconds(160));
        ToastBorder.BeginAnimation(OpacityProperty, fade);

        _toastTimer.Stop();
        _toastTimer.Start();
    }

    private void HideToast()
    {
        var fade = new DoubleAnimation(1, 0, TimeSpan.FromMilliseconds(220));
        fade.Completed += (_, _) => ToastBorder.Visibility = Visibility.Collapsed;
        ToastBorder.BeginAnimation(OpacityProperty, fade);
    }

    // ===== 更新 =====

    private async void OnCheckUpdateClick(object sender, RoutedEventArgs e)
        => await CheckUpdateAsync(true);

    private async Task CheckUpdateAsync(bool manual)
    {
        if (_checkingUpdate || _downloadingUpdate)
        {
            return;
        }

        _checkingUpdate = true;
        if (manual)
        {
            ShowBanner("正在检查更新…", "#5B6577", null);
        }

        try
        {
            var (result, info, error, remoteTag) = await new UpdateService().CheckAsync();
            switch (result)
            {
                case UpdateCheckResult.Available when info is not null:
                    _update = info;
                    if (string.IsNullOrEmpty(info.DownloadUrl))
                    {
                        // Release 里还没有安装包时，只能打开发布页手动下载。
                        ShowBanner($"发现新版本 {info.Tag}，请前往发布页下载", "#2453C4", "前往发布页");
                    }
                    else
                    {
                        ShowBanner($"发现新版本 {info.Tag}，可立即更新", "#2453C4", "更新");
                    }
                    break;
                case UpdateCheckResult.UpToDate:
                    _update = null;
                    HideBanner();
                    if (manual)
                    {
                        ShowToast(string.IsNullOrEmpty(remoteTag)
                            ? $"已是最新版本 v{UpdateService.CurrentVersion}"
                            : $"已是最新版本 v{UpdateService.CurrentVersion}（线上 {remoteTag}）");
                    }
                    break;
                default:
                    HideBanner();
                    if (manual)
                    {
                        ShowBanner($"检查更新失败：{error}", "#DC2626", "重试");
                    }
                    break;
            }
        }
        finally
        {
            _checkingUpdate = false;
        }
    }

    private async void OnUpdateClick(object sender, RoutedEventArgs e)
    {
        if (_busy)
        {
            ShowToast("正在登录或注销，完成后再更新", true);
            return;
        }

        if (_update is null || string.IsNullOrEmpty(_update.DownloadUrl))
        {
            OpenUrl(_update?.PageUrl ?? "https://github.com/1EM0NS/NJUPT_NET/releases/latest");
            return;
        }

        if (_downloadingUpdate)
        {
            return;
        }

        _downloadingUpdate = true;
        var progress = new Progress<double>(p =>
            UpdateText.Text = $"正在下载更新… {p * 100:0}%");
        try
        {
            ShowBanner("正在下载更新…", "#2453C4", null);
            var service = new UpdateService();
            var path = await service.DownloadAsync(_update, progress);
            UpdateText.Text = "下载完成，正在启动安装程序…";
            service.LaunchInstaller(path);
            Application.Current.Shutdown();
        }
        catch (Exception ex)
        {
            Log.Write($"update download failed: {ex.GetType().Name}: {ex.Message}");
            ShowBanner($"更新失败：{ex.Message}", "#DC2626", "重试");
        }
        finally
        {
            _downloadingUpdate = false;
        }
    }

    private void ShowBanner(string text, string color, string? action)
    {
        UpdateText.Text = text;
        UpdateText.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(color));
        UpdateBanner.Visibility = Visibility.Visible;
        UpdateButton.Visibility = action is null ? Visibility.Collapsed : Visibility.Visible;
        if (action is not null)
        {
            UpdateButton.Content = action;
        }
    }

    private void HideBanner() => UpdateBanner.Visibility = Visibility.Collapsed;

    private void OnProjectClick(object sender, RoutedEventArgs e)
        => OpenUrl("https://github.com/1EM0NS/NJUPT_NET/");

    private static void OpenUrl(string url)
    {
        try
        {
            Process.Start(new ProcessStartInfo { FileName = url, UseShellExecute = true });
        }
        catch (Exception ex)
        {
            Log.Write($"open url failed: {ex.Message}");
        }
    }
}
