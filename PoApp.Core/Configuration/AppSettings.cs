namespace PoApp.Core.Configuration;

public sealed class AppSettings
{
    public PathSettings Paths { get; set; } = new();
}

public sealed class PathSettings
{
    public string PdfSourceRoot { get; set; } = string.Empty;
    public List<string> PdfFiles { get; set; } = new();
}
