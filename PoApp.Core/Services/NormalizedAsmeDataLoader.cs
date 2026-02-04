using System.Text.Json;
using PoApp.Core.Models;

namespace PoApp.Core.Services;

public sealed class NormalizedDataValidationException : Exception
{
    public NormalizedDataValidationException(IReadOnlyList<string> errors)
        : base("Normalized ASME data failed validation.")
    {
        Errors = errors;
    }

    public IReadOnlyList<string> Errors { get; }
}

public sealed class NormalizedAsmeDataLoader
{
    private const string GlobalPolicyRecordType = "global_policy";
    private const string SpecDefinitionRecordType = "spec_definition";

    public AsmeNormalizedDataset Load(string jsonlPath, string schemaPath)
    {
        if (!File.Exists(jsonlPath))
            throw new FileNotFoundException("JSONL dataset file was not found.", jsonlPath);
        if (!File.Exists(schemaPath))
            throw new FileNotFoundException("Schema file was not found.", schemaPath);

        ValidateSchema(schemaPath);

        var errors = new List<string>();
        var specs = new List<SpecDefinitionRecord>();
        GlobalPolicyRecord? globalPolicy = null;
        var lineNumber = 0;

        foreach (var rawLine in File.ReadLines(jsonlPath))
        {
            lineNumber++;
            if (string.IsNullOrWhiteSpace(rawLine))
                continue;

            JsonDocument doc;
            try
            {
                doc = JsonDocument.Parse(rawLine);
            }
            catch (JsonException ex)
            {
                errors.Add($"Line {lineNumber}: invalid JSON ({ex.Message}).");
                continue;
            }

            using (doc)
            {
                var root = doc.RootElement;
                if (!TryGetRequiredString(root, "record_type", lineNumber, errors, out var recordType))
                    continue;

                if (string.Equals(recordType, GlobalPolicyRecordType, StringComparison.OrdinalIgnoreCase))
                {
                    if (globalPolicy is not null)
                    {
                        errors.Add($"Line {lineNumber}: duplicate global_policy record; only one is allowed.");
                        continue;
                    }

                    var parsedPolicy = ParseGlobalPolicy(root, lineNumber, errors);
                    if (parsedPolicy is not null)
                        globalPolicy = parsedPolicy;
                    continue;
                }

                if (string.Equals(recordType, SpecDefinitionRecordType, StringComparison.OrdinalIgnoreCase))
                {
                    var spec = ParseSpecDefinition(root, lineNumber, errors);
                    if (spec is not null)
                        specs.Add(spec);
                    continue;
                }

                errors.Add($"Line {lineNumber}: unknown record_type '{recordType}'.");
            }
        }

        if (globalPolicy is null)
            errors.Add("Dataset is missing a global_policy record.");

        if (specs.Count == 0)
            errors.Add("Dataset did not contain any spec_definition records.");

        if (errors.Count > 0)
            throw new NormalizedDataValidationException(errors);

        return new AsmeNormalizedDataset(
            globalPolicy!,
            specs.OrderBy(static s => s.AsmeSpec, StringComparer.OrdinalIgnoreCase).ToList());
    }

    private static void ValidateSchema(string schemaPath)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(schemaPath));
        var root = doc.RootElement;

        if (!root.TryGetProperty("oneOf", out var oneOf) || oneOf.ValueKind != JsonValueKind.Array)
            throw new InvalidDataException("Schema must define a top-level oneOf array.");

        var hasGlobalPolicySchema = false;
        var hasSpecSchema = false;

        foreach (var entry in oneOf.EnumerateArray())
        {
            if (!entry.TryGetProperty("properties", out var properties))
                continue;
            if (!properties.TryGetProperty("record_type", out var recordTypeProperty))
                continue;
            if (!recordTypeProperty.TryGetProperty("const", out var constValue))
                continue;

            var value = constValue.GetString();
            if (string.Equals(value, GlobalPolicyRecordType, StringComparison.OrdinalIgnoreCase))
                hasGlobalPolicySchema = true;
            if (string.Equals(value, SpecDefinitionRecordType, StringComparison.OrdinalIgnoreCase))
                hasSpecSchema = true;
        }

        if (!hasGlobalPolicySchema || !hasSpecSchema)
            throw new InvalidDataException("Schema oneOf must include both global_policy and spec_definition records.");
    }

    private static GlobalPolicyRecord? ParseGlobalPolicy(JsonElement root, int lineNumber, List<string> errors)
    {
        if (!TryGetRequiredString(root, "policy_id", lineNumber, errors, out var policyId))
            return null;

        if (!root.TryGetProperty("rules", out var rulesElement) || rulesElement.ValueKind != JsonValueKind.Array)
        {
            errors.Add($"Line {lineNumber}: global_policy.rules must be an array.");
            return null;
        }

        var description = GetNullableString(root, "description");
        var inputsRequired = ReadStringArray(root, "inputs_required");
        var enums = ReadEnums(root, lineNumber, errors);
        var rules = new List<GlobalPolicyRule>();

        var ruleIndex = 0;
        foreach (var ruleElement in rulesElement.EnumerateArray())
        {
            ruleIndex++;
            if (ruleElement.ValueKind != JsonValueKind.Object)
            {
                errors.Add($"Line {lineNumber}: global policy rule #{ruleIndex} must be an object.");
                continue;
            }

            var id = GetNullableString(ruleElement, "id") ?? $"rule_{ruleIndex}";
            var condition = GetNullableString(ruleElement, "if");
            if (string.IsNullOrWhiteSpace(condition))
            {
                errors.Add($"Line {lineNumber}: global policy rule '{id}' is missing condition ('if').");
                continue;
            }

            if (!ruleElement.TryGetProperty("then", out var thenElement) || thenElement.ValueKind != JsonValueKind.Array)
            {
                errors.Add($"Line {lineNumber}: global policy rule '{id}' must contain a then array.");
                continue;
            }

            var actions = new List<GlobalPolicyAction>();
            foreach (var actionElement in thenElement.EnumerateArray())
            {
                if (actionElement.ValueKind != JsonValueKind.Object)
                    continue;

                var setField = GetNullableString(actionElement, "set");
                bool? setBooleanValue = null;
                if (actionElement.TryGetProperty("value", out var valueElement) &&
                    (valueElement.ValueKind == JsonValueKind.True || valueElement.ValueKind == JsonValueKind.False))
                {
                    setBooleanValue = valueElement.GetBoolean();
                }

                var addNote = GetNullableString(actionElement, "add_po_note");

                if (string.IsNullOrWhiteSpace(setField) && string.IsNullOrWhiteSpace(addNote))
                    continue;

                actions.Add(new GlobalPolicyAction(setField, setBooleanValue, addNote));
            }

            rules.Add(new GlobalPolicyRule(
                id,
                condition,
                actions,
                GetNullableString(ruleElement, "severity"),
                GetNullableString(ruleElement, "message")));
        }

        return new GlobalPolicyRecord(
            policyId,
            description,
            inputsRequired,
            rules,
            enums);
    }

    private static SpecDefinitionRecord? ParseSpecDefinition(JsonElement root, int lineNumber, List<string> errors)
    {
        if (!TryGetRequiredString(root, "asme_spec", lineNumber, errors, out var asmeSpec))
            return null;

        if (!root.TryGetProperty("ordering_fields", out var orderingFieldsElement) ||
            orderingFieldsElement.ValueKind != JsonValueKind.Array)
        {
            errors.Add($"Line {lineNumber}: spec_definition '{asmeSpec}' is missing ordering_fields array.");
            return null;
        }

        var orderingFields = new List<OrderingFieldDefinition>();
        var fieldIndex = 0;
        foreach (var fieldElement in orderingFieldsElement.EnumerateArray())
        {
            fieldIndex++;
            if (fieldElement.ValueKind != JsonValueKind.Object)
            {
                errors.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] must be an object.");
                continue;
            }

            var prompt = GetNullableString(fieldElement, "prompt");
            var inputType = GetNullableString(fieldElement, "input_type");
            if (string.IsNullOrWhiteSpace(prompt) || string.IsNullOrWhiteSpace(inputType))
            {
                errors.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] requires prompt and input_type.");
                continue;
            }

            var required = false;
            if (!fieldElement.TryGetProperty("required", out var requiredElement) ||
                (requiredElement.ValueKind != JsonValueKind.True && requiredElement.ValueKind != JsonValueKind.False))
            {
                errors.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] requires boolean 'required'.");
                continue;
            }

            required = requiredElement.GetBoolean();

            orderingFields.Add(new OrderingFieldDefinition(
                GetNullableString(fieldElement, "id"),
                GetNullableString(fieldElement, "key"),
                prompt!,
                inputType!,
                required,
                GetNullableString(fieldElement, "required_when"),
                ReadStringArray(fieldElement, "options"),
                ReadStringArray(fieldElement, "units"),
                GetNullableString(fieldElement, "notes"),
                GetNullableString(fieldElement, "source_ref")));
        }

        return new SpecDefinitionRecord(
            asmeSpec,
            GetNullableString(root, "title"),
            GetNullableString(root, "astm_identical"),
            ReadStringArray(root, "sources"),
            orderingFields,
            ReadSupplementaryRequirements(root),
            ReadSpecRules(root));
    }

    private static IReadOnlyDictionary<string, IReadOnlyList<string>> ReadEnums(
        JsonElement root,
        int lineNumber,
        List<string> errors)
    {
        var values = new Dictionary<string, IReadOnlyList<string>>(StringComparer.OrdinalIgnoreCase);
        if (!root.TryGetProperty("enums", out var enumsElement))
            return values;
        if (enumsElement.ValueKind != JsonValueKind.Object)
        {
            errors.Add($"Line {lineNumber}: global_policy.enums must be an object.");
            return values;
        }

        foreach (var property in enumsElement.EnumerateObject())
        {
            if (property.Value.ValueKind != JsonValueKind.Array)
                continue;
            var enumValues = property.Value
                .EnumerateArray()
                .Where(static item => item.ValueKind == JsonValueKind.String)
                .Select(static item => item.GetString() ?? string.Empty)
                .Where(static item => !string.IsNullOrWhiteSpace(item))
                .ToList();

            values[property.Name] = enumValues;
        }

        return values;
    }

    private static IReadOnlyList<SupplementaryRequirementDefinition> ReadSupplementaryRequirements(JsonElement root)
    {
        var items = new List<SupplementaryRequirementDefinition>();
        if (!root.TryGetProperty("supplementary_requirements_catalog", out var catalogElement) ||
            catalogElement.ValueKind != JsonValueKind.Array)
            return items;

        foreach (var item in catalogElement.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.Object)
                continue;

            var code = GetNullableString(item, "code")
                       ?? GetNullableString(item, "sr")
                       ?? GetNullableString(item, "id");
            if (string.IsNullOrWhiteSpace(code))
                continue;

            var description = GetNullableString(item, "description")
                              ?? GetNullableString(item, "title")
                              ?? GetNullableString(item, "name");
            var purchaserMustSpecify = GetNullableString(item, "purchaser_must_specify")
                                       ?? GetNullableString(item, "purchaserMustSpecify")
                                       ?? GetNullableString(item, "prompt");

            items.Add(new SupplementaryRequirementDefinition(code, description, purchaserMustSpecify));
        }

        return items;
    }

    private static IReadOnlyList<SpecRuleDefinition> ReadSpecRules(JsonElement root)
    {
        var rules = new List<SpecRuleDefinition>();
        if (!root.TryGetProperty("rules", out var rulesElement) || rulesElement.ValueKind != JsonValueKind.Array)
            return rules;

        foreach (var item in rulesElement.EnumerateArray())
        {
            if (item.ValueKind == JsonValueKind.String)
            {
                rules.Add(new SpecRuleDefinition(null, null, null, item.GetString()));
                continue;
            }

            if (item.ValueKind != JsonValueKind.Object)
                continue;

            var key = GetNullableString(item, "key");
            var when = GetNullableString(item, "when");
            var then = GetNullableString(item, "then");
            var text = GetNullableString(item, "text");

            rules.Add(new SpecRuleDefinition(key, when, then, text));
        }

        return rules;
    }

    private static bool TryGetRequiredString(
        JsonElement element,
        string propertyName,
        int lineNumber,
        List<string> errors,
        out string value)
    {
        value = string.Empty;
        var stringValue = GetNullableString(element, propertyName);
        if (string.IsNullOrWhiteSpace(stringValue))
        {
            errors.Add($"Line {lineNumber}: missing required string property '{propertyName}'.");
            return false;
        }

        value = stringValue;
        return true;
    }

    private static string? GetNullableString(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var property))
            return null;
        if (property.ValueKind == JsonValueKind.Null)
            return null;
        if (property.ValueKind != JsonValueKind.String)
            return null;
        return property.GetString();
    }

    private static IReadOnlyList<string> ReadStringArray(JsonElement element, string propertyName)
    {
        if (!element.TryGetProperty(propertyName, out var property) || property.ValueKind != JsonValueKind.Array)
            return Array.Empty<string>();

        return property
            .EnumerateArray()
            .Where(static item => item.ValueKind == JsonValueKind.String)
            .Select(static item => item.GetString() ?? string.Empty)
            .Where(static item => !string.IsNullOrWhiteSpace(item))
            .ToList();
    }
}

