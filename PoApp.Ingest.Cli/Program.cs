using System.Text;
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

var tocSpecs = ExtractTocSpecs(pdfFiles);
if (tocSpecs.Count > 0)
    Console.WriteLine($"TOC specs found: {tocSpecs.Count}");
if (tocSpecs.Count < 100)
{
    Console.WriteLine("TOC spec count is low; header filtering is disabled for this run.");
    tocSpecs.Clear();
}

var results = new Dictionary<string, MaterialSpecRecord>(StringComparer.OrdinalIgnoreCase);
var orderingItemsBySpec = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);

foreach (var pdfPath in pdfFiles)
{
    Console.WriteLine($"- {Path.GetFileName(pdfPath)}");

    using var document = PdfDocument.Open(pdfPath);
    string? currentSpec = null;
    var currentSpecText = new StringBuilder();

    foreach (var page in document.GetPages())
    {
        if (TryExtractSpecFromPage(page, out var record, out var headerText, tocSpecs))
        {
            if (currentSpec is not null && !string.Equals(currentSpec, record.SpecDesignation, StringComparison.OrdinalIgnoreCase))
            {
                FinalizeOrderingInfo(currentSpec, currentSpecText.ToString(), orderingItemsBySpec);
                currentSpecText.Clear();
            }

            currentSpec = record.SpecDesignation;
            if (!results.ContainsKey(record.SpecDesignation))
                results[record.SpecDesignation] = record;
        }

        if (currentSpec is null)
            continue;

        currentSpecText.AppendLine(page.Text);
    }

    if (currentSpec is not null)
    {
        FinalizeOrderingInfo(currentSpec, currentSpecText.ToString(), orderingItemsBySpec);
        currentSpecText.Clear();
    }
}

var dataDir = ResolveDataDirectory();
Directory.CreateDirectory(dataDir);
var combinedDataset = new MaterialDataset(results.Values
    .Select(record =>
    {
        orderingItemsBySpec.TryGetValue(record.SpecDesignation, out var orderingItems);
        return record with
        {
            OrderingInfoItems = orderingItems is not null ? orderingItems.ToList() : Array.Empty<string>()
        };
    })
    .OrderBy(r => r.SpecDesignation)
    .ToList());
WriteDataset(Path.Combine(dataDir, "materials.json"), combinedDataset);

WriteDataset(Path.Combine(dataDir, "materials-ferrous.json"),
    new MaterialDataset(combinedDataset.Materials.Where(m => m.Category == MaterialCategory.Ferrous).ToList()));
WriteDataset(Path.Combine(dataDir, "materials-nonferrous.json"),
    new MaterialDataset(combinedDataset.Materials.Where(m => m.Category == MaterialCategory.NonFerrous).ToList()));
WriteDataset(Path.Combine(dataDir, "materials-electrode.json"),
    new MaterialDataset(combinedDataset.Materials.Where(m => m.Category == MaterialCategory.ElectrodeWire).ToList()));

Console.WriteLine($"Extracted {results.Count} material specs.");
Console.WriteLine($"Wrote dataset to: {Path.Combine(dataDir, "materials.json")}");

var missingSpecs = ReportMissingSpecs(settings, combinedDataset);
if (missingSpecs.Count > 0 && settings.Ingest.ScanMissingSpecs)
{
    ScanForMissingSpecs(pdfFiles, missingSpecs);
}

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

static bool TryExtractSpecFromPage(
    Page page,
    out MaterialSpecRecord record,
    out string headerText,
    IReadOnlySet<string>? allowedSpecs = null)
{
    record = default!;
    headerText = string.Empty;

    var text = page.Text;
    if (string.IsNullOrWhiteSpace(text))
        return false;

    if (!TryGetTopRightHeader(page, allowedSpecs, out headerText)
        && !TryGetTopHeaderFromWords(page, allowedSpecs, out headerText)
        && !TryGetHeaderFromTopLines(text, allowedSpecs, out headerText))
        return false;

    if (!TryParseSpec(headerText, allowedSpecs, out var prefix, out var number))
        return false;

    var designation = $"{prefix}-{number}";
    if (headerText.Contains("HIGHSTRENGTHSA-", StringComparison.OrdinalIgnoreCase))
    {
        prefix = "SA";
        designation = $"HIGH STRENGTH SA-{number}";
    }

    var (astmSpec, astmYear, astmNote) = ExtractAstmEquivalent(text);

    var category = ResolveCategory(prefix);
    record = new MaterialSpecRecord(
        SpecDesignation: designation,
        SpecPrefix: prefix,
        SpecNumber: number,
        AstmSpec: astmSpec,
        AstmYear: astmYear,
        AstmNote: astmNote,
        Category: category,
        OrderingInfoItems: Array.Empty<string>(),
        Grades: Array.Empty<string>(),
        OrderingNotes: Array.Empty<string>());

    return true;
}

static void FinalizeOrderingInfo(
    string spec,
    string text,
    Dictionary<string, List<string>> orderingItemsBySpec)
{
    var items = ExtractOrderingItems(text);
    if (items.Count == 0)
        return;

    if (!orderingItemsBySpec.TryGetValue(spec, out var existing))
    {
        existing = new List<string>();
        orderingItemsBySpec[spec] = existing;
    }

    existing.AddRange(items);
}

static List<string> ExtractOrderingItems(string text)
{
    if (string.IsNullOrWhiteSpace(text))
        return new List<string>();

    var normalized = text.Replace("\r\n", "\n");
    var headerMatches = Regex.Matches(
        normalized,
        @"(?s)(?<section>\d+)\s*\.\s*Ordering\s*Information",
        RegexOptions.IgnoreCase);

    var items = new List<string>();
    foreach (Match headerMatch in headerMatches)
    {
        var section = headerMatch.Groups["section"].Value;
        if (string.IsNullOrWhiteSpace(section))
            continue;

        var start = headerMatch.Index + headerMatch.Length;
        var tail = normalized.Substring(start);
        var nextSection = Regex.Match(tail, @"\b\d+\s*\.(?!\s*\d)\s+[A-Z]", RegexOptions.IgnoreCase);
        var end = nextSection.Success ? start + nextSection.Index : normalized.Length;
        if (end <= start)
            continue;

        var body = normalized.Substring(start, end - start);
        items.AddRange(ParseOrderingItems(body, section));
    }

    return items;
}

static List<string> ParseOrderingItems(string text, string sectionNumber)
{
    var items = new List<string>();
    if (string.IsNullOrWhiteSpace(text) || string.IsNullOrWhiteSpace(sectionNumber))
        return items;

    var normalized = NormalizeWhitespace(text);
    var itemPattern = new Regex(
        @"\b" + Regex.Escape(sectionNumber) + @"\s*\.\s*\d+(?:\s*\.\s*\d+)?\b",
        RegexOptions.IgnoreCase);

    var matches = itemPattern.Matches(normalized).Cast<Match>().ToList();
    for (var i = 0; i < matches.Count; i++)
    {
        var start = matches[i].Index + matches[i].Length;
        var end = (i + 1 < matches.Count) ? matches[i + 1].Index : normalized.Length;
        if (end <= start)
            continue;

        var itemText = normalized.Substring(start, end - start).Trim();
        if (itemText.Length == 0)
            continue;

        itemText = CleanOrderingItem(itemText);
        if (itemText.Length == 0)
            continue;

        if (itemText.StartsWith("Information items to be considered", StringComparison.OrdinalIgnoreCase))
            continue;

        items.Add(itemText);
    }

    return items;
}

static string CleanOrderingItem(string text)
{
    if (string.IsNullOrWhiteSpace(text))
        return string.Empty;

    var cleaned = Regex.Replace(text, @"(\w)-\s+(\w)", "$1$2");
    cleaned = Regex.Replace(cleaned, @"\bship-ment\b", "shipment", RegexOptions.IgnoreCase);
    cleaned = Regex.Replace(cleaned, @"\bre-quirements\b", "requirements", RegexOptions.IgnoreCase);
    cleaned = Regex.Replace(cleaned, @"\brequire-ments\b", "requirements", RegexOptions.IgnoreCase);
    cleaned = Regex.Replace(cleaned, @"\s+\d+$", "");
    return NormalizeWhitespace(cleaned);
}

static (string Spec, string Year, string Note) ExtractAstmEquivalent(string text)
{
    if (string.IsNullOrWhiteSpace(text))
        return (string.Empty, string.Empty, string.Empty);

    var identMatch = Regex.Match(
        text,
        @"\((?<note>Identical\s+with\s+ASTM\s+Specification\s+.+?)\)",
        RegexOptions.IgnoreCase | RegexOptions.Singleline);
    if (identMatch.Success)
    {
        var note = NormalizeWhitespace(identMatch.Groups["note"].Value);
        var specMatch = Regex.Match(note, @"ASTM\s+Specification\s+(A\d+[A-Z]?\/A\d+[A-Z]?M?)-(\d{2,4})",
            RegexOptions.IgnoreCase);
        if (specMatch.Success)
        {
            var spec = specMatch.Groups[1].Value.ToUpperInvariant();
            var yearToken = specMatch.Groups[2].Value;
            var year = yearToken.Length == 2 ? $"20{yearToken}" : yearToken;
            return (spec, year, note);
        }
    }

    var astmSpecMatch = Regex.Match(text, @"\bA\d+[A-Z]?\/A\d+[A-Z]?\b", RegexOptions.IgnoreCase);
    var astmSpec = astmSpecMatch.Success ? astmSpecMatch.Value.ToUpperInvariant() : string.Empty;

    var astmYearMatch = Regex.Match(text, @"\bA\d+[A-Z]?\/A\d+[A-Z]?-(\d{2,4})\b", RegexOptions.IgnoreCase);
    var astmYear = string.Empty;
    if (astmYearMatch.Success)
    {
        var yearToken = astmYearMatch.Groups[1].Value;
        astmYear = yearToken.Length == 2 ? $"20{yearToken}" : yearToken;
    }

    return (astmSpec, astmYear, string.Empty);
}

static string NormalizeWhitespace(string value)
{
    return Regex.Replace(value, @"\s+", " ").Trim();
}

static bool TryGetTopRightHeader(Page page, IReadOnlySet<string>? allowedSpecs, out string headerText)
{
    headerText = string.Empty;
    var words = page.GetWords();
    if (words is null)
        return false;

    var headerPattern = new Regex(@"^[A-Z]+-\d+[A-Z]?(?:/[A-Z]+-\d+[A-Z]?M?)?$", RegexOptions.IgnoreCase);
    var minLeft = page.Width * 0.55;
    var minTop = page.Height * 0.8;

    foreach (var word in words)
    {
        if (!headerPattern.IsMatch(word.Text))
            continue;

        if (!TryParseSpec(word.Text, allowedSpecs, out _, out _))
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

static bool TryGetTopHeaderFromWords(Page page, IReadOnlySet<string>? allowedSpecs, out string headerText)
{
    headerText = string.Empty;
    var words = page.GetWords();
    if (words is null)
        return false;

    var headerPattern = new Regex(@"^[A-Z]+-\d+[A-Z]?(?:/[A-Z]+-\d+[A-Z]?M?)?$", RegexOptions.IgnoreCase);
    var minTop = page.Height * 0.8;
    var maxLeft = page.Width * 0.35;

    foreach (var word in words)
    {
        if (!headerPattern.IsMatch(word.Text))
            continue;

        if (!TryParseSpec(word.Text, allowedSpecs, out _, out _))
            continue;

        var box = word.BoundingBox;
        if (box.Top >= minTop && box.Left <= maxLeft)
        {
            headerText = word.Text.Trim();
            return true;
        }
    }

    return false;
}

static bool TryGetHeaderFromTopLines(string text, IReadOnlySet<string>? allowedSpecs, out string headerText)
{
    headerText = string.Empty;

    var lines = text.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries);
    if (lines.Length == 0)
        return false;

    var headerPattern = new Regex(
        @"^(?<prefix>[A-Z]+)\s*-\s*(?<num>\d+[A-Z]?)\s*/\s*(?<prefix2>[A-Z]+)\s*-\s*(?<num2>\d+[A-Z]?)\s*M?$",
        RegexOptions.IgnoreCase);
    var singlePattern = new Regex(@"^(?<prefix>[A-Z]+)\s*-\s*(?<num>\d+[A-Z]?)$", RegexOptions.IgnoreCase);

    foreach (var line in lines.Take(10))
    {
        var candidate = line.Trim();
        var match = headerPattern.Match(candidate);
        if (match.Success)
        {
            var prefix = match.Groups["prefix"].Value.ToUpperInvariant();
            var number = match.Groups["num"].Value.ToUpperInvariant();
            headerText = $"{prefix}-{number}/{prefix}-{number}M";
            return IsAllowedSpec(headerText, allowedSpecs);
        }

        var singleMatch = singlePattern.Match(candidate);
        if (singleMatch.Success)
        {
            var prefix = singleMatch.Groups["prefix"].Value.ToUpperInvariant();
            var number = singleMatch.Groups["num"].Value.ToUpperInvariant();
            headerText = $"{prefix}-{number}";
            return IsAllowedSpec(headerText, allowedSpecs);
        }
    }

    var compactPattern = new Regex(
        @"(?<prefix>[A-Z]+)-(?<num>\d+[A-Z]?)/(?<prefix2>[A-Z]+)-(?<num2>\d+[A-Z]?)[M]?",
        RegexOptions.IgnoreCase);
    var compactBlock = Regex.Replace(string.Join(" ", lines.Take(10)), @"\s+", "");
    var compactMatch = compactPattern.Match(compactBlock);
    if (compactMatch.Success)
    {
        var prefix = compactMatch.Groups["prefix"].Value.ToUpperInvariant();
        var number = compactMatch.Groups["num"].Value.ToUpperInvariant();
        headerText = $"{prefix}-{number}/{prefix}-{number}M";
        return IsAllowedSpec(headerText, allowedSpecs);
    }

    return false;
}

static bool TryParseSpec(string headerText, IReadOnlySet<string>? allowedSpecs, out string prefix, out string number)
{
    prefix = string.Empty;
    number = string.Empty;

    if (string.IsNullOrWhiteSpace(headerText))
        return false;

    var match = Regex.Match(headerText, @"^(?<prefix>[A-Z]+)-(?<num>\d+[A-Z]?)(?:/|$)", RegexOptions.IgnoreCase);
    if (!match.Success)
        match = Regex.Match(headerText, @"^(?<prefix>[A-Z]+)-(?<num>\d+[A-Z]?)$", RegexOptions.IgnoreCase);
    if (!match.Success)
        return false;

    prefix = match.Groups["prefix"].Value.ToUpperInvariant();
    number = match.Groups["num"].Value.ToUpperInvariant();
    var designation = $"{prefix}-{number}";
    return IsAllowedSpec(designation, allowedSpecs);
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

static List<string> ReportMissingSpecs(AppSettings settings, MaterialDataset dataset)
{
    var expected = settings.Ingest.ExpectedSpecs
        .Where(spec => !string.IsNullOrWhiteSpace(spec))
        .Select(spec => spec.Trim().ToUpperInvariant())
        .Distinct()
        .ToList();

    if (expected.Count == 0)
        return new List<string>();

    var found = dataset.Materials.Select(m => m.SpecDesignation.ToUpperInvariant()).ToHashSet();
    var missing = expected.Where(spec => !found.Contains(spec)).ToList();

    if (missing.Count == 0)
    {
        Console.WriteLine("All expected specs were found.");
        return missing;
    }

    Console.WriteLine($"Missing {missing.Count} expected spec(s):");
    foreach (var spec in missing.OrderBy(spec => spec))
        Console.WriteLine($"- {spec}");

    return missing;
}

static void ScanForMissingSpecs(IEnumerable<string> pdfFiles, IReadOnlyCollection<string> missingSpecs)
{
    Console.WriteLine("Scanning PDFs for missing spec mentions (no header filter)...");

    var patterns = missingSpecs
        .Select(spec => new { Spec = spec, Regex = new Regex(@"\b" + Regex.Escape(spec) + @"\b", RegexOptions.IgnoreCase) })
        .ToList();

    var hits = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);

    foreach (var pdfPath in pdfFiles)
    {
        using var document = PdfDocument.Open(pdfPath);
        foreach (var page in document.GetPages())
        {
            var text = page.Text;
            if (string.IsNullOrWhiteSpace(text))
                continue;

            foreach (var entry in patterns)
            {
                if (!entry.Regex.IsMatch(text))
                    continue;

                if (!hits.TryGetValue(entry.Spec, out var locations))
                {
                    locations = new List<string>();
                    hits[entry.Spec] = locations;
                }

                if (locations.Count >= 3)
                    continue;

                locations.Add($"{Path.GetFileName(pdfPath)} page {page.Number}");
            }
        }
    }

    if (hits.Count == 0)
    {
        Console.WriteLine("No mentions of missing specs were found in the scanned PDFs.");
        return;
    }

    Console.WriteLine("Missing spec mentions found:");
    foreach (var spec in hits.Keys.OrderBy(s => s))
    {
        Console.WriteLine($"- {spec}: {string.Join(", ", hits[spec])}");
    }
}

static HashSet<string> ExtractTocSpecs(IEnumerable<string> pdfFiles)
{
    var specs = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    var headerPattern = new Regex(@"\b(?<spec>(?:SA|SB|SF|A)-\d+[A-Z]?M?)\b", RegexOptions.IgnoreCase);

    foreach (var pdfPath in pdfFiles)
    {
        using var document = PdfDocument.Open(pdfPath);
        var tocStarted = false;
        var emptyPages = 0;

        foreach (var page in document.GetPages())
        {
            var text = page.Text;
            if (string.IsNullOrWhiteSpace(text))
                continue;

            if (!tocStarted && text.IndexOf("TABLE OF CONTENTS", StringComparison.OrdinalIgnoreCase) >= 0)
                tocStarted = true;

            if (!tocStarted)
                continue;

            var pageMatches = headerPattern.Matches(text);
            if (pageMatches.Count == 0)
            {
                emptyPages++;
                if (emptyPages >= 4)
                    break;
                continue;
            }

            emptyPages = 0;
            foreach (Match match in pageMatches)
            {
                var spec = match.Groups["spec"].Value.ToUpperInvariant();
                specs.Add(spec);
            }
        }

        if (specs.Count > 0)
            break;
    }

    return specs;
}

static bool IsAllowedSpec(string designation, IReadOnlySet<string>? allowedSpecs)
{
    if (allowedSpecs is null || allowedSpecs.Count == 0)
        return true;

    var normalized = designation.ToUpperInvariant();
    if (normalized.Contains("/"))
        normalized = normalized.Split('/')[0];

    return allowedSpecs.Contains(normalized);
}
