using System.Text.RegularExpressions;
using PoApp.Core.Models;

namespace PoApp.Core.Services;

public sealed class GlobalPolicyEngine
{
    private static readonly Regex InExpression = new(
        @"^\s*(?<field>[A-Za-z0-9_]+)\s+(?<op>NOT\s+IN|IN)\s+(?<enum>[A-Za-z0-9_]+)\s*$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    private static readonly Regex EqualityExpression = new(
        @"^\s*(?<field>[A-Za-z0-9_]+)\s*==\s*(?<value>.+?)\s*$",
        RegexOptions.IgnoreCase | RegexOptions.Compiled);

    public PolicyEvaluationResult Evaluate(GlobalPolicyRecord policy, GlobalPolicyContext context)
    {
        var notes = new List<string>();
        var variables = BuildVariableMap(context);

        ApplyDerivedFields(policy, variables);

        var mtrRequired = context.MtrRequired;
        var isMtrLocked = false;
        var lockActionEncountered = false;
        var setActionEncountered = false;

        foreach (var rule in policy.Rules)
        {
            if (!EvaluateCondition(rule.Condition, variables, policy.Enums))
                continue;

            foreach (var action in rule.Actions)
            {
                if (!string.IsNullOrWhiteSpace(action.SetField) &&
                    string.Equals(action.SetField, "mtr_required", StringComparison.OrdinalIgnoreCase) &&
                    action.SetBooleanValue.HasValue)
                {
                    mtrRequired = action.SetBooleanValue.Value;
                    variables["mtr_required"] = mtrRequired;
                    setActionEncountered = true;
                }

                if (!string.IsNullOrWhiteSpace(action.LockField) &&
                    string.Equals(action.LockField, "mtr_required", StringComparison.OrdinalIgnoreCase) &&
                    action.LockValue.HasValue)
                {
                    isMtrLocked = action.LockValue.Value;
                    lockActionEncountered = true;
                }

                if (!string.IsNullOrWhiteSpace(action.AddPoNote))
                    notes.Add(action.AddPoNote!);
            }
        }

        if (!lockActionEncountered && setActionEncountered)
            isMtrLocked = true;

        return new PolicyEvaluationResult(
            mtrRequired,
            isMtrLocked,
            notes.Distinct(StringComparer.OrdinalIgnoreCase).ToList());
    }

    private static Dictionary<string, object?> BuildVariableMap(GlobalPolicyContext context)
    {
        return new Dictionary<string, object?>(StringComparer.OrdinalIgnoreCase)
        {
            ["code_use"] = context.CodeUse,
            ["item_type"] = context.ItemType,
            ["order_to_standard"] = context.OrderToStandard,
            ["marking_required"] = context.MarkingRequired,
            ["purchaser_requires_mtr"] = context.PurchaserRequiresMtr,
            ["mtr_required"] = context.MtrRequired
        };
    }

    private static void ApplyDerivedFields(
        GlobalPolicyRecord policy,
        Dictionary<string, object?> variables)
    {
        foreach (var field in policy.DerivedFields)
        {
            if (!string.Equals(field.Type, "boolean", StringComparison.OrdinalIgnoreCase))
                continue;

            var value = EvaluateCondition(field.Expression, variables, policy.Enums);
            variables[field.Id] = value;
        }
    }

    private static bool EvaluateCondition(
        string condition,
        IReadOnlyDictionary<string, object?> variables,
        IReadOnlyDictionary<string, IReadOnlyList<string>> enums)
    {
        if (string.IsNullOrWhiteSpace(condition))
            return false;

        var cleaned = condition.Replace("(", " ").Replace(")", " ");
        var clauses = Regex.Split(cleaned, @"\s+AND\s+", RegexOptions.IgnoreCase);
        foreach (var rawClause in clauses)
        {
            var clause = rawClause.Trim();
            if (clause.Length == 0)
                continue;

            if (!EvaluateClause(clause, variables, enums))
                return false;
        }

        return true;
    }

    private static bool EvaluateClause(
        string clause,
        IReadOnlyDictionary<string, object?> variables,
        IReadOnlyDictionary<string, IReadOnlyList<string>> enums)
    {
        var inMatch = InExpression.Match(clause);
        if (inMatch.Success)
        {
            var field = inMatch.Groups["field"].Value;
            var operation = inMatch.Groups["op"].Value.Replace(" ", string.Empty, StringComparison.OrdinalIgnoreCase);
            var enumName = inMatch.Groups["enum"].Value;

            if (!enums.TryGetValue(enumName, out var enumValues))
                return false;

            if (!TryGetString(variables, field, out var value))
                return false;

            var contains = enumValues.Any(enumValue =>
                string.Equals(enumValue, value, StringComparison.OrdinalIgnoreCase));

            if (operation.Equals("IN", StringComparison.OrdinalIgnoreCase))
                return contains;

            return !contains;
        }

        var equalityMatch = EqualityExpression.Match(clause);
        if (equalityMatch.Success)
        {
            var field = equalityMatch.Groups["field"].Value;
            var rawValue = equalityMatch.Groups["value"].Value.Trim();
            if (TryParseBooleanLiteral(rawValue, out var expectedBool))
            {
                if (!TryGetBool(variables, field, out var actualBool))
                    return false;

                return actualBool == expectedBool;
            }

            var expectedString = TrimQuotes(rawValue);
            if (!TryGetString(variables, field, out var actualString))
                return false;

            return string.Equals(actualString, expectedString, StringComparison.OrdinalIgnoreCase);
        }

        return false;
    }

    private static bool TryGetBool(
        IReadOnlyDictionary<string, object?> variables,
        string key,
        out bool value)
    {
        value = false;
        if (!variables.TryGetValue(key, out var rawValue) || rawValue is null)
            return false;

        if (rawValue is bool boolean)
        {
            value = boolean;
            return true;
        }

        if (rawValue is string text && bool.TryParse(text, out var parsed))
        {
            value = parsed;
            return true;
        }

        return false;
    }

    private static bool TryGetString(
        IReadOnlyDictionary<string, object?> variables,
        string key,
        out string value)
    {
        value = string.Empty;
        if (!variables.TryGetValue(key, out var rawValue) || rawValue is null)
            return false;

        if (rawValue is string text)
        {
            value = text;
            return true;
        }

        value = rawValue.ToString() ?? string.Empty;
        return !string.IsNullOrWhiteSpace(value);
    }

    private static bool TryParseBooleanLiteral(string value, out bool result)
    {
        if (string.Equals(value, "true", StringComparison.OrdinalIgnoreCase))
        {
            result = true;
            return true;
        }

        if (string.Equals(value, "false", StringComparison.OrdinalIgnoreCase))
        {
            result = false;
            return true;
        }

        result = false;
        return false;
    }

    private static string TrimQuotes(string value)
    {
        if (value.Length >= 2 &&
            ((value.StartsWith('"') && value.EndsWith('"')) ||
             (value.StartsWith('\'') && value.EndsWith('\''))))
        {
            return value.Substring(1, value.Length - 2);
        }

        return value;
    }
}
