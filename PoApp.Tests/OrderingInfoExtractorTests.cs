using PoApp.Core.Services;

namespace PoApp.Tests;

public class OrderingInfoExtractorTests
{
    [Fact]
    public void ExtractOrderingItems_HandlesVariantsAndNestedNumbers()
    {
        var text = """
        3. Ordering Information
        3.1 Quantity.
        3.1.1 Length.
        3.2 Size.
        4. Scope
        """;

        var items = OrderingInfoExtractor.ExtractOrderingItems(text);

        Assert.Equal(3, items.Count);
        Assert.Contains("Quantity.", items);
        Assert.Contains("Length.", items);
        Assert.Contains("Size.", items);
    }

    [Fact]
    public void ExtractOrderingItems_StopsAtNextSection()
    {
        var text = """
        3 Ordering Information
        3.1 Test report.
        4 Scope
        4.1 General.
        """;

        var items = OrderingInfoExtractor.ExtractOrderingItems(text);

        Assert.Single(items);
        Assert.Equal("Test report.", items[0]);
    }

    [Fact]
    public void ExtractOrderingItems_SkipsInformationItemsToBeConsidered()
    {
        var text = """
        3 Ordering Requirements
        3.1 Information items to be considered as applicable.
        3.2 Heat treatment.
        4 Scope
        """;

        var items = OrderingInfoExtractor.ExtractOrderingItems(text);

        Assert.Single(items);
        Assert.Equal("Heat treatment.", items[0]);
    }

    [Fact]
    public void ExtractOrderingItems_AcceptsInformationForOrderingHeader()
    {
        var text = """
        5. Information for Ordering
        5.1 Grade.
        6 General
        """;

        var items = OrderingInfoExtractor.ExtractOrderingItems(text);

        Assert.Single(items);
        Assert.Equal("Grade.", items[0]);
    }
}
