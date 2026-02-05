namespace PoApp.Core.Models;

public sealed record AsmeNormalizedDataset(
    GlobalPolicyRecord GlobalPolicy,
    IReadOnlyList<SpecDefinitionRecord> Specs,
    IReadOnlyList<MaterialIndexRecord> MaterialIndex);

public sealed record GlobalPolicyRecord(
    string PolicyId,
    string? Version,
    string? Description,
    IReadOnlyList<string> InputsRequired,
    IReadOnlyList<DerivedFieldDefinition> DerivedFields,
    IReadOnlyList<GlobalPolicyRule> Rules,
    IReadOnlyDictionary<string, IReadOnlyList<string>> Enums);

public sealed record DerivedFieldDefinition(
    string Id,
    string Type,
    string Expression);

public sealed record GlobalPolicyRule(
    string Id,
    string Condition,
    IReadOnlyList<GlobalPolicyAction> Actions,
    string? Severity,
    string? Message);

public sealed record GlobalPolicyAction(
    string? SetField,
    bool? SetBooleanValue,
    string? LockField,
    bool? LockValue,
    string? AddPoNote);

public sealed record SpecDefinitionRecord(
    string AsmeSpec,
    string? Title,
    string? AstmIdentical,
    IReadOnlyList<string> Sources,
    IReadOnlyList<OrderingFieldDefinition> OrderingFields,
    IReadOnlyList<SupplementaryRequirementDefinition> SupplementaryRequirementsCatalog,
    IReadOnlyList<SpecRuleDefinition> Rules,
    SpecSystemDefinition SpecSystems);

public sealed record SpecSystemDefinition(
    string Primary,
    IReadOnlyList<string> Available,
    string? AstmIdentical);

public sealed record MaterialIndexRecord(
    string SpecBase,
    string? SpecAsme,
    string? SpecAstm,
    IReadOnlyList<string> SystemsAvailable,
    IReadOnlyList<string> Grades,
    IReadOnlyList<string> Classes,
    IReadOnlyList<GradeClassUnsMapping> GradeClassUns);

public sealed record GradeClassUnsMapping(
    string? Grade,
    string? Class,
    string? Uns);

public sealed record OrderingFieldDefinition(
    string? Id,
    string? Key,
    string Prompt,
    string InputType,
    bool Required,
    string? RequiredWhen,
    IReadOnlyList<string> Options,
    IReadOnlyList<string> Units,
    string? Notes,
    string? SourceRef);

public sealed record SupplementaryRequirementDefinition(
    string Code,
    string? Description,
    string? PurchaserMustSpecify);

public sealed record SpecRuleDefinition(
    string? Key,
    string? When,
    string? Then,
    string? Text);

public sealed record PolicyEvaluationResult(
    bool MtrRequired,
    bool IsMtrLocked,
    IReadOnlyList<string> Notes);

public sealed record GlobalPolicyContext(
    bool CodeUse,
    string ItemType,
    string OrderToStandard,
    bool MarkingRequired,
    bool PurchaserRequiresMtr,
    bool MtrRequired);

public sealed record FilledOrderingField(
    OrderingFieldDefinition Definition,
    string Value);

public sealed record PurchaseOrderBuildInput(
    SpecDefinitionRecord Spec,
    MaterialSelection Material,
    bool CodeUse,
    string GoverningStandard,
    bool MtrRequired,
    IReadOnlyList<string> PolicyNotes,
    IReadOnlyList<FilledOrderingField> FilledOrderingFields,
    IReadOnlyList<string> SelectedSupplementaryRequirements,
    IReadOnlyList<string> SupplementaryRequirementNotes);

public sealed record PurchaseOrderExportContext(
    bool CodeUse,
    string GoverningStandard,
    bool MtrRequired);

public sealed record MaterialSelection(
    string SpecSystem,
    string SpecDisplay,
    string SpecBase,
    string? Grade,
    string? Class,
    string? Uns,
    string? AstmEquivalencyInfo);

public sealed record PurchaseOrderExportSpec(
    string AsmeSpec,
    string? Title,
    string? AstmIdentical);

public sealed record PurchaseOrderExport(
    PurchaseOrderExportContext PoContext,
    PurchaseOrderExportSpec Spec,
    MaterialSelection Material,
    IReadOnlyDictionary<string, string> FieldValues,
    IReadOnlyList<string> SelectedSupplementaryRequirements);

public sealed record PurchaseOrderBuildResult(
    string Text,
    PurchaseOrderExport Export);
