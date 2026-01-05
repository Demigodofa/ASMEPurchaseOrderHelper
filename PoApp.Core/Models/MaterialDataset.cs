namespace PoApp.Core.Models;

public sealed record MaterialDataset(
    IReadOnlyList<MaterialSpecRecord> Materials
);
