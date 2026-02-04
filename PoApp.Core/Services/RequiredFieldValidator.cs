using PoApp.Core.Models;

namespace PoApp.Core.Services;

public sealed class RequiredFieldValidator
{
    public IReadOnlyList<OrderingFieldDefinition> GetMissingRequiredFields(
        IReadOnlyList<OrderingFieldDefinition> definitions,
        IReadOnlyDictionary<string, string?> valuesByKey)
    {
        var missing = new List<OrderingFieldDefinition>();

        foreach (var definition in definitions)
        {
            if (!definition.Required)
                continue;
            if (!string.IsNullOrWhiteSpace(definition.RequiredWhen))
                continue;

            var key = ResolveFieldKey(definition);
            if (!valuesByKey.TryGetValue(key, out var value) || string.IsNullOrWhiteSpace(value))
                missing.Add(definition);
        }

        return missing;
    }

    public static string ResolveFieldKey(OrderingFieldDefinition definition)
    {
        if (!string.IsNullOrWhiteSpace(definition.Key))
            return definition.Key!;
        if (!string.IsNullOrWhiteSpace(definition.Id))
            return definition.Id!;

        return definition.Prompt;
    }
}

