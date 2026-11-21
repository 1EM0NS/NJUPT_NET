using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Reflection;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace NjuptNet.Services;

public sealed class UpdateInfo
{
    public string Tag { get; init; } = "";
    public string PageUrl { get; init; } = "";
    public string DownloadUrl { get; init; } = "";
    public string AssetName { get; init; } = "";
    public long Size { get; init; }
    public string Sha256 { get; init; } = "";
    /// <summary>Release 只提供 SHA256SUMS.txt 时，用它兜底校验安装包。</summary>
    public string Sha256SumsUrl { get; init; } = "";
}

public enum UpdateCheckResult
{
    UpToDate,
    Available,
    Failed,
}

/// <summary>
/// 检查 GitHub Release；发现新版本时下载安装包并静默运行安装程序。
/// </summary>
public sealed class UpdateService
{
    private const string DefaultApiUrl = "https://api.github.com/repos/1EM0NS/NJUPT_NET/releases/latest";
    private const string DefaultLatestUrl = "https://github.com/1EM0NS/NJUPT_NET/releases/latest";
    private const string DefaultRepoUrl = "https://github.com/1EM0NS/NJUPT_NET";

    private static readonly string[] SetupAssetPrefixes = { "NJUPT_Net_Setup", "NJUPT_NET_Setup" };

    private readonly HttpClient _http = new(new HttpClientHandler
    {
        AllowAutoRedirect = true,
    })
    {
        Timeout = TimeSpan.FromSeconds(15),
    };

    private readonly HttpClient _redirectProbe = new(new HttpClientHandler
    {
        // 用 302 的 Location 反推最新 tag，避免依赖 api.github.com 是否可达。
        AllowAutoRedirect = false,
    })
    {
        Timeout = TimeSpan.FromSeconds(10),
    };

    private readonly string _apiUrl;
    private readonly string _latestUrl;

    public UpdateService(string? apiUrl = null, string? latestUrl = null)
    {
        _apiUrl = string.IsNullOrWhiteSpace(apiUrl) ? DefaultApiUrl : apiUrl;
        _latestUrl = string.IsNullOrWhiteSpace(latestUrl) ? DefaultLatestUrl : latestUrl;
    }

    public static string CurrentVersion =>
        typeof(UpdateService).Assembly.GetName().Version?.ToString(3) ?? "2.9.0";

    public async Task<(UpdateCheckResult Result, UpdateInfo? Info, string Error, string RemoteTag)> CheckAsync(
        CancellationToken token = default)
    {
        _http.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", "NJUPT_NET-updater");
        _http.DefaultRequestHeaders.TryAddWithoutValidation("Accept", "application/vnd.github+json");
        _redirectProbe.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", "NJUPT_NET-updater");

        string apiFailure;
        try
        {
            using var response = await _http.GetAsync(_apiUrl, token).ConfigureAwait(false);
            if (response.IsSuccessStatusCode)
            {
                var json = await response.Content.ReadAsStringAsync(token).ConfigureAwait(false);
                var parsed = ParseRelease(json, CurrentVersion, DefaultRepoUrl + "/releases/latest");
                if (parsed.Result == UpdateCheckResult.Available)
                {
                    Log.Write($"update available local={CurrentVersion} remote={parsed.RemoteTag} " +
                              $"asset={parsed.Info?.AssetName ?? "-"}");
                }
                else
                {
                    Log.Write($"update check ok local={CurrentVersion} remote={parsed.RemoteTag} " +
                              "state=up-to-date");
                }

                return parsed;
            }

            apiFailure = $"GitHub 返回 HTTP {(int)response.StatusCode}";
            Log.Write($"update api failed: {apiFailure}, trying redirect fallback");
        }
        catch (Exception ex)
        {
            apiFailure = ex.Message;
            Log.Write($"update api failed: {ex.GetType().Name}: {ex.Message}, trying redirect fallback");
        }

        // 降级：API 被限流/不可达时，用 releases/latest 的 302 目标反推 tag。
        // 此时拿不到资产清单，发现新版就让用户去发布页手动下载。
        try
        {
            var tag = await ResolveTagFromRedirectAsync(token).ConfigureAwait(false);
            if (string.IsNullOrEmpty(tag))
            {
                return (UpdateCheckResult.Failed, null, apiFailure, "");
            }

            if (!IsNewer(tag, CurrentVersion))
            {
                Log.Write($"update check ok local={CurrentVersion} remote={tag} state=up-to-date");
                return (UpdateCheckResult.UpToDate, null, "", tag);
            }

            Log.Write($"update available local={CurrentVersion} remote={tag} asset=- (redirect fallback)");
            return (UpdateCheckResult.Available,
                new UpdateInfo { Tag = tag, PageUrl = $"{DefaultRepoUrl}/releases/tag/{tag}" },
                "", tag);
        }
        catch (Exception ex)
        {
            Log.Write($"update redirect fallback failed: {ex.GetType().Name}: {ex.Message}");
            return (UpdateCheckResult.Failed, null, apiFailure, "");
        }
    }

    /// <summary>
    /// 解析 GitHub Release JSON。抽成静态方法便于用固定样本做回归，
    /// 也保证“有新版但没安装包”时不会误报可自动更新。
    /// </summary>
    public static (UpdateCheckResult Result, UpdateInfo? Info, string Error, string RemoteTag)
        ParseRelease(string json, string currentVersion, string fallbackPageUrl)
    {
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var tag = root.TryGetProperty("tag_name", out var t) ? t.GetString() ?? "" : "";
        if (string.IsNullOrWhiteSpace(tag))
        {
            return (UpdateCheckResult.Failed, null, "未获取到版本号", "");
        }

        var pageUrl = root.TryGetProperty("html_url", out var h) && !string.IsNullOrEmpty(h.GetString())
            ? h.GetString()!
            : fallbackPageUrl;

        UpdateInfo? setup = null;
        UpdateInfo? sums = null;
        if (root.TryGetProperty("assets", out var assets) && assets.ValueKind == JsonValueKind.Array)
        {
            foreach (var asset in assets.EnumerateArray())
            {
                var name = asset.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                var url = asset.TryGetProperty("browser_download_url", out var u) ? u.GetString() ?? "" : "";
                if (string.IsNullOrEmpty(name) || string.IsNullOrEmpty(url))
                {
                    continue;
                }

                if (setup is null && IsSetupAsset(name))
                {
                    setup = new UpdateInfo
                    {
                        Tag = tag,
                        PageUrl = pageUrl,
                        DownloadUrl = url,
                        AssetName = name,
                        Size = asset.TryGetProperty("size", out var s) ? s.GetInt64() : 0,
                        Sha256 = asset.TryGetProperty("digest", out var d) ? d.GetString() ?? "" : "",
                    };
                }
                else if (sums is null && name.Equals("SHA256SUMS.txt", StringComparison.OrdinalIgnoreCase))
                {
                    sums = new UpdateInfo
                    {
                        Tag = tag,
                        PageUrl = pageUrl,
                        DownloadUrl = url,
                        AssetName = name,
                    };
                }
            }
        }

        if (!IsNewer(tag, currentVersion))
        {
            return (UpdateCheckResult.UpToDate, null, "", tag);
        }

        if (setup is null)
        {
            // 有新版但还没上传安装包：只能引导到发布页，不能假装可以自动更新。
            return (UpdateCheckResult.Available,
                new UpdateInfo { Tag = tag, PageUrl = pageUrl },
                "", tag);
        }

        return (UpdateCheckResult.Available,
            new UpdateInfo
            {
                Tag = setup.Tag,
                PageUrl = setup.PageUrl,
                DownloadUrl = setup.DownloadUrl,
                AssetName = setup.AssetName,
                Size = setup.Size,
                Sha256 = setup.Sha256,
                Sha256SumsUrl = string.IsNullOrEmpty(setup.Sha256) && sums is not null
                    ? sums.DownloadUrl
                    : "",
            },
            "", tag);
    }

    private static bool IsSetupAsset(string name)
        => name.EndsWith(".exe", StringComparison.OrdinalIgnoreCase) &&
           SetupAssetPrefixes.Any(p => name.StartsWith(p, StringComparison.OrdinalIgnoreCase));

    private async Task<string> ResolveTagFromRedirectAsync(CancellationToken token)
    {
        using var response = await _redirectProbe.GetAsync(_latestUrl, token).ConfigureAwait(false);
        var location = response.Headers.Location?.ToString();
        if (string.IsNullOrEmpty(location))
        {
            return "";
        }

        // https://github.com/<owner>/<repo>/releases/tag/v3.1.0
        var marker = "/releases/tag/";
        var index = location.IndexOf(marker, StringComparison.OrdinalIgnoreCase);
        if (index < 0)
        {
            return "";
        }

        return Uri.UnescapeDataString(location[(index + marker.Length)..]).Trim('/');
    }

    public async Task<string> DownloadAsync(
        UpdateInfo info, IProgress<double>? progress, CancellationToken token = default)
    {
        var dir = Path.Combine(Path.GetTempPath(), "NJUPT_NET_update");
        Directory.CreateDirectory(dir);
        var target = Path.Combine(dir, info.AssetName);
        var partial = target + ".part";

        using var request = new HttpRequestMessage(HttpMethod.Get, info.DownloadUrl);
        using var response = await _http.SendAsync(
            request, HttpCompletionOption.ResponseHeadersRead, token).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();

        var total = response.Content.Headers.ContentLength ?? info.Size;
        var received = 0L;
        await using (var source = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false))
        await using (var sink = new FileStream(partial, FileMode.Create, FileAccess.Write, FileShare.None,
                         81920, useAsync: true))
        {
            var buffer = new byte[81920];
            int read;
            while ((read = await source.ReadAsync(buffer, token).ConfigureAwait(false)) > 0)
            {
                await sink.WriteAsync(buffer.AsMemory(0, read), token).ConfigureAwait(false);
                received += read;
                if (total > 0)
                {
                    progress?.Report((double)received / total);
                }
            }
        }

        if (received == 0)
        {
            throw new InvalidOperationException("下载内容为空");
        }

        if (info.Size > 0 && received != info.Size)
        {
            throw new InvalidOperationException($"文件大小不符（{received} != {info.Size}）");
        }

        var expected = NormalizeHash(info.Sha256);
        if (string.IsNullOrEmpty(expected) && !string.IsNullOrEmpty(info.Sha256SumsUrl))
        {
            expected = await TryReadHashFromSumsAsync(info, token).ConfigureAwait(false);
        }

        if (!string.IsNullOrEmpty(expected))
        {
            await using var check = File.OpenRead(partial);
            var actual = Convert.ToHexString(
                await System.Security.Cryptography.SHA256.HashDataAsync(check, token).ConfigureAwait(false));
            if (!string.Equals(actual, expected, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException("SHA256 校验失败");
            }
        }

        File.Move(partial, target, true);
        Log.Write($"update downloaded {target} size={received}");
        return target;
    }

    /// <summary>
    /// 从 Release 的 SHA256SUMS.txt 里取出安装包的哈希（格式：hash  filename）。
    /// 拿不到就返回空串，不阻断安装。
    /// </summary>
    private async Task<string> TryReadHashFromSumsAsync(UpdateInfo info, CancellationToken token)
    {
        try
        {
            var text = await _http.GetStringAsync(info.Sha256SumsUrl, token).ConfigureAwait(false);
            foreach (var line in text.Split('\n'))
            {
                var parts = line.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length < 2)
                {
                    continue;
                }

                var name = parts[^1].TrimStart('*');
                if (!name.Equals(info.AssetName, StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                var hash = NormalizeHash(parts[0]);
                if (!string.IsNullOrEmpty(hash))
                {
                    Log.Write($"update hash from SHA256SUMS.txt for {name}");
                    return hash;
                }
            }
        }
        catch (Exception ex)
        {
            Log.Write($"update sums fetch failed: {ex.GetType().Name}: {ex.Message}");
        }

        return "";
    }

    public void LaunchInstaller(string path)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = path,
                Arguments = "/SILENT /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS",
                UseShellExecute = true,
            });
            Log.Write($"installer launched: {path}");
        }
        catch (Exception ex)
        {
            Log.Write($"installer launch failed: {ex.Message}");
            throw;
        }
    }

    public static bool IsNewer(string remote, string local)
    {
        var r = VersionKey(remote);
        var l = VersionKey(local);
        if (r.Count == 0)
        {
            return false;
        }

        var size = Math.Max(r.Count, l.Count);
        for (var i = 0; i < size; i++)
        {
            var rv = i < r.Count ? r[i] : 0;
            var lv = i < l.Count ? l[i] : 0;
            if (rv != lv)
            {
                return rv > lv;
            }
        }
        return false;
    }

    private static List<int> VersionKey(string value)
    {
        var m = Regex.Match(value ?? "", @"\d+(?:\.\d+)*");
        return m.Success
            ? m.Value.Split('.').Select(p => int.TryParse(p, out var n) ? n : 0).ToList()
            : new List<int>();
    }

    private static string NormalizeHash(string value)
    {
        var text = (value ?? "").Trim().ToLowerInvariant();
        if (text.StartsWith("sha256:", StringComparison.Ordinal))
        {
            text = text[7..];
        }
        return Regex.IsMatch(text, "^[0-9a-f]{64}$") ? text : "";
    }
}
