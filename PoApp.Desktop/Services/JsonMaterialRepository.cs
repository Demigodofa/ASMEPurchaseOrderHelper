using System.IO;
using PoApp.Core.Models;
using PoApp.Core.Services;

namespace PoApp.Desktop.Services;

public static class NormalizedAsmeRepository
{
    public static AsmeNormalizedDataset LoadFromRepoDataFolder()
    {
        var dataPath = DataFileLocator.FindDataFile("asme_po_data_imperial_v4.jsonl");
        if (string.IsNullOrWhiteSpace(dataPath))
            throw new FileNotFoundException("Could not locate data/asme_po_data_imperial_v4.jsonl from application base path.");

        var schemaPath = DataFileLocator.FindDataFile("asme_po_schema_imperial_v4.json");
        if (string.IsNullOrWhiteSpace(schemaPath))
            throw new FileNotFoundException("Could not locate data/asme_po_schema_imperial_v4.json from application base path.");

        var loader = new NormalizedAsmeDataLoader();
        return loader.Load(dataPath, schemaPath);
    }
}
