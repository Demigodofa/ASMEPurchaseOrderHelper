using System;
using System.IO;

namespace PoApp.Desktop.Services;

public static class DataFileLocator
{
    public static string? FindDataFile(string fileName)
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "data", fileName);
            if (File.Exists(candidate))
                return candidate;

            dir = dir.Parent;
        }

        return null;
    }
}
