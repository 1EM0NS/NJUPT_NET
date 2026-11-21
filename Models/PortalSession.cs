namespace NjuptNet.Models;

public sealed class PortalTerminal
{
    public string Ip { get; set; } = "";
    public string Ipv6 { get; set; } = "";
    public string Mac { get; set; } = "000000000000";
    public string Vlan { get; set; } = "0";
}

public sealed class PortalSessionInfo
{
    public string Ip { get; set; } = "";
    public string Account { get; set; } = "";
    public string Mac { get; set; } = "000000000000";
    public string Vlan { get; set; } = "0";
    public string Session { get; set; } = "";
}
