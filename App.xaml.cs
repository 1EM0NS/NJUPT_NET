using System.Windows;
using System.Windows.Threading;
using NjuptNet.Services;

namespace NjuptNet;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        DispatcherUnhandledException += OnDispatcherUnhandledException;
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            Log.Write($"unhandled: {args.ExceptionObject}");
        base.OnStartup(e);
    }

    private static void OnDispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        Log.Write($"dispatcher unhandled: {e.Exception}");
        MessageBox.Show(e.Exception.Message, "NJUPT 校园网", MessageBoxButton.OK, MessageBoxImage.Error);
        e.Handled = true;
    }
}
