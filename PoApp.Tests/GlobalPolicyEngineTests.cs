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

        var result = engine.Evaluate(
            policy,
            codeUse: true,
            governingStandard: "ASME BPVC Section II material",
            currentMtrRequired: false);

        Assert.True(result.MtrRequired);
        Assert.True(result.IsMtrLocked);
        Assert.Contains(result.Notes, note => note.Contains("MTR", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Evaluate_ClearsMtrRequired_ForB16MarkingOnly()
    {
        var engine = new GlobalPolicyEngine();
        var policy = BuildPolicy();

        var result = engine.Evaluate(
            policy,
            codeUse: true,
            governingStandard: "ASME B16.9",
            currentMtrRequired: true);

        Assert.False(result.MtrRequired);
        Assert.True(result.IsMtrLocked);
        Assert.Contains(result.Notes, note => note.Contains("Marking", StringComparison.OrdinalIgnoreCase));
    }

    private static GlobalPolicyRecord BuildPolicy()
    {
        return new GlobalPolicyRecord(
            "POLICY",
            "Test policy",
            ["code_use", "governing_standard"],
            [
                new GlobalPolicyRule(
                    "RULE1",
                    "code_use == true AND governing_standard NOT IN B16_MARKING_ONLY",
                    [
                        new GlobalPolicyAction("mtr_required", true, null),
                        new GlobalPolicyAction(null, null, "Provide MTR/CMTR (certified test report) with shipment.")
                    ],
                    null,
                    null),
                new GlobalPolicyRule(
                    "RULE2",
                    "code_use == true AND governing_standard IN B16_MARKING_ONLY",
                    [
                        new GlobalPolicyAction("mtr_required", false, null),
                        new GlobalPolicyAction(null, null, "Marking requirements apply; MTR not required by this policy.")
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

