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
    private const string MaterialIndexRecordType = "material_index";
    private readonly List<string> lastWarnings = [];

    public IReadOnlyList<string> LastWarnings => lastWarnings;

    public AsmeNormalizedDataset Load(string jsonlPath, string schemaPath)
    {
        if (!File.Exists(jsonlPath))
            throw new FileNotFoundException("JSONL dataset file was not found.", jsonlPath);
        if (!File.Exists(schemaPath))
            throw new FileNotFoundException("Schema file was not found.", schemaPath);

        ValidateSchema(schemaPath);

        lastWarnings.Clear();
        var errors = new List<string>();
        var specs = new List<SpecDefinitionRecord>();
        var materialIndex = new List<MaterialIndexRecord>();
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
                    var spec = ParseSpecDefinition(root, lineNumber, errors, lastWarnings);
                    if (spec is not null)
                        specs.Add(spec);
                    continue;
                }

                if (string.Equals(recordType, MaterialIndexRecordType, StringComparison.OrdinalIgnoreCase))
                {
                    var material = ParseMaterialIndex(root, lineNumber, errors);
                    if (material is not null)
                        materialIndex.Add(material);
                    continue;
                }

                errors.Add($"Line {lineNumber}: unknown record_type '{recordType}'.");
            }
        }

        if (globalPolicy is null)
            errors.Add("Dataset is missing a global_policy record.");

        if (specs.Count == 0)
            errors.Add("Dataset did not contain any spec_definition records.");

        if (materialIndex.Count == 0)
            errors.Add("Dataset did not contain any material_index records.");

        if (errors.Count > 0)
            throw new NormalizedDataValidationException(errors);

        return new AsmeNormalizedDataset(
            globalPolicy!,
            specs.OrderBy(static s => s.AsmeSpec, StringComparer.OrdinalIgnoreCase).ToList(),
            materialIndex.OrderBy(static entry => entry.SpecBase, StringComparer.OrdinalIgnoreCase).ToList());
    }

    private static void ValidateSchema(string schemaPath)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(schemaPath));
        var root = doc.RootElement;

        if (!root.TryGetProperty("oneOf", out var oneOf) || oneOf.ValueKind != JsonValueKind.Array)
            throw new InvalidDataException("Schema must define a top-level oneOf array.");

        var hasGlobalPolicySchema = false;
        var hasSpecSchema = false;
        var hasMaterialIndexSchema = false;

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
            if (string.Equals(value, MaterialIndexRecordType, StringComparison.OrdinalIgnoreCase))
                hasMaterialIndexSchema = true;
        }

        if (!hasGlobalPolicySchema || !hasSpecSchema || !hasMaterialIndexSchema)
        {
            throw new InvalidDataException(
                "Schema oneOf must include global_policy, spec_definition, and material_index records.");
        }
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
        var version = GetNullableString(root, "version");
        var inputsRequired = ReadStringArray(root, "inputs_required");
        var enums = ReadEnums(root, lineNumber, errors);
        var derivedFields = ReadDerivedFields(root, lineNumber, errors);
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
                var lockField = GetNullableString(actionElement, "lock");
                bool? setBooleanValue = null;
                bool? lockValue = null;
                if (actionElement.TryGetProperty("value", out var valueElement) &&
                    (valueElement.ValueKind == JsonValueKind.True || valueElement.ValueKind == JsonValueKind.False))
                {
                    setBooleanValue = valueElement.GetBoolean();
                    lockValue = valueElement.GetBoolean();
                }

                var addNote = GetNullableString(actionElement, "add_po_note");

                if (string.IsNullOrWhiteSpace(setField) &&
                    string.IsNullOrWhiteSpace(lockField) &&
                    string.IsNullOrWhiteSpace(addNote))
                    continue;

                actions.Add(new GlobalPolicyAction(setField, setBooleanValue, lockField, lockValue, addNote));
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
            version,
            description,
            inputsRequired,
            derivedFields,
            rules,
            enums);
    }

    private static SpecDefinitionRecord? ParseSpecDefinition(
        JsonElement root,
        int lineNumber,
        List<string> errors,
        List<string> warnings)
    {
        if (!TryGetRequiredString(root, "asme_spec", lineNumber, errors, out var asmeSpec))
            return null;

        if (!root.TryGetProperty("ordering_fields", out var orderingFieldsElement) ||
            orderingFieldsElement.ValueKind != JsonValueKind.Array)
        {
            warnings.Add($"Line {lineNumber}: spec_definition '{asmeSpec}' is missing ordering_fields array. Using empty field list.");
            orderingFieldsElement = default;
        }

        var orderingFields = new List<OrderingFieldDefinition>();
        if (orderingFieldsElement.ValueKind != JsonValueKind.Array)
        {
            return new SpecDefinitionRecord(
                asmeSpec,
                GetNullableString(root, "title"),
                GetNullableString(root, "astm_identical"),
                ReadStringArray(root, "sources"),
                orderingFields,
                ReadSupplementaryRequirements(root),
                ReadSpecRules(root),
                ReadSpecSystems(root, lineNumber, errors));
        }

        var fieldIndex = 0;
        foreach (var fieldElement in orderingFieldsElement.EnumerateArray())
        {
            fieldIndex++;
            if (fieldElement.ValueKind != JsonValueKind.Object)
            {
                warnings.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] is not an object; field skipped.");
                continue;
            }

            var prompt = GetNullableString(fieldElement, "prompt");
            var inputType = GetNullableString(fieldElement, "input_type");
            if (string.IsNullOrWhiteSpace(prompt) || string.IsNullOrWhiteSpace(inputType))
            {
                warnings.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] missing prompt or input_type; field skipped.");
                continue;
            }

            var required = false;
            if (!fieldElement.TryGetProperty("required", out var requiredElement))
            {
                warnings.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] missing 'required'; defaulting to false.");
            }
            else if (requiredElement.ValueKind == JsonValueKind.True || requiredElement.ValueKind == JsonValueKind.False)
            {
                required = requiredElement.GetBoolean();
            }
            else
            {
                warnings.Add($"Line {lineNumber}: ordering_fields[{fieldIndex}] has non-boolean 'required'; defaulting to false.");
            }

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
            ReadSpecRules(root),
            ReadSpecSystems(root, lineNumber, errors));
    }

    private static MaterialIndexRecord? ParseMaterialIndex(JsonElement root, int lineNumber, List<string> errors)
    {
        if (!TryGetRequiredString(root, "spec_base", lineNumber, errors, out var specBase))
            return null;

        if (!root.TryGetProperty("grade_class_uns", out var mappingElement) ||
            mappingElement.ValueKind != JsonValueKind.Array)
        {
            errors.Add($"Line {lineNumber}: material_index.grade_class_uns must be an array.");
            return null;
        }

        var mappings = new List<GradeClassUnsMapping>();
        var mapIndex = 0;
        foreach (var mapElement in mappingElement.EnumerateArray())
        {
            mapIndex++;
            if (mapElement.ValueKind != JsonValueKind.Object)
            {
                errors.Add($"Line {lineNumber}: material_index.grade_class_uns[{mapIndex}] must be an object.");
                continue;
            }

            var grade = GetNullableString(mapElement, "grade");
            var @class = GetNullableString(mapElement, "class");
            var uns = GetNullableString(mapElement, "uns");

            mappings.Add(new GradeClassUnsMapping(grade, @class, uns));
        }

        return new MaterialIndexRecord(
            specBase,
            GetNullableString(root, "spec_asme"),
            GetNullableString(root, "spec_astm"),
            ReadStringArray(root, "systems_available"),
            ReadStringArray(root, "grades"),
            ReadStringArray(root, "classes"),
            mappings);
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

    private static IReadOnlyList<DerivedFieldDefinition> ReadDerivedFields(
        JsonElement root,
        int lineNumber,
        List<string> errors)
    {
        var derivedFields = new List<DerivedFieldDefinition>();
        if (!root.TryGetProperty("derived_fields", out var derivedElement) ||
            derivedElement.ValueKind != JsonValueKind.Array)
            return derivedFields;

        var index = 0;
        foreach (var item in derivedElement.EnumerateArray())
        {
            index++;
            if (item.ValueKind != JsonValueKind.Object)
            {
                errors.Add($"Line {lineNumber}: derived_fields[{index}] must be an object.");
                continue;
            }

            var id = GetNullableString(item, "id");
            var type = GetNullableString(item, "type") ?? "boolean";
            var expression = GetNullableString(item, "expression");

            if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(expression))
            {
                errors.Add($"Line {lineNumber}: derived_fields[{index}] requires id and expression.");
                continue;
            }

            derivedFields.Add(new DerivedFieldDefinition(id, type, expression));
        }

        return derivedFields;
    }

    private static SpecSystemDefinition ReadSpecSystems(
        JsonElement root,
        int lineNumber,
        List<string> errors)
    {
        if (!root.TryGetProperty("spec_systems", out var systemsElement) ||
            systemsElement.ValueKind != JsonValueKind.Object)
        {
            errors.Add($"Line {lineNumber}: spec_definition.spec_systems must be an object.");
            return new SpecSystemDefinition("ASME", Array.Empty<string>(), null);
        }

        var primary = GetNullableString(systemsElement, "primary") ?? "ASME";
        var available = ReadStringArray(systemsElement, "available");
        if (available.Count == 0 && !string.IsNullOrWhiteSpace(primary))
            available = new List<string> { primary };

        var astmIdentical = GetNullableString(systemsElement, "astm_identical");

        return new SpecSystemDefinition(primary, available, astmIdentical);
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
