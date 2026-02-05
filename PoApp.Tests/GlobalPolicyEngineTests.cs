using PoApp.Core.Models;
using PoApp.Core.Services;

namespace PoApp.Tests;

public sealed class GlobalPolicyEngineTests
{
    [Fact]
    public void Evaluate_SetsMtrRequired_WhenCodeUseTrueAndNotB16()
    {
        var engine = new GlobalPolicyEngine();
        var policy = BuildPolicy();

        var result = engine.Evaluate(policy, new GlobalPolicyContext(
            CodeUse: true,
            ItemType: "RawMaterial",
            OrderToStandard: "ASME BPVC Section II",
            MarkingRequired: false,
            PurchaserRequiresMtr: false,
            MtrRequired: false));

        Assert.True(result.MtrRequired);
        Assert.True(result.IsMtrLocked);
        Assert.Contains(result.Notes, note => note.Contains("MTR", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Evaluate_ClearsMtrRequired_ForB16MarkingOnly()
    {
        var engine = new GlobalPolicyEngine();
        var policy = BuildPolicy();

        var result = engine.Evaluate(policy, new GlobalPolicyContext(
            CodeUse: true,
            ItemType: "Component",
            OrderToStandard: "ASME B16.9",
            MarkingRequired: true,
            PurchaserRequiresMtr: false,
            MtrRequired: true));

        Assert.False(result.MtrRequired);
        Assert.True(result.IsMtrLocked);
        Assert.Contains(result.Notes, note => note.Contains("Marking", StringComparison.OrdinalIgnoreCase));
    }

    private static GlobalPolicyRecord BuildPolicy()
    {
        return new GlobalPolicyRecord(
            "POLICY",
            "1.0.0",
            "Test policy",
            ["code_use", "order_to_standard", "marking_required"],
            [],
            [
                new GlobalPolicyRule(
                    "RULE1",
                    "code_use == true AND order_to_standard NOT IN B16_MARKING_ONLY",
                    [
                        new GlobalPolicyAction("mtr_required", true, "mtr_required", true, null),
                        new GlobalPolicyAction(null, null, null, null, "Provide MTR/CMTR (certified test report) with shipment.")
                    ],
                    null,
                    null),
                new GlobalPolicyRule(
                    "RULE2",
                    "code_use == true AND order_to_standard IN B16_MARKING_ONLY",
                    [
                        new GlobalPolicyAction("mtr_required", false, "mtr_required", true, null),
                        new GlobalPolicyAction(null, null, null, null, "Marking requirements apply; MTR not required by this policy.")
                    ],
                    null,
                    null)
            ],
            new Dictionary<string, IReadOnlyList<string>>(StringComparer.OrdinalIgnoreCase)
            {
                ["B16_MARKING_ONLY"] = ["ASME B16.5", "ASME B16.9", "ASME B16.11", "ASME B16.34"]
            });
    }
}
