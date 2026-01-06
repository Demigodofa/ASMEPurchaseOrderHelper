using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Configuration;
using PoApp.Core.Configuration;
using PoApp.Core.Models;
using UglyToad.PdfPig;
using UglyToad.PdfPig.Content;

var settings = LoadSettings();
var pdfRoot = ResolvePdfRoot(settings);

if (!Directory.Exists(pdfRoot))
{
    Console.WriteLine($"PDF source folder not found: {pdfRoot}");
    return;
}

var pdfFiles = Directory.EnumerateFiles(pdfRoot, "*.pdf", SearchOption.TopDirectoryOnly)
    .Where(path => !Path.GetFileName(path).Contains("PART B", StringComparison.OrdinalIgnoreCase))
    .ToList();

if (pdfFiles.Count == 0)
{
    Console.WriteLine($"No PDFs found in: {pdfRoot}");
    return;
}

Console.WriteLine($"Scanning {pdfFiles.Count} PDF(s) in: {pdfRoot}");

var results = new Dictionary<string, MaterialSpecRecord>(StringComparer.OrdinalIgnoreCase);

foreach (var pdfPath in pdfFiles)
{
    Console.WriteLine($"- {Path.GetFileName(pdfPath)}");

    using var document = PdfDocument.Open(pdfPath);
    foreach (var page in document.GetPages())
    {
        if (!TryExtractSpecFromPage(page, out var asmeSpec, out var astmSpec, out var astmYear))
            continue;

        if (!results.ContainsKey(asmeSpec))
        {
            results[asmeSpec] = new MaterialSpecRecord(
                AsmeSpec: asmeSpec,
                AstmSpec: astmSpec,
                AstmYear: astmYear,
                Grades: Array.Empty<string>(),
                OrderingNotes: Array.Empty<string>());
        }
    }
}

var dataDir = ResolveDataDirectory();
Directory.CreateDirectory(dataDir);
var outputPath = Path.Combine(dataDir, "materials.json");

var dataset = new MaterialDataset(results.Values.OrderBy(r => r.AsmeSpec).ToList());
var json = JsonSerializer.Serialize(dataset, new JsonSerializerOptions { WriteIndented = true });
File.WriteAllText(outputPath, json);

Console.WriteLine($"Extracted {results.Count} material specs.");
Console.WriteLine($"Wrote dataset to: {outputPath}");

static AppSettings LoadSettings()
{
    var config = new ConfigurationBuilder()
        .SetBasePath(AppContext.BaseDirectory)
        .AddJsonFile("appsettings.json", optional: true, reloadOnChange: false)
        .AddJsonFile("appsettings.Development.json", optional: true, reloadOnChange: false)
        .Build();

    return config.Get<AppSettings>() ?? new AppSettings();
}

static string ResolvePdfRoot(AppSettings settings)
{
    var configured = settings.Paths.PdfSourceRoot;
    if (!string.IsNullOrWhiteSpace(configured))
        return configured;

    return Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
}

static string ResolveDataDirectory()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir is not null)
    {
        var dataDir = Path.Combine(dir.FullName, "data");
        if (Directory.Exists(dataDir))
            return dataDir;

        if (File.Exists(Path.Combine(dir.FullName, "PoApp.slnx")))
            return dataDir;

        dir = dir.Parent;
    }

    return Path.Combine(AppContext.BaseDirectory, "data");
}

static bool TryExtractSpecFromPage(Page page, out string asmeSpec, out string astmSpec, out string astmYear)
{
    asmeSpec = string.Empty;
    astmSpec = string.Empty;
    astmYear = string.Empty;

    var text = page.Text;
    if (string.IsNullOrWhiteSpace(text))
        return false;

    if (!HasTopRightSaHeader(page))
        return false;

    var asmeMatch = Regex.Match(text, @"\bSA-\d+[A-Z]?\b", RegexOptions.IgnoreCase);
    if (!asmeMatch.Success)
        return false;

    asmeSpec = asmeMatch.Value.ToUpperInvariant();

    var astmSpecMatch = Regex.Match(text, @"\bA\d+[A-Z]?\/A\d+[A-Z]?\b", RegexOptions.IgnoreCase);
    if (astmSpecMatch.Success)
    {
        astmSpec = astmSpecMatch.Value.ToUpperInvariant();
    }

    var astmYearMatch = Regex.Match(text, @"\bA\d+[A-Z]?\/A\d+[A-Z]?-(\d{2,4})\b", RegexOptions.IgnoreCase);
    if (astmYearMatch.Success)
    {
        var yearToken = astmYearMatch.Groups[1].Value;
        astmYear = yearToken.Length == 2 ? $"20{yearToken}" : yearToken;
    }

    return true;
}

static bool HasTopRightSaHeader(Page page)
{
    var words = page.GetWords();
    if (words is null)
        return false;

    var headerPattern = new Regex(@"^SA-\d+[A-Z]?/SA-\d+[A-Z]?M?$", RegexOptions.IgnoreCase);
    var minLeft = page.Width * 0.55;
    var minTop = page.Height * 0.8;

    foreach (var word in words)
    {
        if (!headerPattern.IsMatch(word.Text))
            continue;

        var box = word.BoundingBox;
        if (box.Left >= minLeft && box.Top >= minTop)
            return true;
    }

    return false;
}
