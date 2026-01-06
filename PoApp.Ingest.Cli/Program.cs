using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Configuration;
using PoApp.Core.Configuration;
using PoApp.Core.Models;
using UglyToad.PdfPig;
using UglyToad.PdfPig.Content;

var settings = LoadSettings();
var pdfRoot = ResolvePdfRoot(settings);

var pdfFiles = ResolvePdfFiles(settings, pdfRoot);

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
        if (!TryExtractSpecFromPage(page, out var record))
            continue;

        if (!results.ContainsKey(record.SpecDesignation))
            results[record.SpecDesignation] = record;
    }
}

var dataDir = ResolveDataDirectory();
Directory.CreateDirectory(dataDir);
var combinedDataset = new MaterialDataset(results.Values.OrderBy(r => r.SpecDesignation).ToList());
WriteDataset(Path.Combine(dataDir, "materials.json"), combinedDataset);

WriteDataset(Path.Combine(dataDir, "materials-ferrous.json"),
    new MaterialDataset(combinedDataset.Materials.Where(m => m.Category == MaterialCategory.Ferrous).ToList()));
WriteDataset(Path.Combine(dataDir, "materials-nonferrous.json"),
    new MaterialDataset(combinedDataset.Materials.Where(m => m.Category == MaterialCategory.NonFerrous).ToList()));
WriteDataset(Path.Combine(dataDir, "materials-electrode.json"),
    new MaterialDataset(combinedDataset.Materials.Where(m => m.Category == MaterialCategory.ElectrodeWire).ToList()));

Console.WriteLine($"Extracted {results.Count} material specs.");
Console.WriteLine($"Wrote dataset to: {Path.Combine(dataDir, "materials.json")}");

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

static List<string> ResolvePdfFiles(AppSettings settings, string pdfRoot)
{
    var explicitFiles = settings.Paths.PdfFiles
        .Where(path => !string.IsNullOrWhiteSpace(path))
        .Select(Path.GetFullPath)
        .ToList();

    if (explicitFiles.Count > 0)
    {
        var existing = explicitFiles.Where(File.Exists).ToList();
        var missing = explicitFiles.Except(existing, StringComparer.OrdinalIgnoreCase).ToList();
        foreach (var path in missing)
        {
            Console.WriteLine($"Missing PDF file: {path}");
        }

        return existing;
    }

    if (!Directory.Exists(pdfRoot))
    {
        Console.WriteLine($"PDF source folder not found: {pdfRoot}");
        return new List<string>();
    }

    return Directory.EnumerateFiles(pdfRoot, "*.pdf", SearchOption.TopDirectoryOnly)
        .Where(path => Path.GetFileName(path).Contains("SECT II", StringComparison.OrdinalIgnoreCase))
        .Where(path => Path.GetFileName(path).Contains("PART A", StringComparison.OrdinalIgnoreCase))
        .Where(path => !Path.GetFileName(path).Contains("PART B", StringComparison.OrdinalIgnoreCase))
        .ToList();
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

static bool TryExtractSpecFromPage(Page page, out MaterialSpecRecord record)
{
    record = default!;

    var text = page.Text;
    if (string.IsNullOrWhiteSpace(text))
        return false;

    if (!TryGetTopRightHeader(page, out var headerText))
        return false;

    if (!TryParseSpec(headerText, out var prefix, out var number))
        return false;

    var designation = $"{prefix}-{number}";

    var astmSpecMatch = Regex.Match(text, @"\bA\d+[A-Z]?\/A\d+[A-Z]?\b", RegexOptions.IgnoreCase);
    var astmSpec = string.Empty;
    if (astmSpecMatch.Success)
    {
        astmSpec = astmSpecMatch.Value.ToUpperInvariant();
    }

    var astmYearMatch = Regex.Match(text, @"\bA\d+[A-Z]?\/A\d+[A-Z]?-(\d{2,4})\b", RegexOptions.IgnoreCase);
    var astmYear = string.Empty;
    if (astmYearMatch.Success)
    {
        var yearToken = astmYearMatch.Groups[1].Value;
        astmYear = yearToken.Length == 2 ? $"20{yearToken}" : yearToken;
    }

    var category = ResolveCategory(prefix);
    record = new MaterialSpecRecord(
        SpecDesignation: designation,
        SpecPrefix: prefix,
        SpecNumber: number,
        AstmSpec: astmSpec,
        AstmYear: astmYear,
        Category: category,
        Grades: Array.Empty<string>(),
        OrderingNotes: Array.Empty<string>());

    return true;
}

static bool TryGetTopRightHeader(Page page, out string headerText)
{
    headerText = string.Empty;
    var words = page.GetWords();
    if (words is null)
        return false;

    var headerPattern = new Regex(@"^[A-Z]+-\d+[A-Z]?/[A-Z]+-\d+[A-Z]?M?$", RegexOptions.IgnoreCase);
    var minLeft = page.Width * 0.55;
    var minTop = page.Height * 0.8;

    foreach (var word in words)
    {
        if (!headerPattern.IsMatch(word.Text))
            continue;

        var box = word.BoundingBox;
        if (box.Left >= minLeft && box.Top >= minTop)
        {
            headerText = word.Text.Trim();
            return true;
        }
    }

    return false;
}

static bool TryParseSpec(string headerText, out string prefix, out string number)
{
    prefix = string.Empty;
    number = string.Empty;

    if (string.IsNullOrWhiteSpace(headerText))
        return false;

    var match = Regex.Match(headerText, @"^(?<prefix>[A-Z]+)-(?<num>\d+[A-Z]?)(?:/|$)", RegexOptions.IgnoreCase);
    if (!match.Success)
        return false;

    prefix = match.Groups["prefix"].Value.ToUpperInvariant();
    number = match.Groups["num"].Value.ToUpperInvariant();
    return true;
}

static MaterialCategory ResolveCategory(string prefix)
{
    if (prefix.Equals("SB", StringComparison.OrdinalIgnoreCase))
        return MaterialCategory.NonFerrous;

    if (prefix.StartsWith("SF", StringComparison.OrdinalIgnoreCase))
        return MaterialCategory.ElectrodeWire;

    if (prefix.Equals("SA", StringComparison.OrdinalIgnoreCase) || prefix.Equals("A", StringComparison.OrdinalIgnoreCase))
        return MaterialCategory.Ferrous;

    return MaterialCategory.Unknown;
}

static void WriteDataset(string path, MaterialDataset dataset)
{
    var json = JsonSerializer.Serialize(dataset, new JsonSerializerOptions { WriteIndented = true });
    File.WriteAllText(path, json);
}
