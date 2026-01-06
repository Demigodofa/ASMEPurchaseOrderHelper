using System;
using Microsoft.Extensions.Configuration;
using PoApp.Core.Configuration;

namespace PoApp.Desktop.Services;

public static class AppSettingsProvider
{
    public static AppSettings Load()
    {
        var config = new ConfigurationBuilder()
            .SetBasePath(AppContext.BaseDirectory)
            .AddJsonFile("appsettings.json", optional: true, reloadOnChange: false)
            .AddJsonFile("appsettings.Development.json", optional: true, reloadOnChange: false)
            .Build();

        var settings = config.Get<AppSettings>() ?? new AppSettings();

        if (string.IsNullOrWhiteSpace(settings.Paths.PdfSourceRoot))
        {
            settings.Paths.PdfSourceRoot = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        }

        return settings;
    }
}
