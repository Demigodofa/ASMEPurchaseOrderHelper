using System.Collections.ObjectModel;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Windows;
using CommunityToolkit.Mvvm.ComponentModel;
using CommunityToolkit.Mvvm.Input;
using Microsoft.Win32;
using PoApp.Core.Models;
using PoApp.Core.Services;
using PoApp.Desktop.Services;

namespace PoApp.Desktop.ViewModels;

public partial class MainViewModel : ObservableObject
{
    public ObservableCollection<SpecSystemOption> SpecSystems { get; } = new();
    public ObservableCollection<MaterialSpecOption> MaterialSpecs { get; } = new();
    public ObservableCollection<string> GradeOptions { get; } = new();
    public ObservableCollection<string> ClassOptions { get; } = new();
    public ObservableCollection<UnsCandidate> UnsCandidates { get; } = new();
    public ObservableCollection<string> ItemTypes { get; } = new();
    public ObservableCollection<string> OrderToStandards { get; } = new();
    public ObservableCollection<OrderingFieldInput> OrderingFields { get; } = new();

    private readonly AsmeNormalizedDataset dataset;
    private readonly GlobalPolicyEngine policyEngine = new();
    private readonly PurchaseOrderBuilder purchaseOrderBuilder = new();
    private readonly Dictionary<string, SpecDefinitionRecord> specsByAsme;
    private readonly Dictionary<string, MaterialIndexRecord> materialsByBase;
    private readonly List<MaterialIndexRecord> sortedMaterials;

    private bool isApplyingPolicy;
    private bool lockedMtrRequiredValue;
    private string? selectedSpecBase;

    [ObservableProperty] private SpecDefinitionRecord? selectedSpec;
    [ObservableProperty] private SpecSystemOption? selectedSpecSystem;
    [ObservableProperty] private MaterialSpecOption? selectedMaterialSpec;
    [ObservableProperty] private string? selectedGrade;
    [ObservableProperty] private string? selectedClass;
    [ObservableProperty] private UnsCandidate? selectedUnsCandidate;
    [ObservableProperty] private string unsNumber = string.Empty;
    [ObservableProperty] private string astmEquivalencyInfo = string.Empty;
    [ObservableProperty] private string materialSpecWarning = string.Empty;
    [ObservableProperty] private string titleDisplay = string.Empty;
    [ObservableProperty] private string generatedText = string.Empty;
    [ObservableProperty] private string validationStatus = string.Empty;
    [ObservableProperty] private string policyStatus = string.Empty;
    [ObservableProperty] private bool hasOrderingFields;
    [ObservableProperty] private bool showGradeSelector;
    [ObservableProperty] private bool showClassSelector;
    [ObservableProperty] private bool codeUse = true;
    [ObservableProperty] private string? selectedItemType;
    [ObservableProperty] private string? selectedOrderToStandard;
    [ObservableProperty] private bool markingRequired;
    [ObservableProperty] private bool purchaserRequiresMtr;

    private bool mtrRequired;
    public bool MtrRequired
    {
        get => mtrRequired;
        set
        {
            if (!SetProperty(ref mtrRequired, value))
                return;

            if (IsMtrLocked && !isApplyingPolicy && mtrRequired != lockedMtrRequiredValue)
            {
                MessageBox.Show(
                    "MTR Required is locked by the active global policy for the selected context.",
                    "Policy Lock",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);

                SetProperty(ref mtrRequired, lockedMtrRequiredValue, nameof(MtrRequired));
                return;
            }

            Regenerate();
        }
    }

    private bool isMtrLocked;
    public bool IsMtrLocked
    {
        get => isMtrLocked;
        private set => SetProperty(ref isMtrLocked, value);
    }

    public MainViewModel()
    {
        dataset = NormalizedAsmeRepository.LoadFromRepoDataFolder();
        var uniqueSpecs = dataset.Specs
            .GroupBy(spec => spec.AsmeSpec, StringComparer.OrdinalIgnoreCase)
            .Select(static group => ChooseBestSpecDefinition(group))
            .ToList();

        var uniqueMaterials = dataset.MaterialIndex
            .GroupBy(entry => entry.SpecBase, StringComparer.OrdinalIgnoreCase)
            .Select(static group => MergeMaterialIndex(group))
            .ToList();

        specsByAsme = uniqueSpecs.ToDictionary(spec => spec.AsmeSpec, StringComparer.OrdinalIgnoreCase);
        materialsByBase = uniqueMaterials.ToDictionary(entry => entry.SpecBase, StringComparer.OrdinalIgnoreCase);
        sortedMaterials = uniqueMaterials
            .OrderBy(entry => ParseSpecBaseSortKey(entry.SpecBase))
            .ToList();

        SpecSystems.Add(new SpecSystemOption(string.Empty, "Select system..."));
        SpecSystems.Add(new SpecSystemOption("ASME", "ASME (SA/SB)"));
        SpecSystems.Add(new SpecSystemOption("ASTM", "ASTM (A/B)"));

        PopulatePolicyEnums();
        BuildUnsCandidates();

        SelectedSpecSystem = SpecSystems.FirstOrDefault();
        MtrRequired = true;
        Regenerate();
    }

    partial void OnSelectedSpecSystemChanged(SpecSystemOption? value)
    {
        var currentBase = selectedSpecBase;
        UpdateMaterialOptions();

        if (!string.IsNullOrWhiteSpace(currentBase))
        {
            SelectedMaterialSpec = MaterialSpecs.FirstOrDefault(option =>
                string.Equals(option.SpecBase, currentBase, StringComparison.OrdinalIgnoreCase));
        }

        UpdateAstmEquivalencyInfo();
        Regenerate();
    }

    partial void OnSelectedMaterialSpecChanged(MaterialSpecOption? value)
    {
        selectedSpecBase = value?.SpecBase;
        ApplyMaterialSelection(value?.SpecBase, null, null, null, preserveExistingGradeClass: false);
    }

    partial void OnSelectedGradeChanged(string? value)
    {
        UpdateUnsFromSelection();
    }

    partial void OnSelectedClassChanged(string? value)
    {
        UpdateUnsFromSelection();
    }

    partial void OnSelectedUnsCandidateChanged(UnsCandidate? value)
    {
        if (value is null)
            return;

        var targetSystem = CodeUse ? "ASME" : SelectedSpecSystem?.Key;
        if (string.IsNullOrWhiteSpace(targetSystem))
            targetSystem = CodeUse ? "ASME" : "ASTM";

        SelectedSpecSystem = SpecSystems.FirstOrDefault(option =>
            string.Equals(option.Key, targetSystem, StringComparison.OrdinalIgnoreCase));

        SelectedMaterialSpec = MaterialSpecs.FirstOrDefault(option =>
            string.Equals(option.SpecBase, value.SpecBase, StringComparison.OrdinalIgnoreCase));

        ApplyMaterialSelection(value.SpecBase, value.Grade, value.Class, value.Uns, preserveExistingGradeClass: true);
    }

    partial void OnSelectedItemTypeChanged(string? value)
    {
        ApplyPolicy();
        Regenerate();
    }

    partial void OnSelectedOrderToStandardChanged(string? value)
    {
        ApplyPolicy();
        Regenerate();
    }

    partial void OnMarkingRequiredChanged(bool value)
    {
        ApplyPolicy();
        Regenerate();
    }

    partial void OnPurchaserRequiresMtrChanged(bool value)
    {
        ApplyPolicy();
        Regenerate();
    }

    partial void OnCodeUseChanged(bool value)
    {
        ApplyPolicy();
        Regenerate();
    }

    partial void OnSelectedSpecChanged(SpecDefinitionRecord? value)
    {
        OrderingFields.Clear();

        if (value is null)
        {
            TitleDisplay = string.Empty;
            HasOrderingFields = false;
            ValidationStatus = "Select a material to load ordering requirements.";
            GeneratedText = string.Empty;
            return;
        }

        TitleDisplay = value.Title ?? string.Empty;
        UpdateAstmEquivalencyInfo();

        foreach (var definition in value.OrderingFields)
        {
            var input = new OrderingFieldInput(definition, value.SupplementaryRequirementsCatalog);
            input.ValueChanged += (_, _) => Regenerate();
            OrderingFields.Add(input);
        }

        HasOrderingFields = OrderingFields.Count > 0;
        ApplyPolicy();
        Regenerate();
    }

    [RelayCommand]
    private void Regenerate()
    {
        if (SelectedSpec is null)
        {
            GeneratedText = string.Empty;
            ValidationStatus = "Select a material to begin.";
            return;
        }

        var hardMissingFields = OrderingFields
            .Where(static field => field.IsRequired && !field.HasConditionalRequirement && !field.IsFilled)
            .Select(static field => field.Label)
            .ToList();

        ValidationStatus = hardMissingFields.Count == 0
            ? "All required fields provided."
            : $"Missing required fields: {string.Join(", ", hardMissingFields)}";

        var buildResult = BuildPurchaseOrderResult(SelectedSpec);
        GeneratedText = buildResult.Text;
    }

    [RelayCommand]
    private void CopyToClipboard()
    {
        if (!string.IsNullOrWhiteSpace(GeneratedText))
            Clipboard.SetText(GeneratedText);
    }

    [RelayCommand]
    private void Export()
    {
        if (SelectedSpec is null)
            return;

        var hardMissingFields = OrderingFields
            .Where(static field => field.IsRequired && !field.HasConditionalRequirement && !field.IsFilled)
            .Select(static field => field.Label)
            .ToList();

        if (hardMissingFields.Count > 0)
        {
            MessageBox.Show(
                $"Cannot export. Fill required fields first: {string.Join(", ", hardMissingFields)}",
                "Missing Required Fields",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        var result = BuildPurchaseOrderResult(SelectedSpec);

        var fileBase = SelectedMaterialSpec?.SpecDisplay ?? SelectedSpec.AsmeSpec;
        var dialog = new SaveFileDialog
        {
            Filter = "JSON files (*.json)|*.json",
            FileName = $"{SanitizeFileName(fileBase)}-po-export.json"
        };

        if (dialog.ShowDialog() != true)
            return;

        var json = JsonSerializer.Serialize(result.Export, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(dialog.FileName, json);

        var textPath = Path.ChangeExtension(dialog.FileName, ".txt");
        File.WriteAllText(textPath, result.Text);

        MessageBox.Show(
            $"Exported:\n- {dialog.FileName}\n- {textPath}",
            "Export Complete",
            MessageBoxButton.OK,
            MessageBoxImage.Information);
    }

    private void ApplyPolicy()
    {
        var policyResult = policyEngine.Evaluate(dataset.GlobalPolicy, BuildPolicyContext());

        isApplyingPolicy = true;
        lockedMtrRequiredValue = policyResult.MtrRequired;
        IsMtrLocked = policyResult.IsMtrLocked;
        MtrRequired = policyResult.MtrRequired;
        isApplyingPolicy = false;

        if (policyResult.Notes.Count == 0)
        {
            PolicyStatus = IsMtrLocked
                ? "Policy applied with no explicit note."
                : "No global policy lock for current context.";
            return;
        }

        PolicyStatus = string.Join(" ", policyResult.Notes);
    }

    private PurchaseOrderBuildResult BuildPurchaseOrderResult(SpecDefinitionRecord spec)
    {
        var filledFields = new List<FilledOrderingField>();
        var selectedSupplementaryRequirements = new List<string>();
        var supplementaryRequirementNotes = new List<string>();

        foreach (var field in OrderingFields)
        {
            var value = field.GetValue();
            if (field.IsFixedText)
            {
                filledFields.Add(new FilledOrderingField(field.Definition, string.Empty));
            }
            else if (!string.IsNullOrWhiteSpace(value))
                filledFields.Add(new FilledOrderingField(field.Definition, value));

            if (!field.IsSupplementarySelector)
                continue;

            var selectedCodes = field.GetSelectedValues();
            selectedSupplementaryRequirements.AddRange(selectedCodes);

            foreach (var selectedCode in selectedCodes)
            {
                var matchingRequirement = spec.SupplementaryRequirementsCatalog.FirstOrDefault(requirement =>
                    string.Equals(requirement.Code, selectedCode, StringComparison.OrdinalIgnoreCase));

                if (!string.IsNullOrWhiteSpace(matchingRequirement?.PurchaserMustSpecify))
                    supplementaryRequirementNotes.Add(matchingRequirement.PurchaserMustSpecify!);
            }
        }

        var policyResult = policyEngine.Evaluate(dataset.GlobalPolicy, BuildPolicyContext());

        var buildInput = new PurchaseOrderBuildInput(
            spec,
            BuildMaterialSelection(),
            CodeUse,
            ResolveOrderToStandardValue(),
            MtrRequired,
            policyResult.Notes,
            filledFields,
            selectedSupplementaryRequirements
                .Where(static code => !string.IsNullOrWhiteSpace(code))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList(),
            supplementaryRequirementNotes
                .Where(static note => !string.IsNullOrWhiteSpace(note))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList());

        return purchaseOrderBuilder.Build(buildInput);
    }

    private GlobalPolicyContext BuildPolicyContext()
    {
        return new GlobalPolicyContext(
            CodeUse,
            SelectedItemType ?? ItemTypes.FirstOrDefault() ?? "RawMaterial",
            ResolveOrderToStandardValue(),
            MarkingRequired,
            PurchaserRequiresMtr,
            MtrRequired);
    }

    private MaterialSelection BuildMaterialSelection()
    {
        var specSystem = SelectedSpecSystem?.Key ?? "ASME";
        var specDisplay = SelectedMaterialSpec?.SpecDisplay
                         ?? (SelectedSpec is not null ? SelectedSpec.AsmeSpec : "SA-UNKNOWN");
        return new MaterialSelection(
            specSystem,
            specDisplay,
            selectedSpecBase ?? string.Empty,
            SelectedGrade,
            SelectedClass,
            string.IsNullOrWhiteSpace(UnsNumber) ? null : UnsNumber,
            string.IsNullOrWhiteSpace(AstmEquivalencyInfo) ? null : AstmEquivalencyInfo);
    }

    private void ApplyMaterialSelection(
        string? specBase,
        string? preferredGrade,
        string? preferredClass,
        string? preferredUns,
        bool preserveExistingGradeClass)
    {
        if (string.IsNullOrWhiteSpace(specBase))
        {
            SelectedSpec = null;
            SelectedGrade = null;
            SelectedClass = null;
            UnsNumber = string.Empty;
            MaterialSpecWarning = string.Empty;
            ShowGradeSelector = false;
            ShowClassSelector = false;
            return;
        }

        if (!materialsByBase.TryGetValue(specBase, out var material))
        {
            SelectedSpec = null;
            MaterialSpecWarning = string.Empty;
            return;
        }

        MaterialSpecWarning = string.Empty;
        if (string.Equals(SelectedSpecSystem?.Key, "ASTM", StringComparison.OrdinalIgnoreCase) &&
            string.IsNullOrWhiteSpace(material.SpecAstm))
        {
            MaterialSpecWarning = "ASTM designation not available in index.";
        }

        var asmeSpec = material.SpecAsme ?? $"SA-{material.SpecBase}";
        specsByAsme.TryGetValue(asmeSpec, out var spec);
        SelectedSpec = spec;

        GradeOptions.Clear();
        foreach (var grade in material.Grades.Where(static g => !string.IsNullOrWhiteSpace(g)))
            GradeOptions.Add(grade);
        ShowGradeSelector = GradeOptions.Count > 0;

        ClassOptions.Clear();
        foreach (var @class in material.Classes.Where(static c => !string.IsNullOrWhiteSpace(c)))
            ClassOptions.Add(@class);
        ShowClassSelector = ClassOptions.Count > 0;

        if (!preserveExistingGradeClass)
        {
            SelectedGrade = GradeOptions.Count == 1 ? GradeOptions[0] : null;
            SelectedClass = ClassOptions.Count == 1 ? ClassOptions[0] : null;
        }

        if (!string.IsNullOrWhiteSpace(preferredGrade) && GradeOptions.Contains(preferredGrade))
            SelectedGrade = preferredGrade;
        if (!string.IsNullOrWhiteSpace(preferredClass) && ClassOptions.Contains(preferredClass))
            SelectedClass = preferredClass;

        if (!string.IsNullOrWhiteSpace(preferredUns))
            UnsNumber = preferredUns;
        else
            UpdateUnsFromSelection();

        UpdateAstmEquivalencyInfo();
    }

    private void UpdateUnsFromSelection()
    {
        if (string.IsNullOrWhiteSpace(selectedSpecBase))
        {
            UnsNumber = string.Empty;
            return;
        }

        if (!materialsByBase.TryGetValue(selectedSpecBase, out var material))
            return;

        var grade = string.IsNullOrWhiteSpace(SelectedGrade) ? null : SelectedGrade;
        var @class = string.IsNullOrWhiteSpace(SelectedClass) ? null : SelectedClass;

        var matches = material.GradeClassUns
            .Where(entry => Matches(entry.Grade, grade) && Matches(entry.Class, @class))
            .Select(entry => entry.Uns)
            .Where(static uns => !string.IsNullOrWhiteSpace(uns))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        if (matches.Count == 1)
        {
            UnsNumber = matches[0]!;
            return;
        }

        UnsNumber = string.Empty;
    }

    private void UpdateMaterialOptions()
    {
        MaterialSpecs.Clear();

        if (SelectedSpecSystem is null || string.IsNullOrWhiteSpace(SelectedSpecSystem.Key))
            return;

        foreach (var material in sortedMaterials)
        {
            var label = BuildMaterialLabel(material, SelectedSpecSystem.Key);
            var display = label;
            if (!string.IsNullOrWhiteSpace(material.SpecBase) && specsByAsme.TryGetValue(material.SpecAsme ?? $"SA-{material.SpecBase}", out var spec))
            {
                if (!string.IsNullOrWhiteSpace(spec.Title))
                    display = $"{label} - {spec.Title}";
            }

            MaterialSpecs.Add(new MaterialSpecOption(material.SpecBase, label, display));
        }
    }

    private void UpdateAstmEquivalencyInfo()
    {
        if (SelectedSpec is null)
        {
            AstmEquivalencyInfo = string.Empty;
            return;
        }

        if (!string.Equals(SelectedSpecSystem?.Key, "ASTM", StringComparison.OrdinalIgnoreCase))
        {
            AstmEquivalencyInfo = string.Empty;
            return;
        }

        AstmEquivalencyInfo = string.IsNullOrWhiteSpace(SelectedSpec.AstmIdentical)
            ? string.Empty
            : $"Equivalent to ASTM {SelectedSpec.AstmIdentical}";
    }

    private void PopulatePolicyEnums()
    {
        if (dataset.GlobalPolicy.Enums.TryGetValue("ITEM_TYPE", out var itemTypes))
        {
            foreach (var item in itemTypes)
                ItemTypes.Add(item);
        }

        if (ItemTypes.Count == 0)
            ItemTypes.Add("RawMaterial");

        if (dataset.GlobalPolicy.Enums.TryGetValue("ORDER_TO_STANDARD", out var standards))
        {
            foreach (var item in standards)
                OrderToStandards.Add(item);
        }

        if (OrderToStandards.Count == 0)
            OrderToStandards.Add("ASME BPVC Section II");

        SelectedItemType = ItemTypes.FirstOrDefault();
        SelectedOrderToStandard = OrderToStandards.FirstOrDefault();
    }

    private void BuildUnsCandidates()
    {
        var candidates = new List<UnsCandidate>();
        foreach (var material in dataset.MaterialIndex)
        {
            foreach (var entry in material.GradeClassUns)
            {
                if (string.IsNullOrWhiteSpace(entry.Uns))
                    continue;

                candidates.Add(new UnsCandidate(
                    entry.Uns!,
                    material.SpecBase,
                    entry.Grade,
                    entry.Class,
                    BuildUnsDisplay(entry.Uns!, material, entry.Grade, entry.Class)));
            }
        }

        foreach (var candidate in candidates
                     .DistinctBy(static candidate => candidate.Display, StringComparer.OrdinalIgnoreCase)
                     .OrderBy(static candidate => candidate.Uns, StringComparer.OrdinalIgnoreCase))
        {
            UnsCandidates.Add(candidate);
        }
    }

    private string ResolveOrderToStandardValue()
    {
        return string.IsNullOrWhiteSpace(SelectedOrderToStandard)
            ? "ASME BPVC Section II"
            : SelectedOrderToStandard.Trim();
    }

    private static string BuildMaterialLabel(MaterialIndexRecord material, string systemKey)
    {
        if (string.Equals(systemKey, "ASTM", StringComparison.OrdinalIgnoreCase))
            return material.SpecAstm ?? $"A{material.SpecBase}";

        return material.SpecAsme ?? $"SA-{material.SpecBase}";
    }

    private static string BuildUnsDisplay(
        string uns,
        MaterialIndexRecord material,
        string? grade,
        string? @class)
    {
        var parts = new List<string> { uns };
        var spec = material.SpecAsme ?? $"SA-{material.SpecBase}";
        parts.Add(spec);

        if (!string.IsNullOrWhiteSpace(grade))
            parts.Add($"Grade {grade}");
        if (!string.IsNullOrWhiteSpace(@class))
            parts.Add($"Class {@class}");

        return string.Join(" - ", parts);
    }

    private static bool Matches(string? value, string? expected)
    {
        if (string.IsNullOrWhiteSpace(value) && string.IsNullOrWhiteSpace(expected))
            return true;

        return string.Equals(value?.Trim(), expected?.Trim(), StringComparison.OrdinalIgnoreCase);
    }

    private static (int SortValue, string Suffix) ParseSpecBaseSortKey(string specBase)
    {
        if (string.IsNullOrWhiteSpace(specBase))
            return (int.MaxValue, string.Empty);

        var digits = new string(specBase.TakeWhile(char.IsDigit).ToArray());
        var suffix = specBase.Substring(digits.Length);

        return int.TryParse(digits, out var number)
            ? (number, suffix)
            : (int.MaxValue, specBase);
    }

    private static string SanitizeFileName(string value)
    {
        var invalidChars = Path.GetInvalidFileNameChars();
        var cleaned = new string(value.Select(ch => invalidChars.Contains(ch) ? '_' : ch).ToArray());
        return cleaned.Replace(' ', '_');
    }

    private static SpecDefinitionRecord ChooseBestSpecDefinition(IEnumerable<SpecDefinitionRecord> specs)
    {
        return specs
            .OrderByDescending(spec => spec.OrderingFields.Count)
            .ThenByDescending(spec => spec.Sources.Count)
            .First();
    }

    private static MaterialIndexRecord MergeMaterialIndex(IEnumerable<MaterialIndexRecord> entries)
    {
        var merged = entries.ToList();
        var first = merged[0];

        var specAsme = merged.Select(entry => entry.SpecAsme)
            .FirstOrDefault(value => !string.IsNullOrWhiteSpace(value));
        var specAstm = merged.Select(entry => entry.SpecAstm)
            .FirstOrDefault(value => !string.IsNullOrWhiteSpace(value));

        var systemsAvailable = merged
            .SelectMany(entry => entry.SystemsAvailable)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var grades = merged
            .SelectMany(entry => entry.Grades)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var classes = merged
            .SelectMany(entry => entry.Classes)
            .Where(static value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .ToList();

        var gradeClassUns = merged
            .SelectMany(entry => entry.GradeClassUns)
            .DistinctBy(entry => $"{entry.Grade}|{entry.Class}|{entry.Uns}", StringComparer.OrdinalIgnoreCase)
            .ToList();

        return new MaterialIndexRecord(
            first.SpecBase,
            specAsme,
            specAstm,
            systemsAvailable,
            grades,
            classes,
            gradeClassUns);
    }
}

public sealed partial class OrderingFieldInput : ObservableObject
{
    public OrderingFieldDefinition Definition { get; }

    public string Label => Definition.Prompt;
    public string? Note => Definition.Notes;
    public bool HasNote => !string.IsNullOrWhiteSpace(Note);
    public bool IsRequired => Definition.Required;
    public bool HasConditionalRequirement => !string.IsNullOrWhiteSpace(Definition.RequiredWhen);
    public string RequiredHint => HasConditionalRequirement ? "Required when applicable" : (IsRequired ? "Required" : "Optional");

    public bool IsBoolean => InputType is "boolean" or "boolean_select";
    public bool IsMultiSelect => InputType is "multi_select" or "sr_select" or "options_select";
    public bool IsSupplementarySelector => InputType is "sr_select";
    public bool IsNumberWithUnit => InputType is "number_with_unit";
    public bool IsEnum => InputType is "enum";
    public bool IsEnumOrText => InputType is "enum_or_text";
    public bool IsFixedText => InputType is "fixed_text";
    public bool HasSingleSelectOptions => IsEnum && Options.Count > 0;
    public bool HasEditableSelectOptions => IsEnumOrText && Options.Count > 0;
    public bool UsesTextInput => InputType is "text" or "number" or "composite" || (IsEnumOrText && Options.Count == 0);
    public bool HasUnits => Units.Count > 0;

    private string InputType { get; }

    public ObservableCollection<string> Options { get; } = new();
    public ObservableCollection<string> Units { get; } = new();
    public ObservableCollection<SelectableValue> MultiSelectOptions { get; } = new();

    [ObservableProperty] private string? textValue;
    [ObservableProperty] private string? selectedOption;
    [ObservableProperty] private bool? booleanValue;
    [ObservableProperty] private string? numberValue;
    [ObservableProperty] private string? selectedUnit;

    public bool IsFilled
    {
        get
        {
            if (IsFixedText)
                return true;
            if (IsBoolean)
                return BooleanValue.HasValue;
            if (IsMultiSelect)
                return MultiSelectOptions.Any(static option => option.IsSelected);
            if (IsNumberWithUnit)
                return !string.IsNullOrWhiteSpace(NumberValue);
            if (HasSingleSelectOptions)
                return !string.IsNullOrWhiteSpace(SelectedOption);
            if (HasEditableSelectOptions)
                return !string.IsNullOrWhiteSpace(SelectedOption);

            return !string.IsNullOrWhiteSpace(TextValue);
        }
    }

    public event EventHandler? ValueChanged;

    public OrderingFieldInput(
        OrderingFieldDefinition definition,
        IReadOnlyList<SupplementaryRequirementDefinition> supplementaryCatalog)
    {
        Definition = definition;
        InputType = (definition.InputType ?? string.Empty).Trim().ToLowerInvariant();

        foreach (var option in ResolveOptions(definition, supplementaryCatalog))
            Options.Add(option);

        foreach (var unit in definition.Units)
            Units.Add(unit);

        if (IsMultiSelect)
        {
            foreach (var option in Options)
            {
                var selectable = new SelectableValue(option);
                selectable.PropertyChanged += (_, args) =>
                {
                    if (args.PropertyName == nameof(SelectableValue.IsSelected))
                        RaiseValueChanged();
                };
                MultiSelectOptions.Add(selectable);
            }
        }

        if ((HasSingleSelectOptions || HasEditableSelectOptions) && Options.Count > 0)
            SelectedOption = Options[0];
        if (IsNumberWithUnit && Units.Count > 0)
            SelectedUnit = Units[0];
    }

    public string? GetValue()
    {
        if (IsFixedText)
            return string.Empty;
        if (IsBoolean)
            return BooleanValue.HasValue ? (BooleanValue.Value ? "Yes" : "No") : null;

        if (IsMultiSelect)
        {
            var selected = GetSelectedValues();
            return selected.Count == 0 ? null : string.Join(", ", selected);
        }

        if (IsNumberWithUnit)
        {
            if (string.IsNullOrWhiteSpace(NumberValue))
                return null;

            return string.IsNullOrWhiteSpace(SelectedUnit)
                ? NumberValue.Trim()
                : $"{NumberValue.Trim()} {SelectedUnit.Trim()}";
        }

        if (HasSingleSelectOptions || HasEditableSelectOptions)
            return string.IsNullOrWhiteSpace(SelectedOption) ? null : SelectedOption.Trim();

        return string.IsNullOrWhiteSpace(TextValue) ? null : TextValue.Trim();
    }

    public IReadOnlyList<string> GetSelectedValues()
    {
        if (!IsMultiSelect)
            return Array.Empty<string>();

        return MultiSelectOptions
            .Where(static option => option.IsSelected)
            .Select(static option => option.Value)
            .ToList();
    }

    partial void OnTextValueChanged(string? value) => RaiseValueChanged();
    partial void OnSelectedOptionChanged(string? value) => RaiseValueChanged();
    partial void OnBooleanValueChanged(bool? value) => RaiseValueChanged();
    partial void OnNumberValueChanged(string? value) => RaiseValueChanged();
    partial void OnSelectedUnitChanged(string? value) => RaiseValueChanged();

    private void RaiseValueChanged() => ValueChanged?.Invoke(this, EventArgs.Empty);

    private static IReadOnlyList<string> ResolveOptions(
        OrderingFieldDefinition definition,
        IReadOnlyList<SupplementaryRequirementDefinition> supplementaryCatalog)
    {
        if (definition.Options.Count > 0)
            return definition.Options;

        if (!string.Equals(definition.InputType, "sr_select", StringComparison.OrdinalIgnoreCase))
            return Array.Empty<string>();

        return supplementaryCatalog
            .Select(static item => item.Code)
            .Where(static code => !string.IsNullOrWhiteSpace(code))
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(static code => code, StringComparer.OrdinalIgnoreCase)
            .ToList();
    }
}

public sealed partial class SelectableValue : ObservableObject
{
    public SelectableValue(string value)
    {
        Value = value;
    }

    public string Value { get; }

    [ObservableProperty] private bool isSelected;
}

public sealed record SpecSystemOption(string Key, string Display);

public sealed record MaterialSpecOption(string SpecBase, string SpecDisplay, string DisplayLabel);

public sealed record UnsCandidate(string Uns, string SpecBase, string? Grade, string? Class, string Display);
