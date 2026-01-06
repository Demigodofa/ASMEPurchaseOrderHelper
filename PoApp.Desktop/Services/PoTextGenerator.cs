using System.Text;
using PoApp.Core.Models;

namespace PoApp.Desktop.Services;

public static class PoTextGenerator
{
    public static string Generate(MaterialSpecRecord spec, string? grade, IEnumerable<string> selectedOrderingNotes, string? selectedSpecType)
    {
        var sb = new StringBuilder();

        var materialDesignation = string.Equals(selectedSpecType, "A", StringComparison.OrdinalIgnoreCase)
            ? $"A-{spec.SpecNumber}"
            : spec.SpecDesignation;
        sb.AppendLine($"MATERIAL: {materialDesignation}");

        if (string.Equals(selectedSpecType, "A", StringComparison.OrdinalIgnoreCase)
            && !string.IsNullOrWhiteSpace(spec.AstmYear))
        {
            sb.AppendLine($"{spec.AstmYear} ASTM Specification is identical to {spec.SpecDesignation} Per. ASME Sect.II 2025");
        }
        else if (!string.IsNullOrWhiteSpace(spec.AstmSpec))
        {
            sb.AppendLine($"EQUIVALENT: ASTM {spec.AstmSpec}-{spec.AstmYear}");
        }

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
