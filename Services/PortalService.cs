using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using NjuptNet.Models;

namespace NjuptNet.Services;

public sealed class PortalException : Exception
{
    public PortalException(string message) : base(message) { }
}

/// <summary>
/// 南邮 2026 新版 Dr.COM eportal 认证流程。
/// </summary>
public sealed class PortalService : IDisposable
{
    private const string PortalHost = "p.njupt.edu.cn";
    private const string PortalUrl = "https://p.njupt.edu.cn/";
    private const string JsVersion = "4.5.1";
    private const string UserAgent =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";

    private static readonly int[] CandidatePorts = { 804, 802 };
    /// <summary>门户域名解析被代理/TUN 劫持时的直连兜底地址。</summary>
    private static readonly string[] FallbackPortalIps = { "10.10.244.11" };
    private static readonly Random Rng = new();
    private static readonly object RngGate = new();

    private readonly HttpClient _http;
    private readonly CookieContainer _cookies = new();
    private int _port;
    private string _lastOnlineNote = "";
    private bool _onlineUnknown;

    public PortalService()
    {
        var handler = new SocketsHttpHandler
        {
            CookieContainer = _cookies,
            UseCookies = true,
            // 门户必须直连，不能被系统代理或 FlClash 的 TUN 配置接管。
            UseProxy = false,
            AllowAutoRedirect = true,
            AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate,
            ConnectTimeout = TimeSpan.FromSeconds(6),
            PooledConnectionLifetime = TimeSpan.FromMinutes(5),
            SslOptions = { RemoteCertificateValidationCallback = (_, _, _, _) => true },
            ConnectCallback = ConnectAsync,
        };

        _http = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromSeconds(20),
        };
        _http.DefaultRequestHeaders.TryAddWithoutValidation("User-Agent", UserAgent);
        _http.DefaultRequestHeaders.TryAddWithoutValidation("Accept-Language", "zh-CN,zh;q=0.9");
    }

    /// <summary>
    /// 先走系统 DNS；解析失败或返回不可用地址时回退到已知门户 IP。
    /// 只替换 TCP 目标地址，TLS 仍按原域名握手（SNI 不变）。
    /// </summary>
    private static async ValueTask<Stream> ConnectAsync(
        SocketsHttpConnectionContext context, CancellationToken token)
    {
        var endpoint = context.DnsEndPoint;
        var addresses = await ResolveAsync(endpoint.Host, token).ConfigureAwait(false);

        Exception? last = null;
        foreach (var address in addresses)
        {
            var socket = new Socket(address.AddressFamily, SocketType.Stream, ProtocolType.Tcp)
            {
                NoDelay = true,
            };
            try
            {
                await socket.ConnectAsync(new IPEndPoint(address, endpoint.Port), token)
                    .ConfigureAwait(false);
                return new NetworkStream(socket, ownsSocket: true);
            }
            catch (Exception ex) when (ex is SocketException or OperationCanceledException)
            {
                socket.Dispose();
                last = ex;
                if (token.IsCancellationRequested)
                {
                    break;
                }
            }
        }

        throw last ?? new SocketException((int)SocketError.HostNotFound);
    }

    private static async Task<List<IPAddress>> ResolveAsync(string host, CancellationToken token)
    {
        if (IPAddress.TryParse(host, out var literal))
        {
            return new List<IPAddress> { literal };
        }

        var result = new List<IPAddress>();
        try
        {
            // DNS 服务器不可达时（例如代理关闭后 DHCP 仍指向 127.0.0.1）系统解析会卡很久，
            // 这里限时；超时就走下面的已知门户地址，保证登录不被拖死。
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(token);
            cts.CancelAfter(TimeSpan.FromSeconds(3));
            var resolved = await Dns.GetHostAddressesAsync(host, cts.Token).ConfigureAwait(false);
            result.AddRange(resolved
                .Where(a => a.AddressFamily == AddressFamily.InterNetwork && IsUsable(a)));
        }
        catch (Exception ex) when (ex is SocketException or OperationCanceledException)
        {
            Log.Write($"portal dns failed for {host}: {ex.Message}");
        }

        if (host.Equals(PortalHost, StringComparison.OrdinalIgnoreCase))
        {
            // 代理/TUN 的 fake-ip 段或校园网 DNS 故障时，解析结果不可用；
            // 校园网内网地址优先，其余可用地址次之，已知门户地址始终兜底。
            var campus = result.Where(IsCampusAddress).ToList();
            var others = result.Where(a => !IsCampusAddress(a)).ToList();
            result.Clear();
            result.AddRange(campus);
            result.AddRange(others);

            foreach (var fallback in FallbackPortalIps.Select(IPAddress.Parse))
            {
                if (!result.Contains(fallback))
                {
                    result.Add(fallback);
                }
            }
        }

        return result;
    }

    /// <summary>校园网内网段（10.0.0.0/8），门户与自服务都在这里。</summary>
    private static bool IsCampusAddress(IPAddress address)
        => address.GetAddressBytes() is { Length: 4 } b && b[0] == 10;

    private static bool IsUsable(IPAddress address)
    {
        var bytes = address.GetAddressBytes();
        if (bytes.Length != 4)
        {
            return false;
        }

        // 198.18.0.0/15 是 Clash/FlClash 的 fake-ip 段，连上去只会拿到代理占位响应。
        if (bytes[0] == 198 && (bytes[1] == 18 || bytes[1] == 19))
        {
            return false;
        }

        // 0.0.0.0、回环、组播与保留段。
        return bytes[0] != 0 && bytes[0] != 127 && bytes[0] < 224;
    }

    public int Port => _port;

    /// <summary>最近一次在线检查的补充说明（例如本机 IP 被别的设备占用）。</summary>
    public string LastOnlineNote => _lastOnlineNote;

    private string ConfigUrl => $"https://p.njupt.edu.cn:{_port}/eportal/portal/page/loadConfig";
    private string LoginUrl => $"https://p.njupt.edu.cn:{_port}/eportal/portal/login";
    private string LogoutUrl => $"https://p.njupt.edu.cn:{_port}/eportal/portal/logout";
    private string OnlineUrl => $"https://p.njupt.edu.cn:{_port}/eportal/portal/online_list";
    private string SelfUrl => $"https://p.njupt.edu.cn:{_port}/eportal/portal/self";

    /// <summary>
    /// 门户部分响应带空的 charset，HttpClient 的 GetStringAsync 会直接抛异常，
    /// 这里按字节读取后自行解码。
    /// </summary>
    private async Task<string> GetTextAsync(string url, CancellationToken token)
    {
        using var response = await _http
            .GetAsync(url, HttpCompletionOption.ResponseHeadersRead, token)
            .ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        var bytes = await response.Content.ReadAsByteArrayAsync(token).ConfigureAwait(false);
        return Decode(bytes, response.Content.Headers.ContentType?.CharSet);
    }

    /// <summary>
    /// 取 eportal 的 JSONP 响应。端口可能在运行期间失效（例如 804 变成 403 落地页），
    /// 拿到 HTML 时重新探测端口并重试一次，避免直接抛“响应格式异常”。
    /// </summary>
    private async Task<string> GetApiTextAsync(Func<string> urlFactory, CancellationToken token)
    {
        var text = await GetTextAsync(urlFactory(), token).ConfigureAwait(false);
        if (LooksLikePortalJson(text))
        {
            return text;
        }

        Log.Write($"portal port {_port} returned non-json: {Truncate(text.Trim(), 120)}");
        _port = 0;
        await EnsurePortAsync(token).ConfigureAwait(false);
        return await GetTextAsync(urlFactory(), token).ConfigureAwait(false);
    }

    private static string Decode(byte[] bytes, string? charset)
    {
        try
        {
            if (!string.IsNullOrWhiteSpace(charset))
            {
                var encoding = Encoding.GetEncoding(charset.Trim('"', '\'', ' '));
                return encoding.GetString(bytes);
            }
        }
        catch (ArgumentException)
        {
            // charset 非法，回退 UTF-8
        }

        return Encoding.UTF8.GetString(bytes);
    }

    // ===== 对外操作 =====

    public async Task<PortalSessionInfo?> GetOnlineAsync(CancellationToken token = default)
    {
        _lastOnlineNote = "";
        _onlineUnknown = false;
        await EnsurePortAsync(token).ConfigureAwait(false);
        var page = await GetPortalPageAsync(token).ConfigureAwait(false);
        var terminal = ParseTerminal(page);

        var query = new Dictionary<string, string>
        {
            ["callback"] = "dr1002",
            ["user_account"] = "",
            ["user_password"] = "",
            ["wlan_user_mac"] = "000000000000",
            ["wlan_user_ip"] = IpToInt(terminal.Ip).ToString(CultureInfo.InvariantCulture),
            ["curr_user_ip"] = "",
            ["jsVersion"] = JsVersion,
            ["v"] = RandomNumber(500, 10500).ToString(CultureInfo.InvariantCulture),
            ["lang"] = "zh",
        };

        string text;
        try
        {
            text = await GetApiTextAsync(() => BuildUrl(OnlineUrl, query), token).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            Log.Write($"online_list failed: {ex.GetType().Name}: {ex.Message}");
            return null;
        }

        var payload = ParseJsonp(text);
        Log.Write($"online_list port={_port} ip={terminal.Ip} result={payload.GetRawText()[..Math.Min(160, payload.GetRawText().Length)]}");

        if (!TryGet(payload, out var result) || result != "1")
        {
            return null;
        }

        if (!payload.TryGetProperty("list", out var list) ||
            list.ValueKind != JsonValueKind.Array ||
            list.GetArrayLength() == 0)
        {
            return null;
        }

        // online_list 会忽略 wlan_user_ip 参数，返回该账号下所有在线终端。
        // 直接取 list[0] 会把别的设备（手机/平板）当成本机，注销时就会误伤。
        var localMac = ResolveLocalMac(terminal.Ip);
        if (localMac.Length != 12)
        {
            // 拿不到本机 MAC 时无法排除“同一 IP 属于别的设备”的情况。
            // 注销是破坏性操作，这里宁可判定为无法确认，也不去猜 list[0]。
            _lastOnlineNote = $"无法确认 ip {terminal.Ip} 的在线会话是否属于本机（未读到本机 MAC）";
            _onlineUnknown = true;
            Log.Write($"online_list skipped: local mac unknown for ip={terminal.Ip} " +
                      $"count={list.GetArrayLength()}");
            return null;
        }

        var first = SelectOwnSession(list, terminal.Ip, localMac);
        if (first is null)
        {
            _lastOnlineNote = $"ip {terminal.Ip} 的在线会话不属于本机（本机 MAC {localMac}）";
            Log.Write($"online_list has no session for this device ip={terminal.Ip} " +
                      $"mac={localMac} count={list.GetArrayLength()}");
            return null;
        }

        return new PortalSessionInfo
        {
            Ip = Str(first.Value, "online_ip") is { Length: > 0 } onlineIp ? onlineIp : terminal.Ip,
            Account = Str(first.Value, "user_account"),
            Mac = Str(first.Value, "online_mac") is { Length: > 0 } mac ? mac : "000000000000",
            Vlan = terminal.Vlan,
            Session = Str(first.Value, "online_session"),
        };
    }

    /// <summary>
    /// 在账号的在线列表里找出本机那一条：先按 IP 精确匹配；
    /// IP 因 DHCP 漂移时再退回按本机网卡 MAC 匹配。
    /// 两边 MAC 都已知且不一致时，说明这个 IP 已经被别的设备占用，必须跳过。
    /// </summary>
    private static JsonElement? SelectOwnSession(JsonElement list, string localIp, string localMac)
    {
        JsonElement? macMatch = null;
        foreach (var item in list.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
            {
                continue;
            }

            var itemMac = NormalizeMac(Str(item, "online_mac"));
            // 会话 MAC 缺失或与本机不符，都不能认定为本机。
            var macConfirms = itemMac.Length == 12 && itemMac == localMac;

            if (localIp.Length > 0 && Str(item, "online_ip") == localIp)
            {
                if (macConfirms)
                {
                    return item;
                }

                Log.Write($"online_list ip={localIp} belongs to mac={itemMac} (local {localMac}), skip");
                continue;
            }

            if (macMatch is null && itemMac == localMac)
            {
                macMatch = item;
            }
        }

        return macMatch;
    }

    private static string NormalizeMac(string value)
        => Regex.Replace(value ?? "", "[^0-9A-Fa-f]", "").ToUpperInvariant();

    /// <summary>
    /// 取本机持有 <paramref name="localIp"/> 的网卡 MAC（12 位十六进制，大写）。
    /// 拿不到时返回空串，调用方会退化为只按 IP 匹配。
    /// </summary>
    private static string ResolveLocalMac(string localIp)
    {
        if (!IsIPv4(localIp))
        {
            return "";
        }

        try
        {
            foreach (var nic in NetworkInterface.GetAllNetworkInterfaces())
            {
                if (nic.NetworkInterfaceType == NetworkInterfaceType.Loopback)
                {
                    continue;
                }

                var hasIp = nic.GetIPProperties().UnicastAddresses
                    .Any(a => a.Address.Equals(IPAddress.Parse(localIp)));
                if (!hasIp)
                {
                    continue;
                }

                var mac = NormalizeMac(nic.GetPhysicalAddress().ToString());
                return mac.Length == 12 ? mac : "";
            }
        }
        catch (Exception ex) when (ex is NetworkInformationException or PlatformNotSupportedException)
        {
            Log.Write($"local mac lookup failed: {ex.Message}");
        }

        return "";
    }

    public async Task<bool> IsOnlineAsync(CancellationToken token = default)
        => await GetOnlineAsync(token).ConfigureAwait(false) is not null;

    public sealed class LoginRequest
    {
        public string Url { get; init; } = "";
        public PortalTerminal Terminal { get; init; } = new();
        public JsonElement Config { get; init; }
        public bool Encrypted { get; init; }
    }

    /// <summary>
    /// 执行门户首页 → a41.js → loadConfig，构造登录请求但不提交。
    /// 用于诊断（loadConfig 是最容易随校方调整而失效的一步）。
    /// </summary>
    public async Task<LoginRequest> BuildLoginRequestAsync(
        string account, string password, CancellationToken token = default)
    {
        await EnsurePortAsync(token).ConfigureAwait(false);

        var page = await GetPortalPageAsync(token).ConfigureAwait(false);
        var terminal = ParseTerminal(page);
        if (!IsIPv4(terminal.Ip))
        {
            throw new PortalException("门户页面未提供有效的客户端 IP，请先连接校园网");
        }

        var encrypt = await ReadPageDataEncryptAsync(page, token).ConfigureAwait(false);

        var callback = "dr" + DateTime.Now.Ticks % 1_000_000_000;
        var configQuery = new Dictionary<string, string>
        {
            ["program_index"] = "",
            ["wlan_vlan_id"] = terminal.Vlan,
            ["wlan_user_ip"] = B64(terminal.Ip),
            ["wlan_user_ipv6"] = B64(terminal.Ipv6),
            ["wlan_user_ssid"] = "",
            ["wlan_user_areaid"] = "",
            ["wlan_ac_ip"] = B64(""),
            ["wlan_ap_mac"] = "000000000000",
            ["gw_id"] = "",
            ["page_index"] = "",
            ["callback"] = callback,
            ["jsVersion"] = JsVersion,
            ["v"] = RandomNumber(500, 10500).ToString(CultureInfo.InvariantCulture),
            ["lang"] = "zh",
        };

        string configText;
        try
        {
            configText = await GetApiTextAsync(() => BuildUrl(ConfigUrl, configQuery), token)
                .ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            throw new PortalException($"连接认证网关失败：{ex.Message}");
        }

        configText = configText.Trim();
        Log.Write($"loadConfig port={_port} body={Truncate(configText, 300)}");

        JsonElement configPayload;
        try
        {
            configPayload = ParseJsonp(configText);
        }
        catch (Exception)
        {
            throw new PortalException($"loadConfig 响应格式异常：{Truncate(configText, 200)}");
        }

        if (Str(configPayload, "code") == "0" ||
            !configPayload.TryGetProperty("data", out var config) ||
            config.ValueKind != JsonValueKind.Object)
        {
            throw new PortalException($"loadConfig 被拒绝：{Truncate(configText, 200)}");
        }

        var accountPrefix = Str(config, "account_prefix", "0") == "1" ? ",0," : "";
        var noFilter = Str(config, "no_filter_accandpwd", "0");
        var portalAccount = accountPrefix + account;
        var portalPassword = password;
        if (noFilter == "1")
        {
            portalAccount = B64(portalAccount);
            portalPassword = B64(portalPassword);
        }

        var fields = new List<KeyValuePair<string, string>>
        {
            new("login_method", Str(config, "login_method")),
            new("is_base64encode", noFilter),
            new("user_account", portalAccount),
            new("user_password", portalPassword),
            new("wlan_user_ip", terminal.Ip),
            new("wlan_user_ipv6", terminal.Ipv6),
            new("wlan_user_mac", terminal.Mac),
            new("wlan_vlan_id", terminal.Vlan),
            new("wlan_ac_ip", ""),
            new("wlan_ac_name", ""),
            new("authex_enable", ""),
            new("jsVersion", JsVersion),
            new("terminal_type", "1"),
            new("lang", "zh-cn"),
            new("user_agent", UserAgent),
            new("enable_r3", Str(config, "enable_r3", "0")),
            new("mac_type", "0"),
            new("rcn", Str(config, "rcn")),
            new("operate", "portal_login"),
            new("business_type", "1"),
            new("program_index", Str(config, "program_index")),
            new("page_index", Str(config, "page_index")),
            new("callback", callback),
        };

        if (encrypt)
        {
            var key = XorKey(terminal.Ip);
            fields = fields.Select(p => new KeyValuePair<string, string>(p.Key, XorHex(p.Value, key))).ToList();
            fields.Add(new KeyValuePair<string, string>("encrypt", "1"));
        }

        fields.Add(new KeyValuePair<string, string>("v", RandomNumber(500, 10500).ToString(CultureInfo.InvariantCulture)));
        fields.Add(new KeyValuePair<string, string>("lang", "zh"));

        return new LoginRequest
        {
            Url = BuildUrl(LoginUrl, fields),
            Terminal = terminal,
            Config = config.Clone(),
            Encrypted = encrypt,
        };
    }

    public async Task<(bool Ok, string Message)> LoginAsync(
        string account, string password, CancellationToken token = default)
    {
        var request = await BuildLoginRequestAsync(account, password, token).ConfigureAwait(false);

        string loginText;
        try
        {
            loginText = await GetTextAsync(request.Url, token).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            throw new PortalException($"提交登录失败：{ex.Message}");
        }

        loginText = loginText.Trim();
        Log.Write($"login port={_port} body={Truncate(loginText, 300)}");

        JsonElement loginPayload;
        try
        {
            loginPayload = ParseJsonp(loginText);
        }
        catch (Exception)
        {
            throw new PortalException($"登录响应格式异常：{Truncate(loginText, 300)}");
        }

        var code = Str(loginPayload, "result", "0");
        var msg = Str(loginPayload, "msg", "未知错误");
        var success = code == "1" || msg.Contains("AC999", StringComparison.OrdinalIgnoreCase)
            || msg.Contains("已在线", StringComparison.OrdinalIgnoreCase);
        return (success, success && code != "1" ? "当前账号已在线" : msg);
    }

    public async Task<(bool Ok, string Message)> LogoutAsync(
        string account, CancellationToken token = default)
    {
        await EnsurePortAsync(token).ConfigureAwait(false);

        var info = await GetOnlineAsync(token).ConfigureAwait(false);
        if (info is null)
        {
            Log.Write("logout skipped: no online session for this ip");
            if (_onlineUnknown)
            {
                return (false, LastOnlineNote);
            }

            return (true, string.IsNullOrEmpty(LastOnlineNote)
                ? "当前没有在线会话"
                : LastOnlineNote);
        }

        var selfResult = await SelfServiceOfflineAsync(account, info, token).ConfigureAwait(false);
        if (selfResult.Ok)
        {
            return selfResult;
        }
        Log.Write($"self-service logout unavailable: {selfResult.Message}");

        var callback = "dr" + DateTime.Now.Ticks % 1_000_000_000;
        var query = new Dictionary<string, string>
        {
            ["callback"] = callback,
            ["login_method"] = "1",
            ["user_account"] = "drcom",
            ["user_password"] = "123",
            ["ac_logout"] = "1",
            ["register_mode"] = "1",
            ["wlan_user_ip"] = info.Ip,
            ["wlan_user_ipv6"] = "",
            ["wlan_vlan_id"] = info.Vlan,
            ["wlan_user_mac"] = "000000000000",
            ["wlan_ac_ip"] = "",
            ["wlan_ac_name"] = "",
            ["jsVersion"] = JsVersion,
            ["v"] = RandomNumber(500, 10500).ToString(CultureInfo.InvariantCulture),
            ["lang"] = "zh",
        };

        var text = await GetTextAsync(BuildUrl(LogoutUrl, query), token).ConfigureAwait(false);
        text = text.Trim();
        Log.Write($"logout portal port={_port} body={Truncate(text, 300)}");

        var payload = TryParseJsonp(text);
        if (payload.HasValue && ResultCode(payload.Value) == "1")
        {
            return (true, Str(payload.Value, "msg", "注销成功"));
        }

        var fallback = await GetTextAsync(BuildUrl(LogoutUrl, new Dictionary<string, string>
            {
                ["callback"] = callback,
                ["jsVersion"] = JsVersion,
            }), token)
            .ConfigureAwait(false);
        fallback = fallback.Trim();
        Log.Write($"logout default port={_port} body={Truncate(fallback, 300)}");

        var payload2 = TryParseJsonp(fallback);
        if (payload2 is null)
        {
            throw new PortalException($"注销响应格式异常：{Truncate(fallback, 200)}");
        }

        var code = ResultCode(payload2.Value);
        return (code == "1", Str(payload2.Value, "msg", "未知错误"));
    }

    // ===== 内部实现 =====

    private async Task EnsurePortAsync(CancellationToken token)
    {
        if (_port != 0)
        {
            return;
        }

        // 只做 TCP 探测是不够的：某个端口可能 TCP 通、但 HTTP 返回 403/HTML 落地页，
        // 那样后续 loadConfig 会拿到 HTML 而不是 JSONP，报“响应格式异常”。
        // 这里必须发一次真实请求，确认能拿到 Dr.COM 的 JSONP。
        foreach (var port in CandidatePorts)
        {
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(token);
                cts.CancelAfter(TimeSpan.FromSeconds(6));
                var probeUrl = $"https://{PortalHost}:{port}/eportal/portal/page/loadConfig";
                using var response = await _http
                    .GetAsync(probeUrl, HttpCompletionOption.ResponseHeadersRead, cts.Token)
                    .ConfigureAwait(false);
                if (!response.IsSuccessStatusCode)
                {
                    Log.Write($"portal port {port} http {(int)response.StatusCode}");
                    continue;
                }

                var bytes = await response.Content.ReadAsByteArrayAsync(cts.Token).ConfigureAwait(false);
                var body = Decode(bytes, response.Content.Headers.ContentType?.CharSet).Trim();
                if (!LooksLikePortalJson(body))
                {
                    Log.Write($"portal port {port} not portal json: {Truncate(body, 80)}");
                    continue;
                }

                _port = port;
                Log.Write($"portal api port={port} verified");
                return;
            }
            catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException
                                           or OperationCanceledException or SocketException)
            {
                // 尝试下一个端口
            }
        }

        _port = CandidatePorts[0];
        Log.Write("portal api port probe failed, fallback to 804");
    }

    private static bool LooksLikePortalJson(string body)
    {
        if (body.Length == 0)
        {
            return false;
        }

        if (body.StartsWith('{'))
        {
            return true;
        }

        return Regex.IsMatch(body,
            @"^(?:/\*\*/\s*)?[A-Za-z_$][\w$.]*\s*\(\s*\{",
            RegexOptions.Singleline);
    }

    private async Task<string> GetPortalPageAsync(CancellationToken token)
    {
        try
        {
            return await GetTextAsync(PortalUrl, token).ConfigureAwait(false);
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            throw new PortalException($"访问校园网门户失败：{ex.Message}");
        }
    }

    private async Task<bool> ReadPageDataEncryptAsync(string page, CancellationToken token)
    {
        var scriptUrl = "";
        foreach (Match m in Regex.Matches(page, "<script\\b[^>]*\\bsrc\\s*=\\s*(['\"])(.*?)\\1",
                     RegexOptions.IgnoreCase | RegexOptions.Singleline))
        {
            var src = WebUtility.HtmlDecode(m.Groups[2].Value.Trim());
            if (Regex.IsMatch(src, @"(?:^|/)a41\.js(?:[?#]|$)", RegexOptions.IgnoreCase))
            {
                scriptUrl = new Uri(new Uri(PortalUrl), src).ToString();
                break;
            }
        }

        if (string.IsNullOrEmpty(scriptUrl))
        {
            return false;
        }

        try
        {
            var js = await GetTextAsync(scriptUrl, token).ConfigureAwait(false);
            var m = Regex.Match(js, "\\bpage_data_encrypt\\s*=\\s*(['\"])([01])\\1");
            return m.Success && m.Groups[2].Value == "1";
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException)
        {
            Log.Write($"a41.js failed: {ex.Message}");
            return false;
        }
    }

    private async Task<(bool Ok, string Message)> SelfServiceOfflineAsync(
        string account, PortalSessionInfo info, CancellationToken token)
    {
        if (!IsIPv4(info.Ip))
        {
            return (false, "无法识别本机 IP");
        }

        var ipInt = IpToInt(info.Ip).ToString(CultureInfo.InvariantCulture);
        var mac = string.IsNullOrEmpty(info.Mac) ? "000000000000" : info.Mac.ToUpperInvariant();
        var query = new Dictionary<string, string>
        {
            ["callback"] = "dr" + DateTime.Now.Ticks % 1_000_000_000,
            ["self_type"] = "1",
            ["user_account"] = string.IsNullOrEmpty(account) ? info.Account : account,
            ["user_password"] = "",
            ["wlan_user_mac"] = mac,
            ["wlan_user_ip"] = ipInt,
            ["jsVersion"] = JsVersion,
            ["v"] = RandomNumber(500, 10500).ToString(CultureInfo.InvariantCulture),
            ["lang"] = "zh",
        };

        var submitted = false;
        try
        {
            var text = await GetTextAsync(BuildUrl(SelfUrl, query), token).ConfigureAwait(false);
            var payload = ParseJsonp(text);
            var authUrl = Str(payload, "self_auth_url");
            if (ResultCode(payload) != "1" || string.IsNullOrEmpty(authUrl))
            {
                return (false, Str(payload, "msg", "自服务入口获取失败"));
            }

            using var response = await _http.GetAsync(authUrl, token).ConfigureAwait(false);
            var finalUri = response.RequestMessage?.RequestUri;
            if (finalUri is null)
            {
                return (false, "自服务登录跳转失败");
            }

            var baseUri = $"{finalUri.Scheme}://{finalUri.Authority}";
            var listUrl = $"{baseUri}/Self/dashboard/getOnlineList" +
                $"?order=asc&_={DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()}";
            var listText = await SendSelfAsync(listUrl, baseUri, token).ConfigureAwait(false);
            var sessionId = FindSessionId(listText, info.Ip, info.Mac);
            if (sessionId is null)
            {
                // 自服务在线列表的字段结构没有实测过，找不到会话不代表本机已离线。
                // 这里返回 false，让 LogoutAsync 继续走门户按 IP 注销的兜底路径。
                Log.Write($"self-service list has no session for this device ip={info.Ip} " +
                          $"mac={info.Mac}");
                return (false, "自服务列表未找到本机会话");
            }

            submitted = true;
            var offlineUrl = $"{baseUri}/Self/dashboard/tooffline?sessionid={Uri.EscapeDataString(sessionId)}";
            var offlineText = await SendSelfAsync(offlineUrl, baseUri, token).ConfigureAwait(false);
            using var doc = JsonDocument.Parse(offlineText);
            var success = doc.RootElement.TryGetProperty("success", out var s) &&
                s.ValueKind == JsonValueKind.True;
            if (success)
            {
                Log.Write($"self-service offline ok ip={info.Ip} sid={sessionId}");
                return (true, "已通过自服务注销");
            }

            return (false, "自服务注销失败");
        }
        catch (Exception ex) when (ex is HttpRequestException or TaskCanceledException or JsonException)
        {
            if (submitted)
            {
                Log.Write($"self-service offline submitted, response lost: {ex.Message}");
                return (true, "已提交注销");
            }
            Log.Write($"self-service offline failed: {ex.GetType().Name}: {ex.Message}");
            return (false, $"自服务注销失败：{ex.Message}");
        }
    }

    private async Task<string> SendSelfAsync(string url, string baseUri, CancellationToken token)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, url);
        request.Headers.TryAddWithoutValidation("Referer", $"{baseUri}/Self/dashboard");
        request.Headers.TryAddWithoutValidation("X-Requested-With", "XMLHttpRequest");
        using var response = await _http.SendAsync(request, token).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        var bytes = await response.Content.ReadAsByteArrayAsync(token).ConfigureAwait(false);
        return Decode(bytes, response.Content.Headers.ContentType?.CharSet);
    }

    /// <summary>
    /// 在自服务在线列表里定位本机会话。只按 IP 匹配会在 DHCP 复用同一地址时
    /// 命中别的设备，所以 IP 命中后还要用 MAC 复核（MAC 未知时才退化为只看 IP）。
    /// </summary>
    private static string? FindSessionId(string json, string ip, string mac)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.ValueKind == JsonValueKind.Object)
            {
                if (root.TryGetProperty("rows", out var rows))
                {
                    root = rows;
                }
                else if (root.TryGetProperty("data", out var data))
                {
                    root = data;
                }
            }

            if (root.ValueKind != JsonValueKind.Array)
            {
                return null;
            }

            var localMac = NormalizeMac(mac);
            foreach (var item in root.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Object || Str(item, "ip") != ip)
                {
                    continue;
                }

                var itemMac = NormalizeMac(Str(item, "mac"));
                if (localMac.Length == 12 && itemMac.Length == 12 && itemMac != localMac)
                {
                    Log.Write($"self list ip={ip} mac mismatch {itemMac}!={localMac}, skip");
                    continue;
                }

                var id = Str(item, "sessionId");
                if (string.IsNullOrEmpty(id))
                {
                    id = Str(item, "sessionid");
                }
                return string.IsNullOrEmpty(id) ? null : id;
            }
        }
        catch (JsonException ex)
        {
            Log.Write($"self list parse failed: {ex.Message}");
        }

        return null;
    }

    private static PortalTerminal ParseTerminal(string page)
    {
        var mac = Regex.Replace(ReadJsString(page, "ss4", "000000000000"), "[:-]", "");
        return new PortalTerminal
        {
            Ip = ReadJsString(page, "ss5") is { Length: > 0 } ss5 ? ss5 : ReadJsString(page, "v46ip"),
            Ipv6 = ReadJsString(page, "myv6ip"),
            Mac = string.IsNullOrEmpty(mac) ? "000000000000" : mac,
            Vlan = ReadJsString(page, "vlanid", "0") is { Length: > 0 } v ? v : "0",
        };
    }

    private static string ReadJsString(string page, string name, string fallback = "")
    {
        var m = Regex.Match(page, $@"\b{Regex.Escape(name)}\s*=\s*(['""])(.*?)\1", RegexOptions.Singleline);
        return m.Success ? m.Groups[2].Value.Trim() : fallback;
    }

    /// <summary>解析 Dr.COM 的 JSON / JSONP；回调名以服务端实际返回为准。</summary>
    public static JsonElement ParseJsonp(string text)
    {
        var body = text.Trim().TrimStart('\uFEFF');
        if (body.StartsWith('{'))
        {
            using var direct = JsonDocument.Parse(body);
            return direct.RootElement.Clone();
        }

        var m = Regex.Match(body,
            @"^(?:/\*\*/\s*)?[A-Za-z_$][\w$.]*\s*\((.*)\)\s*;?\s*$",
            RegexOptions.Singleline);
        if (!m.Success)
        {
            throw new PortalException("响应不是 JSON 或 JSONP");
        }

        using var doc = JsonDocument.Parse(m.Groups[1].Value);
        return doc.RootElement.Clone();
    }

    private static JsonElement? TryParseJsonp(string text)
    {
        try
        {
            return ParseJsonp(text);
        }
        catch
        {
            return null;
        }
    }

    private static string ResultCode(JsonElement element)
    {
        if (element.TryGetProperty("result", out var result))
        {
            return result.ValueKind == JsonValueKind.Number
                ? result.GetRawText()
                : result.GetString() ?? "0";
        }

        if (element.TryGetProperty("code", out var code))
        {
            return code.ValueKind == JsonValueKind.Number
                ? code.GetRawText()
                : code.GetString() ?? "0";
        }

        return "0";
    }

    private static bool TryGet(JsonElement element, out string value)
    {
        value = "";
        if (!element.TryGetProperty("result", out var result))
        {
            return false;
        }

        value = result.ValueKind == JsonValueKind.Number ? result.GetRawText() : result.GetString() ?? "";
        return true;
    }

    private static string Str(JsonElement element, string name, string fallback = "")
    {
        if (!element.TryGetProperty(name, out var value))
        {
            return fallback;
        }

        return value.ValueKind switch
        {
            JsonValueKind.String => value.GetString() ?? fallback,
            JsonValueKind.Number => value.GetRawText(),
            JsonValueKind.True => "true",
            JsonValueKind.False => "false",
            JsonValueKind.Null => fallback,
            _ => value.GetRawText(),
        };
    }

    private static string BuildUrl(string baseUrl, IEnumerable<KeyValuePair<string, string>> query)
    {
        var sb = new StringBuilder(baseUrl);
        sb.Append('?');
        var first = true;
        foreach (var (key, value) in query)
        {
            if (!first)
            {
                sb.Append('&');
            }
            first = false;
            sb.Append(Uri.EscapeDataString(key)).Append('=').Append(Uri.EscapeDataString(value ?? ""));
        }
        return sb.ToString();
    }

    private static long IpToInt(string ip)
    {
        if (!IPAddress.TryParse(ip, out var address) || address.AddressFamily != AddressFamily.InterNetwork)
        {
            throw new PortalException($"无法识别本机 IP：{ip}");
        }

        var bytes = address.GetAddressBytes();
        return ((long)bytes[0] << 24) | ((long)bytes[1] << 16) | ((long)bytes[2] << 8) | bytes[3];
    }

    private static bool IsIPv4(string ip)
        => IPAddress.TryParse(ip, out var address) && address.AddressFamily == AddressFamily.InterNetwork;

    private static int XorKey(string clientIp)
    {
        var key = 0;
        foreach (var ch in clientIp)
        {
            key ^= ch;
        }
        return key;
    }

    private static string XorHex(string value, int key)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "";
        }

        var sb = new StringBuilder(value.Length * 2);
        foreach (var ch in value)
        {
            sb.Append((ch ^ key).ToString("x2", CultureInfo.InvariantCulture));
        }
        return sb.ToString();
    }

    private static string B64(string value)
        => Convert.ToBase64String(Encoding.UTF8.GetBytes(value ?? ""));

    private static int RandomNumber(int min, int max)
    {
        lock (RngGate)
        {
            return Rng.Next(min, max);
        }
    }

    private static string Truncate(string value, int length)
        => value.Length <= length ? value : value[..length];

    public void Dispose() => _http.Dispose();
}
