namespace PoApp.Core.Models;

public sealed record MaterialSpecRecord(
    string AsmeSpec,
    string AstmSpec,
    string AstmYear,
    IReadOnlyList<string> Grades,
    IReadOnlyList<string> OrderingNotes
);
