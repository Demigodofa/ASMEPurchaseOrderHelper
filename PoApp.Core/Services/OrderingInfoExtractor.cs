using System.Linq;
using System.Text.RegularExpressions;

namespace PoApp.Core.Services;

public static class OrderingInfoExtractor
{
    private static readonly Regex HeaderPattern = new(
        @"(?s)(?<section>\d+)\s*\.?\s*(Ordering\s*Information|Ordering\s*Requirements|Information\s*for\s*Ordering)",
        RegexOptions.IgnoreCase);

    private static readonly Regex NextSectionPattern = new(
        @"(?m)^\s*\d+\s*(?:\.)\s+(?!\d)\s*[A-Z]",
        RegexOptions.IgnoreCase);

    private static readonly Regex NextSectionNoDotPattern = new(
        @"(?m)^\s*\d+\s+(?!\d)\s*[A-Z]",
        RegexOptions.IgnoreCase);

    public static List<string> ExtractOrderingItems(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return new List<string>();

        var normalized = text.Replace("\r\n", "\n");
        var items = new List<string>();

        foreach (Match headerMatch in HeaderPattern.Matches(normalized))
        {
            var section = headerMatch.Groups["section"].Value;
            if (string.IsNullOrWhiteSpace(section))
                continue;

            var start = headerMatch.Index + headerMatch.Length;
            var tail = normalized.Substring(start);
            var end = ResolveNextSectionEnd(tail, start, normalized.Length);
            if (end <= start)
                continue;

            var body = normalized.Substring(start, end - start);
            items.AddRange(ParseOrderingItems(body, section));
        }

        return items;
    }

    private static int ResolveNextSectionEnd(string tail, int startOffset, int fallbackEnd)
    {
        var matchDot = NextSectionPattern.Match(tail);
        var matchNoDot = NextSectionNoDotPattern.Match(tail);

        if (matchDot.Success && matchNoDot.Success)
            return startOffset + Math.Min(matchDot.Index, matchNoDot.Index);

        if (matchDot.Success)
            return startOffset + matchDot.Index;

        if (matchNoDot.Success)
            return startOffset + matchNoDot.Index;

        return fallbackEnd;
    }

    private static List<string> ParseOrderingItems(string text, string sectionNumber)
    {
        var items = new List<string>();
        if (string.IsNullOrWhiteSpace(text) || string.IsNullOrWhiteSpace(sectionNumber))
            return items;

        var normalized = NormalizeWhitespace(text);
        var itemPattern = new Regex(
            @"\b" + Regex.Escape(sectionNumber) + @"\s*\.\s*\d+(?:\s*\.\s*\d+)*\b",
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

    private static string CleanOrderingItem(string text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return string.Empty;

        var cleaned = Regex.Replace(text, @"(\w)-\s+(\w)", "$1$2");
        cleaned = Regex.Replace(cleaned, @"\bship-ment\b", "shipment", RegexOptions.IgnoreCase);
        cleaned = Regex.Replace(cleaned, @"\bre-quirements\b", "requirements", RegexOptions.IgnoreCase);
        cleaned = Regex.Replace(cleaned, @"\brequire-ments\b", "requirements", RegexOptions.IgnoreCase);
        cleaned = Regex.Replace(cleaned, @"^[\.\-]+\s*", "");
        cleaned = Regex.Replace(cleaned, @"\s+\d+$", "");
        return NormalizeWhitespace(cleaned);
    }

    private static string NormalizeWhitespace(string value)
    {
        return Regex.Replace(value, @"\s+", " ").Trim();
    }
}
