namespace NjuptNet.Models;

public sealed class AppConfig
{
    public string Account { get; set; } = "";

    public string Suffix { get; set; } = "";

    public string Password { get; set; } = "";

    public bool AutoLogin { get; set; }

    public string Carrier
    {
        get => Suffix switch
        {
            "cmcc" => "中国移动",
            "njxy" or "dx" => "中国电信",
            "lt" => "中国联通",
            _ => "校园网",
        };
        set => Suffix = value switch
        {
            "中国移动" => "cmcc",
            "中国电信" => "njxy",
            "中国联通" => "lt",
            _ => "",
        };
    }

    public string FullAccount => string.IsNullOrEmpty(Suffix) ? Account : $"{Account}@{Suffix}";

    public AppConfig Clone() => new()
    {
        Account = Account,
        Suffix = Suffix,
        Password = Password,
        AutoLogin = AutoLogin,
    };
}
