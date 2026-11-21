using System.IO;
using System.Text;

namespace NjuptNet.Services;

public static class Log
{
    private static readonly object Gate = new();

    public static string Directory
    {
        get
        {
            var dir = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "NJUPT_NET");
            System.IO.Directory.CreateDirectory(dir);
            return dir;
        }
    }

    public static string FilePath => Path.Combine(Directory, "njupt_net.log");

    public static void Write(string message)
    {
        try
        {
            lock (Gate)
            {
                File.AppendAllText(
                    FilePath,
                    $"{DateTime.Now:yyyy-MM-dd HH:mm:ss} {message}{Environment.NewLine}",
                    Encoding.UTF8);
            }
        }
        catch
        {
            // 日志失败不能影响主流程
        }
    }
}
