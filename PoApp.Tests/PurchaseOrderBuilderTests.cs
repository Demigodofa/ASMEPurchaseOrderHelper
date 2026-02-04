using PoApp.Core.Models;
using PoApp.Core.Services;

namespace PoApp.Tests;

public sealed class PurchaseOrderBuilderTests
{
    [Fact]
    public void Build_ProducesExpectedSections_AndExportPayload()
    {
        var builder = new PurchaseOrderBuilder();
        var spec = new SpecDefinitionRecord(
            "SA-106/SA-106M",
            "Seamless Carbon Steel Pipe for High-Temperature Service",
            "A106/A106M-24",
            [],
            [
                new OrderingFieldDefinition("5.1.1", "quantity", "Quantity", "text", true, null, [], [], null, null),
                new OrderingFieldDefinition("5.1.2", "size", "Size", "text", true, null, [], [], null, null)
            ],
            [new SupplementaryRequirementDefinition("S1", "Impact test", "Specify impact test temperature.")],
            [new SpecRuleDefinition("rule", "If supplementary selected", "State in PO", null)]);

        var input = new PurchaseOrderBuildInput(
            spec,
            CodeUse: true,
            GoverningStandard: "ASME BPVC Section II material",
            MtrRequired: true,
            PolicyNotes: ["Provide MTR/CMTR (certified test report) with shipment."],
            FilledOrderingFields:
            [
                new FilledOrderingField(spec.OrderingFields[0], "100 ft"),
                new FilledOrderingField(spec.OrderingFields[1], "NPS 4, SCH 40")
            ],
            SelectedSupplementaryRequirements: ["S1"],
            SupplementaryRequirementNotes: ["Specify impact test temperature."]);

        var result = builder.Build(input);

        Assert.Contains("Line Item Header", result.Text);
        Assert.Contains("Ordering Requirements", result.Text);
        Assert.Contains("Supplementary Requirements", result.Text);
        Assert.Contains("Compliance Notes", result.Text);
        Assert.Contains("Material: SA-106/SA-106M", result.Text);

        Assert.Equal("SA-106/SA-106M", result.Export.Spec.AsmeSpec);
        Assert.True(result.Export.PoContext.CodeUse);
        Assert.True(result.Export.FieldValues.ContainsKey("quantity"));
        Assert.Contains("S1", result.Export.SelectedSupplementaryRequirements);
    }

    [Fact]
    public void RequiredFieldValidator_FlagsOnlyHardRequiredMissingFields()
    {
        var validator = new RequiredFieldValidator();
        var definitions = new List<OrderingFieldDefinition>
        {
            new("5.1.1", "quantity", "Quantity", "text", true, null, [], [], null, null),
            new("5.1.2", "grade", "Grade", "text", true, "when_applicable", [], [], null, null),
            new("5.1.3", "finish", "Finish", "text", false, null, [], [], null, null)
        };

        var values = new Dictionary<string, string?>
        {
            ["quantity"] = "",
            ["grade"] = ""
        };

        var missing = validator.GetMissingRequiredFields(definitions, values);

        Assert.Single(missing);
        Assert.Equal("Quantity", missing[0].Prompt);
    }
}
