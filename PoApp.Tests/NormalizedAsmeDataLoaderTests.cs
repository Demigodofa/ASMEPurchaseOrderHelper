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
            { "properties": { "record_type": { "const": "spec_definition" } } }
          ]
        }
        """);

        var jsonlPath = WriteTempFile("dataset.jsonl", """
        {"record_type":"global_policy","policy_id":"POL1","rules":[{"id":"R1","if":"code_use == true","then":[{"set":"mtr_required","value":true},{"add_po_note":"Provide report."}]}],"enums":{"B16_MARKING_ONLY":["ASME B16.5"]}}
        {"record_type":"spec_definition","asme_spec":"SA-TEST","title":"Test Spec","astm_identical":"A-1","ordering_fields":[{"id":"5.1","prompt":"Quantity","input_type":"text","required":true}]}
        """);

        var loader = new NormalizedAsmeDataLoader();
        var dataset = loader.Load(jsonlPath, schemaPath);

        Assert.Equal("POL1", dataset.GlobalPolicy.PolicyId);
        Assert.Single(dataset.Specs);
        Assert.Equal("SA-TEST", dataset.Specs[0].AsmeSpec);
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
            { "properties": { "record_type": { "const": "spec_definition" } } }
          ]
        }
        """);

        var jsonlPath = WriteTempFile("dataset.jsonl", """
        {"record_type":"global_policy","policy_id":"POL1","rules":[]}
        {"record_type":"spec_definition","ordering_fields":[]}
        """);

        var loader = new NormalizedAsmeDataLoader();
        var exception = Assert.Throws<NormalizedDataValidationException>(() => loader.Load(jsonlPath, schemaPath));

        Assert.Contains(exception.Errors, message => message.Contains("asme_spec", StringComparison.OrdinalIgnoreCase));
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

