using System.Text;
using PoApp.Core.Models;

namespace PoApp.Desktop.Services;

public static class PoTextGenerator
{
    public static string Generate(MaterialSpecRecord spec, string? grade, IEnumerable<string> selectedOrderingNotes)
    {
        var sb = new StringBuilder();

        sb.AppendLine($"MATERIAL: ASME {spec.SpecDesignation}");
        sb.AppendLine($"EQUIVALENT: ASTM {spec.AstmSpec}-{spec.AstmYear}");

        if (!string.IsNullOrWhiteSpace(grade))
            sb.AppendLine($"GRADE/CLASS/TYPE: {grade}");

        var notes = selectedOrderingNotes?.Where(n => !string.IsNullOrWhiteSpace(n)).ToList() ?? new();
        if (notes.Count > 0)
        {
            sb.AppendLine("ORDERING REQUIREMENTS:");
            foreach (var n in notes)
                sb.AppendLine($"- {n}");
        }

        sb.AppendLine();
        sb.AppendLine("CERTS: Provide MTRs / CMTRs as applicable.");

        return sb.ToString().Trim();
    }
}
