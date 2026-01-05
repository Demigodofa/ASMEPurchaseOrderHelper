using System;
using System.IO;
using System.Windows;
using System.Windows.Threading;

namespace PoApp.Desktop;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        // UI thread exceptions
        DispatcherUnhandledException += App_DispatcherUnhandledException;

        // Non-UI exceptions
        AppDomain.CurrentDomain.UnhandledException += CurrentDomain_UnhandledException;

        base.OnStartup(e);
    }

    private void App_DispatcherUnhandledException(object sender, DispatcherUnhandledExceptionEventArgs e)
    {
        Log(e.Exception);
        MessageBox.Show(e.Exception.ToString(), "Unhandled exception", MessageBoxButton.OK, MessageBoxImage.Error);
        e.Handled = true;
        Shutdown(-1);
    }

    private void CurrentDomain_UnhandledException(object? sender, UnhandledExceptionEventArgs e)
    {
        var ex = e.ExceptionObject as Exception
                 ?? new Exception(e.ExceptionObject?.ToString() ?? "Unknown exception");

        Log(ex);
    }

    private static void Log(Exception ex)
    {
        try
        {
            // Walk up until we find a repo-local /data folder
            var dir = new DirectoryInfo(AppContext.BaseDirectory);
            while (dir != null)
            {
                var dataDir = Path.Combine(dir.FullName, "data");
                if (Directory.Exists(dataDir))
                {
                    File.WriteAllText(Path.Combine(dataDir, "startup-error.txt"), ex.ToString());
                    return;
                }

                dir = dir.Parent;
            }

            // Fallback: log next to exe
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory, "startup-error.txt"), ex.ToString());
        }
        catch
        {
 

















           // no-op
        }
    }
}