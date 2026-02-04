using System.Text.RegularExpressions;
using PoApp.Core.Models;

namespace PoApp.Core.Services;

public sealed class GlobalPolicyEngine
{
    private static readonly Regex CodeUseExpression = new(
        @"^\s*code_use\s*==\s*(true|false)\s*$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex GoverningStandardExpression = new(
        @"^\s*governing_standard\s*(IN|NOT\s+IN)\s*([A-Za-z0-9_]+)\s*$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public PolicyEvaluationResult Evaluate(
        GlobalPolicyRecord policy,
        bool codeUse,
        string governingStandard,
        bool currentMtrRequired)
    {
        var notes = new List<string>();
        var mtrRequired = currentMtrRequired;
        var isMtrLocked = false;

        foreach (var rule in policy.Rules)
        {
            if (!EvaluateCondition(rule.Condition, codeUse, governingStandard, policy.Enums))
                continue;

            foreach (var action in rule.Actions)
            {
                if (string.Equals(action.SetField, "mtr_required", StringComparison.OrdinalIgnoreCase) &&
                    action.SetBooleanValue.HasValue)
                {
                    mtrRequired = action.SetBooleanValue.Value;
                    isMtrLocked = true;
                }

                if (!string.IsNullOrWhiteSpace(action.AddPoNote))
                    notes.Add(action.AddPoNote!);
            }
        }

        return new PolicyEvaluationResult(
            mtrRequired,
            isMtrLocked,
            notes.Distinct(StringComparer.OrdinalIgnoreCase).ToList());
    }

    private static bool EvaluateCondition(
        string condition,
        bool codeUse,
        string governingStandard,
        IReadOnlyDictionary<string, IReadOnlyList<string>> enums)
    {
        if (string.IsNullOrWhiteSpace(condition))
            return false;

        var clauses = Regex.Split(condition, @"\s+AND\s+", RegexOptions.IgnoreCase);
        foreach (var rawClause in clauses)
        {
            var clause = rawClause.Trim();
            if (clause.Length == 0)
                continue;

            if (!EvaluateClause(clause, codeUse, governingStandard, enums))
                return false;
        }

        return true;
    }

    private static bool EvaluateClause(
        string clause,
        bool codeUse,
        string governingStandard,
        IReadOnlyDictionary<string, IReadOnlyList<string>> enums)
    {
        var codeUseMatch = CodeUseExpression.Match(clause);
        if (codeUseMatch.Success)
        {
            var expected = string.Equals(codeUseMatch.Groups[1].Value, "true", StringComparison.OrdinalIgnoreCase);
            return codeUse == expected;
        }

        var standardMatch = GoverningStandardExpression.Match(clause);
        if (standardMatch.Success)
        {
            var operation = standardMatch.Groups[1].Value;
            var enumName = standardMatch.Groups[2].Value;

            if (!enums.TryGetValue(enumName, out var enumValues))
                return false;

            var contains = enumValues.Any(value =>
                string.Equals(value, governingStandard, StringComparison.OrdinalIgnoreCase));

            if (operation.Equals("IN", StringComparison.OrdinalIgnoreCase))
                return contains;

            return !contains;
        }

        return false;
    }
}

