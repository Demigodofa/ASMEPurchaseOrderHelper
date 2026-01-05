# Repository Guidelines

## Project Structure & Module Organization
This is a .NET solution organized by project:
- `PoApp.Core/` for domain and shared logic.
- `PoApp.Infrastructure/` for data access and EF Core integration.
- `PoApp.Ingest.Cli/` for the command-line entry point.
- `PoApp.Tests/` for xUnit-based unit tests.
- `PoApp.slnx` as the solution file to build the full workspace.

## Build, Test, and Development Commands
- `dotnet build PoApp.slnx` builds all projects in the solution.
- `dotnet run --project PoApp.Ingest.Cli` runs the CLI application.
- `dotnet test PoApp.Tests` executes the test project.
- `dotnet test PoApp.Tests --collect:"XPlat Code Coverage"` enables coverlet coverage collection.

## Coding Style & Naming Conventions
- C# defaults apply: 4-space indentation, PascalCase for types/methods, camelCase for locals/fields.
- Nullable reference types are enabled; avoid `null` unless the type is nullable.
- Keep filenames aligned with primary type names (e.g., `OrderService.cs`).

## Testing Guidelines
- Framework: xUnit (`PoApp.Tests/`).
- Follow current layout: one test project with files like `UnitTest1.cs`.
- Prefer descriptive test class names ending in `Tests` and method names like `Should_DoThing`.

## Commit & Pull Request Guidelines
- Git history only shows `Initial commit`, so no established convention yet.
- Recommended: imperative, short summaries (e.g., "Add order parser").
- PRs should include a short description, testing notes, and any relevant CLI output or screenshots.

## Configuration & Data
- EF Core is included in `PoApp.Infrastructure/`; keep connection strings and secrets out of source control.
- For local experiments, prefer `appsettings.Development.json` (not committed) and document any required keys in PRs.
