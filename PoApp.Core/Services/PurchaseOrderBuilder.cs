using PoApp.Core.Models;

namespace PoApp.Core.Services;

public sealed class PurchaseOrderBuilder
{
    public PurchaseOrderBuildResult Build(PurchaseOrderBuildInput input)
    {
        var text = BuildText(input);
        var export = BuildExport(input);
        return new PurchaseOrderBuildResult(text, export);
    }

    private static string BuildText(PurchaseOrderBuildInput input)
    {
        var lines = new List<string>();

        lines.Add("Line Item Header");
        var specSystem = input.Material.SpecSystem;
        if (string.Equals(specSystem, "ASTM", StringComparison.OrdinalIgnoreCase))
        {
            var materialLine = $"Material: {input.Material.SpecDisplay} (ASTM)";
            if (!string.IsNullOrWhiteSpace(input.Material.AstmEquivalencyInfo))
                materialLine += $". {input.Material.AstmEquivalencyInfo}";
            lines.Add(materialLine);
        }
        else
        {
            if (!string.IsNullOrWhiteSpace(input.Spec.Title))
                lines.Add($"Material: {input.Material.SpecDisplay} ({input.Spec.Title})");
            else
                lines.Add($"Material: {input.Material.SpecDisplay}");
        }

        if (!string.IsNullOrWhiteSpace(input.Material.Uns))
            lines.Add($"UNS: {input.Material.Uns}");

        lines.Add(string.Empty);
        lines.Add("Ordering Requirements");
        if (input.FilledOrderingFields.Count == 0)
        {
            lines.Add("- (none provided)");
        }
        else
        {
            foreach (var field in input.FilledOrderingFields)
                lines.Add($"- {field.Definition.Prompt}: {field.Value}");
        }

        lines.Add(string.Empty);
        lines.Add("Supplementary Requirements");
        if (input.SelectedSupplementaryRequirements.Count == 0)
        {
            lines.Add("- (none selected)");
        }
        else
        {
            lines.Add($"- Supplementary Requirements: {string.Join(", ", input.SelectedSupplementaryRequirements)}");
            foreach (var note in input.SupplementaryRequirementNotes.Where(note => !string.IsNullOrWhiteSpace(note)))
                lines.Add($"- {note}");
        }

        lines.Add(string.Empty);
        lines.Add("Compliance Notes");

        var complianceNotes = new List<string>();
        complianceNotes.AddRange(input.PolicyNotes.Where(static note => !string.IsNullOrWhiteSpace(note)));

        if (input.MtrRequired)
        {
            complianceNotes.Add("Provide MTR/CMTR (certified test report) with shipment.");
        }
        else if (input.CodeUse)
        {
            complianceNotes.Add("Marking requirements per selected ASME B16 standard; MTR not required by this policy.");
        }

        foreach (var rule in input.Spec.Rules)
        {
            var ruleNote = FormatSpecRule(rule);
            if (!string.IsNullOrWhiteSpace(ruleNote))
                complianceNotes.Add(ruleNote);
        }

        if (complianceNotes.Count == 0)
        {
            lines.Add("- (none)");
        }
        else
        {
            foreach (var note in complianceNotes.Distinct(StringComparer.OrdinalIgnoreCase))
                lines.Add($"- {note}");
        }

        return string.Join(Environment.NewLine, lines).Trim();
    }

    private static PurchaseOrderExport BuildExport(PurchaseOrderBuildInput input)
    {
        var fieldValues = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var field in input.FilledOrderingFields)
        {
            var key = !string.IsNullOrWhiteSpace(field.Definition.Key)
                ? field.Definition.Key!
                : !string.IsNullOrWhiteSpace(field.Definition.Id)
                    ? field.Definition.Id!
                    : field.Definition.Prompt;

            if (!fieldValues.ContainsKey(key))
                fieldValues[key] = field.Value;
        }

        return new PurchaseOrderExport(
            new PurchaseOrderExportContext(
                input.CodeUse,
                input.GoverningStandard,
                input.MtrRequired),
            new PurchaseOrderExportSpec(
                input.Spec.AsmeSpec,
                input.Spec.Title,
                input.Spec.AstmIdentical),
            input.Material,
            fieldValues,
            input.SelectedSupplementaryRequirements
                .Where(static value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList());
    }

    private static string? FormatSpecRule(SpecRuleDefinition rule)
    {
        if (!string.IsNullOrWhiteSpace(rule.Text))
            return rule.Text;

        if (!string.IsNullOrWhiteSpace(rule.When) && !string.IsNullOrWhiteSpace(rule.Then))
            return $"{rule.When}: {rule.Then}";

        return rule.Then;
    }
}
