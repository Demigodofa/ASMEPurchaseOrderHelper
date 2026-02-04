using System.IO;
using PoApp.Core.Models;
using PoApp.Core.Services;

namespace PoApp.Desktop.Services;

public static class NormalizedAsmeRepository
{
    public static AsmeNormalizedDataset LoadFromRepoDataFolder()
    {
        var dataPath = DataFileLocator.FindDataFile("normalized_asme_partA_specs.jsonl");
        if (string.IsNullOrWhiteSpace(dataPath))
            throw new FileNotFoundException("Could not locate data/normalized_asme_partA_specs.jsonl from application base path.");

        var schemaPath = DataFileLocator.FindDataFile("normalized_asme_po_schema.json");
        if (string.IsNullOrWhiteSpace(schemaPath))
            throw new FileNotFoundException("Could not locate data/normalized_asme_po_schema.json from application base path.");

        var loader = new NormalizedAsmeDataLoader();
        return loader.Load(dataPath, schemaPath);
    }
}
