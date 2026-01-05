using System;
using System.IO;
using System.Text.Json;
using PoApp.Core.Models;

namespace PoApp.Desktop.Services;

public static class JsonMaterialRepository
{
    public static MaterialDataset LoadFromRepoDataFolder()
    {
        // We run from: ...\PoApp.Desktop\bin\Debug\net8.0-windows\
        // Find repo root by walking up until we find /data/materials.json
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            var candidate = Path.Combine(dir.FullName, "data", "materials.json");
            if (File.Exists(candidate))
                return Load(candidate);

            dir = dir.Parent;
        }

        throw new FileNotFoundException("Could not find data/materials.json by walking up from AppContext.BaseDirectory.");
    }

    private static MaterialDataset Load(string path)
    {
        var json = File.ReadAllText(path);

        var options = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        };

        var dataset = JsonSerializer.Deserialize<MaterialDataset>(json, options);
        if (dataset is null || dataset.Materials is null)
            throw new InvalidOperationException($"Invalid dataset JSON at: {path}");

        return dataset;
    }
}