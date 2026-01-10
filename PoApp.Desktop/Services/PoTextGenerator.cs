using System.Text;
using PoApp.Core.Models;
using PoApp.Desktop.Models;

namespace PoApp.Desktop.Services;

public static class PoTextGenerator
{
    public static string Generate(
        MaterialSpecRecord spec,
        string? grade,
        IEnumerable<string> selectedOrderingNotes,
        IEnumerable<RequiredFieldEntry> requiredFields,
        string? selectedSpecType)
    {
        var sb = new StringBuilder();

        var materialDesignation = string.Equals(selectedSpecType, "A", StringComparison.OrdinalIgnoreCase)
            ? $"A-{spec.SpecNumber}"
            : spec.SpecDesignation;
        sb.AppendLine($"MATERIAL: {materialDesignation}");

        if (string.Equals(selectedSpecType, "A", StringComparison.OrdinalIgnoreCase)
            && !string.IsNullOrWhiteSpace(spec.AstmNote))
        {
            sb.AppendLine($"{spec.AstmNote} Per. ASME Sect.II 2025");
        }
        else if (string.Equals(selectedSpecType, "A", StringComparison.OrdinalIgnoreCase)
            && !string.IsNullOrWhiteSpace(spec.AstmYear))
        {
            sb.AppendLine($"{spec.AstmYear} ASTM Specification is identical to {spec.SpecDesignation} Per. ASME Sect.II 2025");
        }
        else if (!string.IsNullOrWhiteSpace(spec.AstmSpec))
        {
            sb.AppendLine($"EQUIVALENT: ASTM {spec.AstmSpec}-{spec.AstmYear}");
        }

        var required = requiredFields?.ToList() ?? new();
        var gradeHandledInRequired = required.Any(field =>
            string.Equals(field.Label, "Grade / Class / Type", StringComparison.OrdinalIgnoreCase));

        if (!string.IsNullOrWhiteSpace(grade) && !gradeHandledInRequired)
            sb.AppendLine($"GRADE/CLASS/TYPE: {grade}");

        var notes = selectedOrderingNotes?.Where(n => !string.IsNullOrWhiteSpace(n)).ToList() ?? new();
        if (notes.Count > 0)
        {
            sb.AppendLine("ORDERING REQUIREMENTS:");
            foreach (var n in notes)
                sb.AppendLine($"- {n}");
        }

        if (required.Count > 0)
        {
            sb.AppendLine("REQUIRED FIELDS:");
            foreach (var field in required)
            {
                var value = string.IsNullOrWhiteSpace(field.Value) ? "[enter]" : field.Value;
                if (!string.IsNullOrWhiteSpace(field.Note) && string.IsNullOrWhiteSpace(field.Value))
                    value = field.Note;

                sb.AppendLine($"- {field.Label}: {value}");
            }
        }

        sb.AppendLine();
        sb.AppendLine("CERTS: Provide MTRs / CMTRs as applicable.");

        return sb.ToString().Trim();
    }
}
