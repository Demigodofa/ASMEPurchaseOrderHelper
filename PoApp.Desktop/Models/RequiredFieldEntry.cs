using System.Collections.Generic;

namespace PoApp.Desktop.Models;

public sealed record RequiredFieldEntry(
    string Label,
    string? Value,
    string? Note,
    IReadOnlyList<string>? Options);
