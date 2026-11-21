using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using NjuptNet.Models;

namespace NjuptNet.Services;

/// <summary>
/// 配置保存在 %APPDATA%\NJUPT_NET\config.json，
/// 密码用 DPAPI（当前用户）加密，不再明文落盘。
/// 首次运行会自动迁移旧版 config.bin。
/// </summary>
public sealed class ConfigService
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("NJUPT_NET.config.v3");

    public string Directory => Log.Directory;

    public string FilePath => Path.Combine(Directory, "config.json");

    public AppConfig Load()
    {
        try
        {
            if (File.Exists(FilePath))
            {
                var stored = JsonSerializer.Deserialize<StoredConfig>(File.ReadAllText(FilePath, Encoding.UTF8));
                if (stored is not null)
                {
                    return new AppConfig
                    {
                        Account = stored.Account ?? "",
                        Suffix = NormalizeSuffix(stored.Suffix),
                        Password = Unprotect(stored.Password),
                        AutoLogin = stored.AutoLogin,
                    };
                }
            }
        }
        catch (Exception ex)
        {
            Log.Write($"config load failed: {ex.GetType().Name}: {ex.Message}");
        }

        return MigrateLegacy();
    }

    public void Save(AppConfig config)
    {
        try
        {
            System.IO.Directory.CreateDirectory(Directory);
            var stored = new StoredConfig
            {
                Account = config.Account,
                Suffix = NormalizeSuffix(config.Suffix),
                Password = Protect(config.Password),
                AutoLogin = config.AutoLogin,
            };
            var json = JsonSerializer.Serialize(stored, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText(FilePath, json, new UTF8Encoding(false));
        }
        catch (Exception ex)
        {
            Log.Write($"config save failed: {ex.GetType().Name}: {ex.Message}");
        }
    }

    private static string NormalizeSuffix(string? suffix) => suffix switch
    {
        "dx" => "njxy",
        "cmcc" or "njxy" or "lt" => suffix,
        _ => "",
    };

    private static string Protect(string plain)
    {
        if (string.IsNullOrEmpty(plain))
        {
            return "";
        }

        try
        {
            var bytes = ProtectedData.Protect(
                Encoding.UTF8.GetBytes(plain), Entropy, DataProtectionScope.CurrentUser);
            return "dpapi:" + Convert.ToBase64String(bytes);
        }
        catch (Exception ex)
        {
            Log.Write($"dpapi protect failed: {ex.Message}");
            return "plain:" + Convert.ToBase64String(Encoding.UTF8.GetBytes(plain));
        }
    }

    private static string Unprotect(string? stored)
    {
        if (string.IsNullOrEmpty(stored))
        {
            return "";
        }

        try
        {
            if (stored.StartsWith("dpapi:", StringComparison.Ordinal))
            {
                var bytes = ProtectedData.Unprotect(
                    Convert.FromBase64String(stored[6..]), Entropy, DataProtectionScope.CurrentUser);
                return Encoding.UTF8.GetString(bytes);
            }

            if (stored.StartsWith("plain:", StringComparison.Ordinal))
            {
                return Encoding.UTF8.GetString(Convert.FromBase64String(stored[6..]));
            }
        }
        catch (Exception ex)
        {
            Log.Write($"dpapi unprotect failed: {ex.GetType().Name}: {ex.Message}");
        }

        return "";
    }

    /// <summary>读取旧版 Python 程序目录里的 config.bin 并转存。</summary>
    private AppConfig MigrateLegacy()
    {
        try
        {
            var legacy = Path.Combine(AppContext.BaseDirectory, "config.bin");
            if (!File.Exists(legacy))
            {
                return new AppConfig();
            }

            var text = File.ReadAllText(legacy, Encoding.UTF8).Trim();
            var parsed = ParseLegacy(text);
            if (parsed is null)
            {
                return new AppConfig();
            }

            Save(parsed);
            Log.Write("legacy config.bin migrated");
            return parsed;
        }
        catch (Exception ex)
        {
            Log.Write($"legacy config migrate failed: {ex.Message}");
            return new AppConfig();
        }
    }

    /// <summary>解析 Python 字面量列表：['学号', None, '密码', False]</summary>
    private static AppConfig? ParseLegacy(string text)
    {
        if (!text.StartsWith('[') || !text.EndsWith(']'))
        {
            return null;
        }

        var items = SplitLegacy(text[1..^1]);
        if (items.Count < 2)
        {
            return null;
        }

        var config = new AppConfig
        {
            Account = Unquote(items[0]),
            Suffix = NormalizeSuffix(Unquote(items[1])),
            Password = items.Count > 2 ? Unquote(items[2]) : "",
            AutoLogin = items.Count > 3 && items[3].Trim() == "True",
        };
        return config;
    }

    private static List<string> SplitLegacy(string body)
    {
        var result = new List<string>();
        var sb = new StringBuilder();
        var quote = '\0';
        var escaped = false;

        foreach (var ch in body)
        {
            if (quote != '\0')
            {
                sb.Append(ch);
                if (escaped)
                {
                    escaped = false;
                }
                else if (ch == '\\')
                {
                    escaped = true;
                }
                else if (ch == quote)
                {
                    quote = '\0';
                }
                continue;
            }

            switch (ch)
            {
                case '\'' or '"':
                    quote = ch;
                    sb.Append(ch);
                    break;
                case ',':
                    result.Add(sb.ToString().Trim());
                    sb.Clear();
                    break;
                default:
                    sb.Append(ch);
                    break;
            }
        }

        if (sb.Length > 0)
        {
            result.Add(sb.ToString().Trim());
        }
        return result;
    }

    private static string Unquote(string value)
    {
        value = value.Trim();
        if (value is "None" or "null")
        {
            return "";
        }

        if (value.Length >= 2 &&
            (value[0] == '\'' || value[0] == '"') &&
            value[^1] == value[0])
        {
            var inner = value[1..^1];
            return inner
                .Replace("\\'", "'", StringComparison.Ordinal)
                .Replace("\\\"", "\"", StringComparison.Ordinal)
                .Replace("\\\\", "\\", StringComparison.Ordinal);
        }

        return value;
    }

    private sealed class StoredConfig
    {
        public string? Account { get; set; }
        public string? Suffix { get; set; }
        public string? Password { get; set; }
        public bool AutoLogin { get; set; }
    }
}
