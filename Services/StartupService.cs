using Microsoft.Win32;

namespace NjuptNet.Services;

public sealed class StartupService
{
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string ValueName = "NJUPT_NET";

    public bool IsEnabled
    {
        get
        {
            try
            {
                using var key = Registry.CurrentUser.OpenSubKey(RunKey, false);
                return key?.GetValue(ValueName) is string value && value.Length > 0;
            }
            catch (Exception ex)
            {
                Log.Write($"startup read failed: {ex.Message}");
                return false;
            }
        }
    }

    public (bool Ok, string Message) Set(bool enabled)
    {
        try
        {
            using var key = Registry.CurrentUser.OpenSubKey(RunKey, true)
                ?? Registry.CurrentUser.CreateSubKey(RunKey, true);
            if (key is null)
            {
                return (false, "无法打开开机启动注册表项");
            }

            if (enabled)
            {
                var exe = Environment.ProcessPath;
                if (string.IsNullOrEmpty(exe))
                {
                    return (false, "无法获取程序路径");
                }
                key.SetValue(ValueName, $"\"{exe}\"", RegistryValueKind.String);
            }
            else
            {
                key.DeleteValue(ValueName, false);
            }

            return (true, enabled ? "已开启开机自启" : "已关闭开机自启");
        }
        catch (Exception ex)
        {
            Log.Write($"startup write failed: {ex.Message}");
            return (false, $"设置开机自启失败：{ex.Message}");
        }
    }
}
