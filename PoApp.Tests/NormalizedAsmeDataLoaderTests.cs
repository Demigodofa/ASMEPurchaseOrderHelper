using PoApp.Core.Services;

namespace PoApp.Tests;

public sealed class NormalizedAsmeDataLoaderTests
{
    [Fact]
    public void Load_ParsesPolicyAndSpecRecords()
    {
        var schemaPath = WriteTempFile("schema.json", """
        {
          "oneOf": [
            { "properties": { "record_type": { "const": "global_policy" } } },
            { "properties": { "record_type": { "const": "spec_definition" } } },
            { "properties": { "record_type": { "const": "material_index" } } }
          ]
        }
        """);

        var jsonlPath = WriteTempFile("dataset.jsonl", """
        {"record_type":"global_policy","policy_id":"POL1","inputs_required":["code_use"],"rules":[{"id":"R1","if":"code_use == true","then":[{"set":"mtr_required","value":true},{"lock":"mtr_required","value":true},{"add_po_note":"Provide report."}]}],"enums":{"B16_MARKING_ONLY":["ASME B16.5"]}}
        {"record_type":"spec_definition","asme_spec":"SA-100","title":"Test Spec","astm_identical":"A-1","spec_systems":{"primary":"ASME","available":["ASME"]},"units_profile":"ImperialOnly","ordering_fields":[{"id":"5.1","key":"quantity","prompt":"Quantity","input_type":"text","required":true}]}
        {"record_type":"material_index","spec_base":"100","systems_available":["ASME"],"grade_class_uns":[{"grade":null,"class":null,"uns":"K00000"}]}
        """);

        var loader = new NormalizedAsmeDataLoader();
        var dataset = loader.Load(jsonlPath, schemaPath);

        Assert.Equal("POL1", dataset.GlobalPolicy.PolicyId);
        Assert.Single(dataset.Specs);
        Assert.Equal("SA-100", dataset.Specs[0].AsmeSpec);
        Assert.Single(dataset.Specs[0].OrderingFields);
        Assert.True(dataset.Specs[0].OrderingFields[0].Required);
    }

    [Fact]
    public void Load_Throws_WhenSpecIsMissingAsmeSpec()
    {
        var schemaPath = WriteTempFile("schema.json", """
        {
          "oneOf": [
            { "properties": { "record_type": { "const": "global_policy" } } },
            { "properties": { "record_type": { "const": "spec_definition" } } },
            { "properties": { "record_type": { "const": "material_index" } } }
          ]
        }
        """);

        var jsonlPath = WriteTempFile("dataset.jsonl", """
        {"record_type":"global_policy","policy_id":"POL1","inputs_required":["code_use"],"rules":[]}
        {"record_type":"spec_definition","ordering_fields":[]}
        {"record_type":"material_index","spec_base":"100","systems_available":["ASME"],"grade_class_uns":[{"grade":null,"class":null,"uns":"K00000"}]}
        """);

        var loader = new NormalizedAsmeDataLoader();
        var exception = Assert.Throws<NormalizedDataValidationException>(() => loader.Load(jsonlPath, schemaPath));

        Assert.Contains(exception.Errors, message => message.Contains("asme_spec", StringComparison.OrdinalIgnoreCase));
    }

    [Fact]
    public void Load_Throws_OnMalformedOrderingFields()
    {
        var schemaPath = WriteTempFile("schema.json", """
        {
          "oneOf": [
            { "properties": { "record_type": { "const": "global_policy" } } },
            { "properties": { "record_type": { "const": "spec_definition" } } },
            { "properties": { "record_type": { "const": "material_index" } } }
          ]
        }
        """);

        var jsonlPath = WriteTempFile("dataset.jsonl", """
        {"record_type":"global_policy","policy_id":"POL1","inputs_required":["code_use"],"rules":[]}
        {"record_type":"spec_definition","asme_spec":"SA-100","spec_systems":{"primary":"ASME","available":["ASME"]},"units_profile":"ImperialOnly","ordering_fields":[{"id":"5.1","key":"","prompt":"","input_type":"text","required":true},{"id":"5.2","key":"quantity","prompt":"Quantity","input_type":"text","required":"yes"},{"id":"5.3","key":"size","prompt":"Size","input_type":"text","required":true}]}
        {"record_type":"material_index","spec_base":"100","systems_available":["ASME"],"grade_class_uns":[{"grade":null,"class":null,"uns":"K00000"}]}
        """);

        var loader = new NormalizedAsmeDataLoader();
        var exception = Assert.Throws<NormalizedDataValidationException>(() => loader.Load(jsonlPath, schemaPath));

        Assert.Contains(exception.Errors, message => message.Contains("ordering_fields", StringComparison.OrdinalIgnoreCase));
    }

    private static string WriteTempFile(string fileName, string content)
    {
        var directory = Path.Combine(Path.GetTempPath(), "asme-po-tests", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var path = Path.Combine(directory, fileName);
        File.WriteAllText(path, content.Replace("\r\n", "\n"));
        return path;
    }
}
