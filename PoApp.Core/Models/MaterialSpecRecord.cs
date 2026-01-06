namespace PoApp.Core.Models;

public sealed record MaterialSpecRecord(
    string SpecDesignation,
    string SpecPrefix,
    string SpecNumber,
    string AstmSpec,
    string AstmYear,
    MaterialCategory Category,
    IReadOnlyList<string> Grades,
    IReadOnlyList<string> OrderingNotes
);

public enum MaterialCategory
{
    Unknown = 0,
    Ferrous = 1,
    NonFerrous = 2,
    ElectrodeWire = 3
}
