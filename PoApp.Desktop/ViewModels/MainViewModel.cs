using System.Collections.ObjectModel;
using System.IO;
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
    private static readonly IReadOnlyList<string> DefaultGoverningStandards =
    [
        "ASME BPVC Section II material",
        "ASME B16.5",
        "ASME B16.9",
        "ASME B16.11",
        "ASME B16.34",
        "Other (specify)"
    ];

    public ObservableCollection<SpecDefinitionRecord> Specs { get; } = new();
    public ObservableCollection<string> GoverningStandards { get; } = new();
    public ObservableCollection<OrderingFieldInput> OrderingFields { get; } = new();

    private readonly AsmeNormalizedDataset dataset;
    private readonly GlobalPolicyEngine policyEngine = new();
    private readonly PurchaseOrderBuilder purchaseOrderBuilder = new();

    private bool isApplyingPolicy;
    private bool lockedMtrRequiredValue;

    [ObservableProperty] private SpecDefinitionRecord? selectedSpec;
    [ObservableProperty] private bool codeUse = true;
    [ObservableProperty] private string? selectedGoverningStandard;
    [ObservableProperty] private string? otherGoverningStandard;
    [ObservableProperty] private string astmDisplay = string.Empty;
    [ObservableProperty] private string titleDisplay = string.Empty;
    [ObservableProperty] private string generatedText = string.Empty;
    [ObservableProperty] private string validationStatus = string.Empty;
    [ObservableProperty] private string policyStatus = string.Empty;
    [ObservableProperty] private bool hasOrderingFields;
    [ObservableProperty] private bool showOtherGoverningStandard;

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

        foreach (var standard in DefaultGoverningStandards)
            GoverningStandards.Add(standard);

        foreach (var spec in dataset.Specs.OrderBy(static spec => spec.AsmeSpec, StringComparer.OrdinalIgnoreCase))
            Specs.Add(spec);

        SelectedGoverningStandard = GoverningStandards.FirstOrDefault();
        MtrRequired = true;

        if (Specs.Count > 0)
            SelectedSpec = Specs[0];
        else
            Regenerate();
    }

    partial void OnSelectedSpecChanged(SpecDefinitionRecord? value)
    {
        OrderingFields.Clear();

        if (value is null)
        {
            AstmDisplay = string.Empty;
            TitleDisplay = string.Empty;
            HasOrderingFields = false;
            ValidationStatus = "No spec selected.";
            GeneratedText = string.Empty;
            return;
        }

        AstmDisplay = value.AstmIdentical ?? string.Empty;
        TitleDisplay = value.Title ?? string.Empty;

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

    partial void OnCodeUseChanged(bool value)
    {
        ApplyPolicy();
        Regenerate();
    }

    partial void OnSelectedGoverningStandardChanged(string? value)
    {
        ShowOtherGoverningStandard = string.Equals(value, "Other (specify)", StringComparison.OrdinalIgnoreCase);
        ApplyPolicy();
        Regenerate();
    }

    partial void OnOtherGoverningStandardChanged(string? value)
    {
        if (ShowOtherGoverningStandard)
        {
            ApplyPolicy();
            Regenerate();
        }
    }

    [RelayCommand]
    private void Regenerate()
    {
        if (SelectedSpec is null)
        {
            GeneratedText = string.Empty;
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

        var dialog = new SaveFileDialog
        {
            Filter = "JSON files (*.json)|*.json",
            FileName = $"{SanitizeFileName(SelectedSpec.AsmeSpec)}-po-export.json"
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
        var governingStandard = ResolveGoverningStandardValue();
        var policyResult = policyEngine.Evaluate(
            dataset.GlobalPolicy,
            CodeUse,
            governingStandard,
            MtrRequired);

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
            if (!string.IsNullOrWhiteSpace(value))
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

        var policyResult = policyEngine.Evaluate(
            dataset.GlobalPolicy,
            CodeUse,
            ResolveGoverningStandardValue(),
            MtrRequired);

        var buildInput = new PurchaseOrderBuildInput(
            spec,
            CodeUse,
            ResolveGoverningStandardValue(),
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

    private string ResolveGoverningStandardValue()
    {
        if (ShowOtherGoverningStandard)
            return string.IsNullOrWhiteSpace(OtherGoverningStandard) ? "Other (specify)" : OtherGoverningStandard.Trim();

        return string.IsNullOrWhiteSpace(SelectedGoverningStandard)
            ? "ASME BPVC Section II material"
            : SelectedGoverningStandard.Trim();
    }

    private static string SanitizeFileName(string value)
    {
        var invalidChars = Path.GetInvalidFileNameChars();
        var cleaned = new string(value.Select(ch => invalidChars.Contains(ch) ? '_' : ch).ToArray());
        return cleaned.Replace(' ', '_');
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
    public bool HasSingleSelectOptions => !IsMultiSelect && !IsBoolean && !IsNumberWithUnit && Options.Count > 0;
    public bool UsesTextInput => !IsBoolean && !IsMultiSelect && !IsNumberWithUnit && !HasSingleSelectOptions;
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
            if (IsBoolean)
                return BooleanValue.HasValue;
            if (IsMultiSelect)
                return MultiSelectOptions.Any(static option => option.IsSelected);
            if (IsNumberWithUnit)
                return !string.IsNullOrWhiteSpace(NumberValue);
            if (HasSingleSelectOptions)
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

        if (HasSingleSelectOptions && Options.Count > 0)
            SelectedOption = Options[0];
        if (IsNumberWithUnit && Units.Count > 0)
            SelectedUnit = Units[0];
    }

    public string? GetValue()
    {
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

        if (HasSingleSelectOptions)
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
