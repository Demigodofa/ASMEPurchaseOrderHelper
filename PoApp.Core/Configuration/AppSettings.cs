namespace PoApp.Core.Configuration;

public sealed class AppSettings
{
    public PathSettings Paths { get; set; } = new();
    public IngestSettings Ingest { get; set; } = new();
}

public sealed class PathSettings
{
    public string PdfSourceRoot { get; set; } = string.Empty;
    public List<string> PdfFiles { get; set; } = new();
}

public sealed class IngestSettings
{
    public List<string> ExpectedSpecs { get; set; } = new();
    public bool ScanMissingSpecs { get; set; }
}
